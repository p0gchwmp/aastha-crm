"""Clinical team access and protected Assistant handover."""
from alembic import op
from sqlalchemy.orm import Session
from app.models.preparation import ClinicalPreparation, PreparationRevision
from app.services.clinical_team import configure_permissions
revision = "0012_clinical_team"
down_revision = "0011_doctor_consultation"
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    ClinicalPreparation.__table__.create(bind, checkfirst=True)
    PreparationRevision.__table__.create(bind, checkfirst=True)
    configure_permissions(Session(bind=bind))


def downgrade():
    PreparationRevision.__table__.drop(op.get_bind(), checkfirst=True)
    ClinicalPreparation.__table__.drop(op.get_bind(), checkfirst=True)
