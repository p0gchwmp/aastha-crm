"""Manual prescribing, explicit product verification, privacy and retry protection."""
import json
import uuid
from pathlib import Path
import pytest
from sqlalchemy import select
from test_staff_access import clinic
from test_lead_register import leads
from test_appointments import scheduling
from test_patient_registration import registration
from test_visit_management import encounters
from test_doctor_consultations import clinical
from app.models.prescription import Medicine, PrescriptionLine
from app.services.clinical_team import configure_permissions
from app.services.prescriptions import seed_medicines

M="/api/v1/medicines"
D="/api/v1/doctor-consultations"


@pytest.fixture
def prescribing(clinical):
    (c,db,branches,users,admin,login),h,*_=clinical
    configure_permissions(db);seed_medicines(db,users["DOCTOR"].organization_id);db.commit()
    return clinical


def product(c,h,**extra):
    body={"brand":"Fictional Medicine","generic":"Fictional composition","strength":"Test strength","form":"Test form","route":"Test route","active":True,"review_confirmed":True,**extra}
    r=c.post(M,headers=h,json=body);assert r.status_code==201,r.text
    return r.json()


def line(m,**extra):
    return {"line_id":str(uuid.uuid4()),"medicine_id":m["medicine_id"],"medicine_version":m["row_version"],"dose":"Fictional amount","frequency":"Fictional frequency","duration":"Fictional duration","route":m["route"],"quantity":"Fictional quantity","site":"Fictional site","instructions":"Fictional instructions",**extra}


def patch(m,**extra):
    return {**{f:m[f] for f in ("brand","generic","strength","form","route","pack_size","manufacturer","active")},"row_version":m["row_version"],"reason":"Test catalogue correction",**extra}


def test_import_is_inactive_and_idempotent_with_source_provenance(prescribing):
    (c,db,branches,users,admin,login),h,*_=prescribing
    source=json.loads((Path(__file__).parents[1]/"app/data/medicines_v11.json").read_text())
    rows=c.get(M+"?include_inactive=true&limit=250",headers=h).json()+c.get(M+"?include_inactive=true&offset=250&limit=250",headers=h).json()
    assert len(source["entries"])==len(rows)==352
    assert sum(not m["generic"] for m in rows)==294
    assert all(not m["active"] and m["requires_review"] for m in rows)
    assert c.get(M,headers=h).json()==[]
    first=rows[0];r=c.patch(M+"/"+first["medicine_id"],headers=admin,json=patch(first,brand="Source entry renamed"));assert r.status_code==200,r.text
    seed_medicines(db,users["DOCTOR"].organization_id);db.commit()
    assert c.get(M+"?include_inactive=true&q=Source%20entry%20renamed",headers=h).json()[0]["medicine_id"]==first["medicine_id"]


def test_catalogue_verification_permissions_validation_and_stale_edits(prescribing):
    (c,db,branches,users,admin,login),h,*_=prescribing
    reception=login(users["RECEPTIONIST"].username)
    assert c.get(M,headers=reception).status_code==403
    assert c.post(M,headers=admin,json={"brand":"Draft","active":True}).status_code==409
    assert c.post(M,headers=admin,json={"brand":"Draft","review_confirmed":True}).status_code==403
    assert c.post(M,headers=h,json={"brand":"Incomplete","review_confirmed":True}).status_code==422
    a=product(c,h)
    assert c.post(M,headers=h,json={**patch(a),"reason":None}).status_code==422  # extra fields forbidden
    duplicate={k:v for k,v in patch(a).items() if k not in {"reason","row_version"}}
    assert c.post(M,headers=h,json={**duplicate,"review_confirmed":True,"brand":" FICTIONAL   MEDICINE "}).status_code==409
    assert c.patch(M+"/"+a["medicine_id"],headers=admin,json=patch(a,strength="Changed strength")).status_code==409
    r=c.patch(M+"/"+a["medicine_id"],headers=admin,json=patch(a,active=False));assert r.status_code==200,r.text
    assert c.patch(M+"/"+a["medicine_id"],headers=admin,json=patch(a,active=False)).status_code==409
    r=c.patch(M+"/"+a["medicine_id"],headers=admin,json=patch(r.json(),strength="Changed strength",active=False));assert r.status_code==200 and r.json()["requires_review"]
    assert c.delete(M+"/"+a["medicine_id"],headers=admin).status_code==405


