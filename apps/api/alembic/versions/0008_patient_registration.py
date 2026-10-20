"""Registration retries, recorded age and one non-resetting global UHID series."""
from alembic import op
revision = "0008_patient_registration"
down_revision = "0007_appointments"
branch_labels = None
depends_on = None


def upgrade():
    for name, kind in (("registration_request_id", "uuid"), ("registration_request_hash", "varchar(64)"), ("age_years", "integer"), ("age_recorded_on", "date")):
        op.execute(f"ALTER TABLE patient.patients ADD COLUMN IF NOT EXISTS {name} {kind}")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_patient_registration_request ON patient.patients (organization_id, created_by, registration_request_id)")
    # Old yearly rows remain as history. Keep one canonical active global counter,
    # advance beyond every allocated trailing number and never rewrite any UHID.
    op.execute("""DO $$ DECLARE org uuid; chosen uuid; highest bigint; BEGIN
      FOR org IN SELECT DISTINCT organization_id FROM core.number_series WHERE series_code='UHID' LOOP
        SELECT number_series_id INTO chosen FROM core.number_series WHERE organization_id=org AND series_code='UHID'
          ORDER BY active DESC, current_number DESC, created_at, number_series_id LIMIT 1;
        SELECT greatest(coalesce((SELECT max(current_number) FROM core.number_series WHERE organization_id=org AND series_code='UHID'),0),
          coalesce((SELECT max(substring(uhid from '([0-9]+)$')::numeric) FROM patient.patients WHERE organization_id=org AND uhid ~ '^AAS-[0-9]{1,9}$'),0)) INTO highest;
        UPDATE core.number_series SET active=false, row_version=row_version+1 WHERE organization_id=org AND series_code='UHID' AND number_series_id<>chosen;
        UPDATE core.number_series SET active=true,branch_id=NULL,fiscal_year=NULL,reset_rule='NEVER',current_number=highest,row_version=row_version+1 WHERE number_series_id=chosen;
      END LOOP;
    END $$""")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_active_global_uhid ON core.number_series (organization_id) WHERE series_code='UHID' AND active")


def downgrade():
    # Counter consolidation intentionally stays: never reset business identity numbers.
    op.execute("DROP INDEX IF EXISTS core.uq_active_global_uhid")
    op.execute("DROP INDEX IF EXISTS patient.uq_patient_registration_request")
    for name in ("registration_request_id", "registration_request_hash", "age_years", "age_recorded_on"):
        op.execute(f"ALTER TABLE patient.patients DROP COLUMN IF EXISTS {name}")
