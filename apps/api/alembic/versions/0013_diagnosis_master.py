"""Additive diagnosis catalogue and protected Visit selections."""
from alembic import op
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.core import Organization
from app.models.diagnosis import Diagnosis, VisitDiagnosis
from app.services.clinical_team import configure_permissions
from app.services.diagnoses import seed_catalogue

revision = "0013_diagnosis_master"
down_revision = "0012_clinical_team"
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    Diagnosis.__table__.create(bind, checkfirst=True)
    VisitDiagnosis.__table__.create(bind, checkfirst=True)
    db = Session(bind=bind)
    configure_permissions(db)
    for organization_id in db.scalars(select(Organization.organization_id)).all():
        seed_catalogue(db, organization_id)
    db.flush()


def downgrade():
    VisitDiagnosis.__table__.drop(op.get_bind(), checkfirst=True)
    Diagnosis.__table__.drop(op.get_bind(), checkfirst=True)
