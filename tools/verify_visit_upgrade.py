"""Disposable CI database only: compare original Visit fields through migration."""
import json, os, sys
from pathlib import Path
from sqlalchemy import create_engine, text
engine=create_engine(os.environ['DATABASE_URL'])
path=Path('/tmp/aastha-visit-upgrade.json')
with engine.connect() as c:
    visits=c.execute(text("SELECT to_jsonb(v) - ARRAY['creation_request_id','creation_request_hash','identity_confirmed_at','identity_patient_version'] FROM clinical.visits v ORDER BY visit_id")).scalars().all()
    complaints=c.execute(text('SELECT to_jsonb(v) FROM clinical.visit_complaints v ORDER BY visit_complaint_id')).scalars().all()
    patients=c.execute(text('SELECT patient_id::text,uhid FROM patient.patients ORDER BY patient_id')).all()
    data=json.dumps({'visits':visits,'complaints':complaints,'patients':[list(x) for x in patients]},sort_keys=True)
    if sys.argv[1]=='snapshot':
        assert visits and complaints
        path.write_text(data)
    else:
        assert path.read_text()==data, 'Existing encounter or Patient identity changed'
        assert c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()=='0015_patient_safety'
print('Visit migration content comparison passed')

