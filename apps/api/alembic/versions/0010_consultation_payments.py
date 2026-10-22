"""Retry-safe collections, numbered receipts and organization policy versions."""
from alembic import op
revision = "0010_consultation_payments"
down_revision = "0009_visit_management"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE consultation_finance.policy_versions ADD COLUMN IF NOT EXISTS organization_id uuid REFERENCES core.organizations(organization_id) ON DELETE RESTRICT")
    for name,kind in (("payment_request_id","uuid"),("payment_request_hash","varchar(64)"),("receipt_number","varchar(120)")):
        op.execute(f"ALTER TABLE consultation_finance.payments ADD COLUMN IF NOT EXISTS {name} {kind}")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_consultation_payment_request ON consultation_finance.payments (received_by,payment_request_id)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_consultation_receipt_number ON consultation_finance.payments (receipt_number)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS consultation_finance.uq_consultation_payment_request")
    op.execute("DROP INDEX IF EXISTS consultation_finance.uq_consultation_receipt_number")
    for name in ("payment_request_id","payment_request_hash","receipt_number"):
        op.execute(f"ALTER TABLE consultation_finance.payments DROP COLUMN IF EXISTS {name}")
    op.execute("ALTER TABLE consultation_finance.policy_versions DROP COLUMN IF EXISTS organization_id")
