"""Compare populated operational data through the additive Doctor upgrade in CI."""
import json, os, sys
from pathlib import Path
from sqlalchemy import create_engine, text
engine = create_engine(os.environ["DATABASE_URL"])
path = Path("/tmp/aastha-doctor-upgrade.json")
tables = ("patient.patients", "patient.patient_contacts", "crm.leads", "scheduling.appointments", "clinical.visits", "clinical.visit_complaints", "consultation_finance.consultation_bills", "consultation_finance.payments", "consultation_finance.entitlements", "core.number_series")
with engine.connect() as c:
    data = {t: c.execute(text("SELECT to_jsonb(t) FROM " + t + " AS t ORDER BY to_jsonb(t)::text")).scalars().all() for t in tables}
    encoded = json.dumps(data, sort_keys=True)
    if sys.argv[1] == "snapshot":
        assert data["patient.patients"] and data["clinical.visits"] and data["consultation_finance.payments"]
        path.write_text(encoded)
    else:
        assert path.read_text() == encoded, "Doctor migration changed existing clinic records"
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0011_doctor_consultation"
        assert c.execute(text("SELECT count(*) FROM clinical.consultation_notes")).scalar_one() == 0
print("Doctor migration preserved all existing operational contents and identities")
