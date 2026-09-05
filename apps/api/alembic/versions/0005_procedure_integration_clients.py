"""Procedure integration client tenant scope.

Revision ID: 0005_integration_clients
Revises: 0004_change_request_tenant_scope
"""
from alembic import op

revision = "0005_integration_clients"
down_revision = "0004_change_request_tenant_scope"
branch_labels = None
depends_on = None


def upgrade():
    # The 0001 baseline builds current model metadata on fresh databases, so
    # every later upgrade must also be safe when these columns/FKs already exist.
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='integration' AND table_name='clients'
              AND column_name='organization_id'
          ) THEN
            ALTER TABLE integration.clients ADD COLUMN organization_id uuid;
          END IF;

          IF NOT EXISTS (
            SELECT 1
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.constraint_schema = kcu.constraint_schema
            JOIN information_schema.constraint_column_usage ccu
              ON tc.constraint_name = ccu.constraint_name
             AND tc.constraint_schema = ccu.constraint_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'integration'
              AND tc.table_name = 'clients'
              AND kcu.column_name = 'organization_id'
              AND ccu.table_schema = 'core'
              AND ccu.table_name = 'organizations'
              AND ccu.column_name = 'organization_id'
          ) THEN
            ALTER TABLE integration.clients
              ADD CONSTRAINT fk_integration_clients_organization
              FOREIGN KEY (organization_id)
              REFERENCES core.organizations(organization_id)
              ON DELETE RESTRICT;
          END IF;

          IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='integration' AND table_name='outbox_events'
              AND column_name='organization_id'
          ) THEN
            ALTER TABLE integration.outbox_events ADD COLUMN organization_id uuid;
          END IF;

          IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='integration' AND table_name='outbox_events'
              AND column_name='target_client_type'
          ) THEN
            ALTER TABLE integration.outbox_events
              ADD COLUMN target_client_type varchar(80);
          END IF;

          IF NOT EXISTS (
            SELECT 1
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.constraint_schema = kcu.constraint_schema
            JOIN information_schema.constraint_column_usage ccu
              ON tc.constraint_name = ccu.constraint_name
             AND tc.constraint_schema = ccu.constraint_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'integration'
              AND tc.table_name = 'outbox_events'
              AND kcu.column_name = 'organization_id'
              AND ccu.table_schema = 'core'
              AND ccu.table_name = 'organizations'
              AND ccu.column_name = 'organization_id'
          ) THEN
            ALTER TABLE integration.outbox_events
              ADD CONSTRAINT fk_outbox_events_organization
              FOREIGN KEY (organization_id)
              REFERENCES core.organizations(organization_id)
              ON DELETE RESTRICT;
          END IF;
        END $$;
        """
    )

    # Existing installations should assign connectors/events to the existing
    # organization before the columns become mandatory.
    op.execute(
        """
        UPDATE integration.clients
        SET organization_id = (
          SELECT organization_id FROM core.organizations ORDER BY created_at LIMIT 1
        )
        WHERE organization_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE integration.outbox_events
        SET organization_id = (
          SELECT organization_id FROM core.organizations ORDER BY created_at LIMIT 1
        )
        WHERE organization_id IS NULL
        """
    )
    op.execute(
        "ALTER TABLE integration.clients ALTER COLUMN organization_id SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE integration.outbox_events ALTER COLUMN organization_id SET NOT NULL"
    )


def downgrade():
    op.execute(
        "ALTER TABLE integration.outbox_events "
        "DROP COLUMN IF EXISTS target_client_type"
    )
    op.execute(
        "ALTER TABLE integration.outbox_events "
        "DROP COLUMN IF EXISTS organization_id"
    )
    op.execute(
        "ALTER TABLE integration.clients DROP COLUMN IF EXISTS organization_id"
    )
