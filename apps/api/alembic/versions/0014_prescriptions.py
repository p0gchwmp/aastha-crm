"""Reviewed medicine catalogue and manual Doctor prescriptions."""
from alembic import op
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.core import Organization
from app.models.prescription import Medicine, PrescriptionLine
from app.services.clinical_team import configure_permissions
from app.services.prescriptions import seed_medicines

revision = "0014_prescriptions"
down_revision = "0013_diagnosis_master"
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    Medicine.__table__.create(bind, checkfirst=True)
    PrescriptionLine.__table__.create(bind, checkfirst=True)
    db = Session(bind=bind)
    configure_permissions(db)
    for organization_id in db.scalars(select(Organization.organization_id)).all():
        seed_medicines(db, organization_id)
    db.flush()


def downgrade():
    PrescriptionLine.__table__.drop(op.get_bind(), checkfirst=True)
    Medicine.__table__.drop(op.get_bind(), checkfirst=True)
