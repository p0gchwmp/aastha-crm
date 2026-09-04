"""Procedure integration client tenant scope.

Revision ID: 0005_procedure_integration_clients
Revises: 0004_change_request_tenant_scope
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_procedure_integration_clients"
down_revision = "0004_change_request_tenant_scope"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "clients",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="integration",
    )
    op.create_foreign_key(
        "fk_integration_clients_organization",
        "clients",
        "organizations",
        ["organization_id"],
        ["organization_id"],
        source_schema="integration",
        referent_schema="core",
        ondelete="RESTRICT",
    )
    # Existing installations should assign every connector to the single Aastha organization before NOT NULL.
    op.execute('UPDATE integration.clients SET organization_id = (SELECT organization_id FROM core.organizations ORDER BY created_at LIMIT 1) WHERE organization_id IS NULL')
    op.alter_column("clients", "organization_id", nullable=False, schema="integration")

    op.add_column("outbox_events", sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True), schema="integration")
    op.add_column("outbox_events", sa.Column("target_client_type", sa.String(length=80), nullable=True), schema="integration")
    op.create_foreign_key(
        "fk_outbox_events_organization", "outbox_events", "organizations",
        ["organization_id"], ["organization_id"],
        source_schema="integration", referent_schema="core", ondelete="RESTRICT",
    )
    op.execute('UPDATE integration.outbox_events SET organization_id = (SELECT organization_id FROM core.organizations ORDER BY created_at LIMIT 1) WHERE organization_id IS NULL')
    op.alter_column("outbox_events", "organization_id", nullable=False, schema="integration")


def downgrade():
    op.drop_constraint("fk_outbox_events_organization", "outbox_events", schema="integration", type_="foreignkey")
    op.drop_column("outbox_events", "target_client_type", schema="integration")
    op.drop_column("outbox_events", "organization_id", schema="integration")
    op.drop_constraint("fk_integration_clients_organization", "clients", schema="integration", type_="foreignkey")
    op.drop_column("clients", "organization_id", schema="integration")
