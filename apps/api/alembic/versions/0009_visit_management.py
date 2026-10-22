"""Add Visit retry and verification evidence without rewriting existing encounters."""
from alembic import op
revision = "0009_visit_management"
down_revision = "0008_patient_registration"
branch_labels = None
depends_on = None


def upgrade():
    for name, kind in (("creation_request_id", "uuid"), ("creation_request_hash", "varchar(64)"),
                       ("identity_confirmed_at", "timestamptz"), ("identity_patient_version", "integer")):
        op.execute(f"ALTER TABLE clinical.visits ADD COLUMN IF NOT EXISTS {name} {kind}")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_visit_creation_request ON clinical.visits (created_by, creation_request_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_visits_branch_checkin ON clinical.visits (branch_id, checkin_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_visits_patient_checkin ON clinical.visits (patient_id, checkin_at)")


def downgrade():
    for name in ("uq_visit_creation_request", "ix_visits_branch_checkin", "ix_visits_patient_checkin"):
        op.execute(f"DROP INDEX IF EXISTS clinical.{name}")
    for name in ("creation_request_id", "creation_request_hash", "identity_confirmed_at", "identity_patient_version"):
        op.execute(f"ALTER TABLE clinical.visits DROP COLUMN IF EXISTS {name}")
