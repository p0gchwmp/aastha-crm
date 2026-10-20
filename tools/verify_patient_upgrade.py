"""CI-only populated migration fixture; never run on a clinic database."""
import json,os,sys,uuid
from pathlib import Path
from sqlalchemy import create_engine,text
from sqlalchemy.orm import Session
from app.services.number_series import allocate_number
engine=create_engine(os.environ['DATABASE_URL'])
state=Path('/tmp/patient-upgrade-fixture.json')
if sys.argv[1]=='prepare':
    with engine.begin() as c:
        rows=c.execute(text('SELECT patient_id::text,uhid FROM patient.patients ORDER BY patient_id')).all()
        assert rows,'Patient HTTP tests must populate the database first'
        org=c.execute(text("SELECT organization_id FROM core.number_series WHERE series_code='UHID' LIMIT 1")).scalar_one()
        high=c.execute(text("SELECT max(current_number) FROM core.number_series WHERE organization_id=:o AND series_code='UHID'"),{'o':org}).scalar_one()+50
        c.execute(text("""INSERT INTO core.number_series (number_series_id,organization_id,series_code,prefix_template,current_number,reset_rule,fiscal_year,active,row_version)
            VALUES (:id,:org,'UHID','AAS-{NUMBER}',:high,'FISCAL_YEAR','2027-28',true,1)"""),{'id':uuid.uuid4(),'org':org,'high':high})
        state.write_text(json.dumps({'patients':[list(x) for x in rows],'org':str(org),'high':high}))
else:
    data=json.loads(state.read_text())
    with engine.connect() as c:
        rows=c.execute(text('SELECT patient_id::text,uhid FROM patient.patients ORDER BY patient_id')).all()
        assert [list(x) for x in rows]==data['patients'],'Existing Patient identities changed'
        active=c.execute(text("SELECT branch_id,fiscal_year,reset_rule,current_number FROM core.number_series WHERE organization_id=:o AND series_code='UHID' AND active"),{'o':uuid.UUID(data['org'])}).all()
        assert len(active)==1 and tuple(active[0])==(None,None,'NEVER',data['high']),active
    with Session(engine) as db:
        number=allocate_number(db,organization_id=uuid.UUID(data['org']),series_code='UHID',branch_id=None,fiscal_year=None)
        assert number==f"AAS-{data['high']+1:06d}",number
        db.rollback()
    print('Existing Patients unchanged; yearly UHID counters consolidated without reset; next global allocation verified')
