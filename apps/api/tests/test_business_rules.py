from types import SimpleNamespace
from fastapi import HTTPException
from sqlalchemy import select
from app.models.crm import Lead
from app.services.dnc import apply_dnc_export_boundary, assert_outbound_allowed
from app.services.utils import normalize_mobile


def test_mobile_normalization_is_shared_number_safe():
    assert normalize_mobile("+91 98765-43210") == "9876543210"


def test_dnc_blocks_outbound_assignment():
    lead = SimpleNamespace(dnc=True)
    try:
        assert_outbound_allowed(lead)
        raise AssertionError("DNC should block outbound use")
    except HTTPException as exc:
        assert exc.status_code == 409


def test_non_dnc_allows_outbound_assignment():
    assert_outbound_allowed(SimpleNamespace(dnc=False))


def test_outbound_export_injects_dnc_filter():
    stmt = apply_dnc_export_boundary(select(Lead), "THIRD_PARTY_CALLING")
    sql = str(stmt)
    assert "leads.dnc" in sql


def test_internal_report_does_not_force_dnc_exclusion():
    stmt = apply_dnc_export_boundary(select(Lead), "INTERNAL_REPORTING")
    assert stmt.whereclause is None


def test_number_series_allocator_uses_row_lock():
    from types import SimpleNamespace
    from app.services.number_series import allocate_number
    import uuid

    class FakeDB:
        def __init__(self):
            self.statement = None
            self.series = SimpleNamespace(current_number=41, row_version=3, prefix_template="AAS/{FY}/{NUMBER}")
        def scalar(self, stmt):
            self.statement = stmt
            return self.series
        def flush(self):
            pass

    db = FakeDB()
    value = allocate_number(
        db,
        organization_id=uuid.uuid4(),
        series_code="TEST",
        branch_id=None,
        fiscal_year="2026-27",
    )
    assert value == "AAS/2026-27/000042"
    assert db.series.current_number == 42
    assert db.statement._for_update_arg is not None


def test_appointment_day_bounds_are_ist_aware():
    from datetime import date
    from app.api.routes.appointments import _local_bounds
    start, end = _local_bounds(date(2026, 9, 3))
    # Midnight IST is 18:30 UTC on the previous calendar day.
    assert start.isoformat().startswith("2026-09-02T18:30:00")
    assert end > start


def test_reception_vertical_slice_is_exposed_in_openapi():
    from app.main import app
    paths = app.openapi()["paths"]
    for path in [
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/meta/bootstrap",
        "/api/v1/dashboard/summary",
        "/api/v1/leads",
        "/api/v1/leads/{lead_id}/dnc",
        "/api/v1/leads/{lead_id}/reopen",
        "/api/v1/appointments",
        "/api/v1/appointments/availability",
    ]:
        assert path in paths