def test_prescriptions_save_retry_complete_history_and_private_serializers(prescribing):
    (c,db,branches,users,admin,login),h,visit,action,patient,doctor=prescribing
    a=product(c,h);b=product(c,h,brand="Fictional topical",generic="Different fictional composition",route="Topical test",form="Test cream")
    v=action(visit())[0].json()["visit"];lines=[line(a),line(b)]
    r,p=action(v,"save",prescriptions=lines,history="Private history");assert r.status_code==200,r.text
    saved=r.json();assert len(saved["prescriptions"])==2
    assert c.post(D+"/"+v["visit_id"]+"/save",headers=h,json=p).status_code==200
    assert c.post(D+"/"+v["visit_id"]+"/save",headers=h,json={**p,"prescriptions":[]}).status_code==409
    assert action(v,"save",prescriptions=[])[0].status_code==409
    r,_=action(saved["visit"],"save",history="Older client keeps medicines");assert len(r.json()["prescriptions"])==2
    r,_=action(r.json()["visit"],"complete",prescriptions=lines);assert r.status_code==200,r.text
    done=r.json();assert done["prescriptions"][0]["instructions"]==lines[0]["instructions"]
    assert action(done["visit"],"save",prescriptions=[])[0].status_code==409
    detail=c.get(D+"/"+v["visit_id"],headers=h).json();assert detail["revisions"][1]["snapshot"]["prescriptions"][0]["brand"]==a["brand"]
    second=visit();assert c.get(D+"/"+second["visit_id"],headers=h).json()["previous_visits"][0]["prescriptions"][0]["brand"]==a["brand"]
    for headers in (admin,login(users["RECEPTIONIST"].username)):
        assert c.get(D+"/"+v["visit_id"],headers=headers).status_code==403
        assert a["brand"] not in c.get("/api/v1/visits/"+v["visit_id"],headers=headers).text
        assert a["brand"] not in c.get("/api/v1/patients/"+patient["patient_id"]+"/visits",headers=headers).text


def test_catalogue_changes_do_not_rewrite_saved_prescriptions_or_silently_change_strength(prescribing):
    (c,db,branches,users,admin,login),h,visit,action,patient,doctor=prescribing
    a=product(c,h);v=action(visit())[0].json()["visit"];old=line(a)
    changed=c.patch(M+"/"+a["medicine_id"],headers=h,json=patch(a,strength="New exact strength",review_confirmed=True)).json()
    assert action(v,"save",prescriptions=[old])[0].status_code==409
    new=line(changed);r,_=action(v,"save",prescriptions=[new]);assert r.status_code==200,r.text
    saved=r.json()["visit"]
    changed=c.patch(M+"/"+a["medicine_id"],headers=admin,json=patch(changed,active=False)).json()
    r,_=action(saved,"save",prescriptions=[{**new,"dose":"Edited manual amount"}]);assert r.status_code==200,r.text
    assert r.json()["prescriptions"][0]["strength"]=="New exact strength"
    assert action(r.json()["visit"],"save",prescriptions=[line(changed)])[0].status_code==409
    r,_=action(r.json()["visit"],"save",prescriptions=[]);assert r.status_code==200,r.text
    assert r.json()["prescriptions"]==[]
    row=db.get(PrescriptionLine,uuid.UUID(new["line_id"]));assert not row.active


def test_validation_foreign_products_and_atomic_rollback(prescribing,monkeypatch):
    (c,db,branches,users,admin,login),h,visit,action,patient,doctor=prescribing
    a=product(c,h);v=action(visit())[0].json()["visit"];l=line(a)
    for fields in ({"dose":" "},{"frequency":""},{"duration":""},{"medicine_version":0},{"route":" "},{"unknown":True}):
        assert action(v,"save",prescriptions=[{**l,**fields}])[0].status_code==422
    assert action(v,"save",prescriptions=[l,l])[0].status_code==422
    assert action(v,"save",prescriptions=[line(a) for _ in range(31)])[0].status_code==422
    master=db.get(Medicine,uuid.UUID(a["medicine_id"]));master.organization_id=branches[2].organization_id;db.commit()
    assert action(v,"save",prescriptions=[l])[0].status_code==422
    master.organization_id=users["DOCTOR"].organization_id;db.commit()
    from app.api.routes import doctor_consultations as service
    payload=service.NoteAction(request_id=uuid.uuid4(),row_version=v["row_version"],prescriptions=[l])
    def broken(*args,**kwargs):raise RuntimeError("Injected audit failure")
    with monkeypatch.context() as m:
        m.setattr("app.services.audit.log_audit",broken)
        with pytest.raises(RuntimeError):service.mutate(uuid.UUID(v["visit_id"]),"save",payload,db,users["DOCTOR"])
    db.expire_all();assert c.get(D+"/"+v["visit_id"],headers=h).json()["prescriptions"]==[]
    r,_=action(v,"save",prescriptions=[l]);assert r.status_code==200,r.text
    other=action(visit())[0].json()["visit"]
    assert action(other,"save",prescriptions=[l])[0].status_code==422


def test_concurrent_prescription_saves_on_postgresql(prescribing):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy.orm import Session
    from fastapi import HTTPException
    from app.api.routes import doctor_consultations as service
    from app.models.core import User
    (c,db,branches,users,admin,login),h,visit,action,patient,doctor=prescribing
    if db.bind.dialect.name!="postgresql":pytest.skip("Real PostgreSQL locking required")
    a=product(c,h);v=action(visit())[0].json()["visit"];actor_id=users["DOCTOR"].user_id;engine=db.bind;db.commit();barrier=Barrier(2)
    def save(dose):
        with Session(engine) as session:
            actor=session.get(User,actor_id);barrier.wait();payload=service.NoteAction(request_id=uuid.uuid4(),row_version=v["row_version"],prescriptions=[line(a,dose=dose)])
            try:service.mutate(uuid.UUID(v["visit_id"]),"save",payload,session,actor);return 200
            except HTTPException as exc:return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(save,["First fictional dose","Second fictional dose"]))
    assert sorted(results)==[200,409]
    db.expire_all();rows=db.scalars(select(PrescriptionLine).where(PrescriptionLine.visit_id==uuid.UUID(v["visit_id"]),PrescriptionLine.active.is_(True))).all();assert len(rows)==1
