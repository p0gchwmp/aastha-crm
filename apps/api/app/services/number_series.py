import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.core import NumberSeries


class NumberSeriesError(RuntimeError):
    pass


def allocate_number(
    db: Session,
    *,
    organization_id: uuid.UUID,
    series_code: str,
    branch_id: uuid.UUID | None,
    fiscal_year: str | None,
    variables: dict[str, str] | None = None,
) -> str:
    """Allocate a business number using a row lock.

    Caller MUST invoke this inside the same DB transaction that finalizes the
    business record. This explicitly prevents read-increment-write races.
    """
    stmt = (
        select(NumberSeries)
        .where(
            NumberSeries.organization_id == organization_id,
            NumberSeries.series_code == series_code,
            NumberSeries.branch_id == branch_id,
            NumberSeries.fiscal_year == fiscal_year,
            NumberSeries.active.is_(True),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    series = db.scalar(stmt)
    if not series:
        raise NumberSeriesError(f"Number series not configured: {series_code}")

    series.current_number += 1
    series.row_version += 1
    values = {
        "NUMBER": f"{series.current_number:06d}",
        "FY": fiscal_year or "",
        **(variables or {}),
    }
    number = series.prefix_template
    for key, value in values.items():
        number = number.replace("{" + key + "}", value)
    db.flush()
    return number
