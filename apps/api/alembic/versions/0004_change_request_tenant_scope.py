"""scope finance change requests to organization

Revision ID: 0004_change_request_tenant_scope
Revises: 0003_operational_hardening
Create Date: 2026-09-03
"""
from alembic import op

revision = "0004_change_request_tenant_scope"
down_revision = "0003_operational_hardening"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='consultation_finance' AND table_name='change_requests' AND column_name='organization_id'
          ) THEN
            ALTER TABLE consultation_finance.change_requests ADD COLUMN organization_id uuid;
            UPDATE consultation_finance.change_requests cr
              SET organization_id = u.organization_id
              FROM core.users u
              WHERE u.user_id = cr.requested_by AND cr.organization_id IS NULL;
            ALTER TABLE consultation_finance.change_requests ALTER COLUMN organization_id SET NOT NULL;
            ALTER TABLE consultation_finance.change_requests
              ADD CONSTRAINT fk_cf_change_request_org FOREIGN KEY (organization_id)
              REFERENCES core.organizations(organization_id);
          END IF;
        END $$;
        """
    )


def downgrade():
    op.execute("ALTER TABLE consultation_finance.change_requests DROP CONSTRAINT IF EXISTS fk_cf_change_request_org")
    op.execute("ALTER TABLE consultation_finance.change_requests DROP COLUMN IF EXISTS organization_id")
