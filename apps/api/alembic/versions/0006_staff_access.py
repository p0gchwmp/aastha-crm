"""Reception staff administration and revocable sessions."""
from alembic import op

revision = "0006_staff_access"
down_revision = "0005_integration_clients"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE core.users ADD COLUMN IF NOT EXISTS session_version integer NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE core.users ADD COLUMN IF NOT EXISTS must_change_password boolean NOT NULL DEFAULT false")
    # Login accepts a username without tenant selection, so uniqueness must be global.
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_users_login ON core.users (lower(username))")
    op.execute("""
        INSERT INTO core.permissions (permission_id, code, name)
        VALUES ('6915f4bc-7587-481a-8c21-3bb30b005986', 'STAFF_MANAGE', 'Manage Reception Staff')
        ON CONFLICT (code) DO NOTHING
    """)
    op.execute("""
        INSERT INTO core.role_permissions (role_permission_id, role_id, permission_id)
        SELECT md5(r.role_id::text || p.permission_id::text)::uuid, r.role_id, p.permission_id
        FROM core.roles r CROSS JOIN core.permissions p
        WHERE r.code IN ('ADMIN', 'SUPER_ADMIN') AND p.code = 'STAFF_MANAGE'
        ON CONFLICT (role_id, permission_id) DO NOTHING
    """)


def downgrade():
    op.execute("DELETE FROM core.role_permissions WHERE permission_id IN (SELECT permission_id FROM core.permissions WHERE code='STAFF_MANAGE')")
    op.execute("DELETE FROM core.permissions WHERE code='STAFF_MANAGE'")
    op.execute("DROP INDEX IF EXISTS core.ux_users_login")
    op.execute("ALTER TABLE core.users DROP COLUMN IF EXISTS must_change_password")
    op.execute("ALTER TABLE core.users DROP COLUMN IF EXISTS session_version")
