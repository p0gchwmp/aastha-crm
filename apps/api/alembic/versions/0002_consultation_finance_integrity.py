"""consultation finance integrity constraints

Revision ID: 0002_consultation_finance_integrity
Revises: 0001_initial
Create Date: 2026-09-03

Idempotent because the pre-production 0001 baseline uses model metadata on fresh installs.
This revision upgrades databases created by the prior Patient/Visit milestone.
"""
from alembic import op

revision = "0002_consultation_finance_integrity"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    # Existing milestone databases had source_bill_id without a real FK/unique
    # guarantee. Add them only when absent so both fresh and upgraded databases work.
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint c
            WHERE c.conrelid = 'consultation_finance.entitlements'::regclass
              AND c.contype = 'f'
              AND pg_get_constraintdef(c.oid) LIKE '%source_bill_id%consultation_finance.consultation_bills%'
          ) THEN
            ALTER TABLE consultation_finance.entitlements
              ADD CONSTRAINT fk_cf_entitlement_source_bill
              FOREIGN KEY (source_bill_id)
              REFERENCES consultation_finance.consultation_bills(consultation_bill_id);
          END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint c
            WHERE c.conrelid = 'consultation_finance.entitlements'::regclass
              AND c.contype = 'u'
              AND pg_get_constraintdef(c.oid) LIKE '%(source_bill_id)%'
          ) THEN
            ALTER TABLE consultation_finance.entitlements
              ADD CONSTRAINT uq_cf_entitlement_source_bill UNIQUE (source_bill_id);
          END IF;
        END $$;
        """
    )


def downgrade():
    op.execute("ALTER TABLE consultation_finance.entitlements DROP CONSTRAINT IF EXISTS uq_cf_entitlement_source_bill")
    op.execute("ALTER TABLE consultation_finance.entitlements DROP CONSTRAINT IF EXISTS fk_cf_entitlement_source_bill")
