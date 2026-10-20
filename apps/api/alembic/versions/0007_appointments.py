"""Appointment retry protection and versioned schedule exceptions; additive upgrade."""
from alembic import op
revision = "0007_appointments"
down_revision = "0006_staff_access"
branch_labels = None
depends_on = None

def upgrade():
    op.execute("ALTER TABLE scheduling.appointments ADD COLUMN IF NOT EXISTS booking_request_id uuid")
    op.execute("ALTER TABLE scheduling.appointments ADD COLUMN IF NOT EXISTS booking_request_hash varchar(64)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_appointment_request ON scheduling.appointments (organization_id, created_by, booking_request_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_appointment_doctor_window ON scheduling.appointments (doctor_id, scheduled_start, scheduled_end)")
    for name, definition in (("row_version","bigint NOT NULL DEFAULT 1"),("created_at","timestamptz NOT NULL DEFAULT now()"),("updated_at","timestamptz NOT NULL DEFAULT now()"),("slot_duration_minutes","integer NOT NULL DEFAULT 15"),("note","varchar(500)")):
        op.execute(f"ALTER TABLE scheduling.schedule_exceptions ADD COLUMN IF NOT EXISTS {name} {definition}")
    op.execute("""INSERT INTO core.permissions (permission_id,code,name) VALUES ('aec928d5-5694-4eda-87f2-4d65bac29f07','APPOINTMENT_SCHEDULE_MANAGE','Manage Doctor Schedules') ON CONFLICT(code) DO NOTHING""")
    op.execute("""INSERT INTO core.role_permissions (role_permission_id,role_id,permission_id)
        SELECT md5(r.role_id::text || p.permission_id::text)::uuid,r.role_id,p.permission_id
        FROM core.roles r CROSS JOIN core.permissions p
        WHERE r.code IN ('ADMIN','SUPER_ADMIN') AND p.code='APPOINTMENT_SCHEDULE_MANAGE'
        ON CONFLICT(role_id,permission_id) DO NOTHING""")

def downgrade():
    op.execute("DELETE FROM core.role_permissions WHERE permission_id IN (SELECT permission_id FROM core.permissions WHERE code='APPOINTMENT_SCHEDULE_MANAGE')")
    op.execute("DELETE FROM core.permissions WHERE code='APPOINTMENT_SCHEDULE_MANAGE'")
    op.execute("DROP INDEX IF EXISTS scheduling.uq_appointment_request")
    op.execute("DROP INDEX IF EXISTS scheduling.ix_appointment_doctor_window")
    for name in ("booking_request_id","booking_request_hash"):
        op.execute(f"ALTER TABLE scheduling.appointments DROP COLUMN IF EXISTS {name}")
    for name in ("row_version","created_at","updated_at","slot_duration_minutes","note"):
        op.execute(f"ALTER TABLE scheduling.schedule_exceptions DROP COLUMN IF EXISTS {name}")
