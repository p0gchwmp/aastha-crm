"""Add structured, versioned clinical safety records without changing existing notes."""
from alembic import op
from app.models.safety import SafetyAssessment, SafetyEntry, SafetyRevision
revision = "0015_patient_safety"
down_revision = "0014_prescriptions"
branch_labels = depends_on = None

def upgrade():
    for model in (SafetyAssessment, SafetyEntry, SafetyRevision):
        model.__table__.create(op.get_bind(), checkfirst=True)

def downgrade():
    for model in (SafetyRevision, SafetyEntry, SafetyAssessment):
        model.__table__.drop(op.get_bind(), checkfirst=True)
