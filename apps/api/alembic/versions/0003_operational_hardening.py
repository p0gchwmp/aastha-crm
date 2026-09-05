"""operational hardening: import tenant scope

Revision ID: 0003_operational_hardening
Revises: 0002_finance_integrity
Create Date: 2026-09-03
"""
from alembic import op

revision = "0003_operational_hardening"
down_revision = "0002_finance_integrity"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='patient' AND table_name='import_batches' AND column_name='organization_id'
          ) THEN
            ALTER TABLE patient.import_batches ADD COLUMN organization_id uuid;
            UPDATE patient.import_batches b
              SET organization_id = u.organization_id
              FROM core.users u
              WHERE u.user_id = b.uploaded_by AND b.organization_id IS NULL;
            ALTER TABLE patient.import_batches ALTER COLUMN organization_id SET NOT NULL;
            ALTER TABLE patient.import_batches
              ADD CONSTRAINT fk_patient_import_batch_org FOREIGN KEY (organization_id)
              REFERENCES core.organizations(organization_id);
          END IF;
        END $$;
        """
    )


def downgrade():
    op.execute("ALTER TABLE patient.import_batches DROP CONSTRAINT IF EXISTS fk_patient_import_batch_org")
    op.execute("ALTER TABLE patient.import_batches DROP COLUMN IF EXISTS organization_id")
