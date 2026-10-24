"""Catalogue isolation, history preservation, concurrent writes and clinical privacy."""
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
from app.models.diagnosis import Diagnosis, VisitDiagnosis
from app.models.clinical import ConsultationNoteRevision, ConsultationNote, Visit
from app.services.clinical_team import configure_permissions
from app.services.diagnoses import seed_catalogue

P = "/api/v1/diagnoses"
D = "/api/v1/doctor-consultations"


@pytest.fixture
def diagnoses(clinical):
    data,h,visit,action,patient,doctor = clinical
    _,db,_,users,_,_ = data
    configure_permissions(db)
    seed_catalogue(db, users["DOCTOR"].organization_id)
    db.commit()
    return clinical


def create(c, h, name="Fictional test diagnosis", **extra):
    r = c.post(P, headers=h, json={"name":name,"category":"Test",**extra})
    assert r.status_code == 201, r.text
    return r.json()


def selected(*rows):
    return [{"diagnosis_id":d["diagnosis_id"],"is_primary":i==0} for i,d in enumerate(rows)]


def test_catalogue_source_is_exact_and_bootstrap_preserves_changes(diagnoses):
    (c,db,branches,users,admin,login),h,*_ = diagnoses
    source=json.loads((Path(__file__).parents[1]/"app/data/diagnoses_v11.json").read_text())
    rows=c.get(P+"?include_inactive=true&limit=250",headers=h).json()
    assert len(source["entries"])==len(rows)==184
    assert sum(d["requires_review"] for d in rows)==3
    assert all(not d["active"] for d in rows if d["requires_review"])
    assert {d["name"] for d in rows}=={d["name"] for d in source["entries"]}
    assert all(set(d)=={"name","category","history_module","source_row","requires_review"} for d in source["entries"])
    first=rows[0]
    r=c.patch(P+"/"+first["diagnosis_id"],headers=admin,json={"name":"Renamed source entry","category":"Test","active":False,"row_version":first["row_version"],"reason":"Clinical catalogue correction"})
    assert r.status_code==200,r.text
    seed_catalogue(db,users["DOCTOR"].organization_id);db.commit()
    rows=c.get(P+"?include_inactive=true&limit=250",headers=h).json()
    assert len(rows)==184 and next(d for d in rows if d["diagnosis_id"]==first["diagnosis_id"])["name"]=="Renamed source entry"
    assert c.get(P+"?q=Renamed",headers=h).json()==[]


def test_catalogue_permissions_duplicates_stale_and_tenant_scope(diagnoses):
    (c,db,branches,users,admin,login),h,*_ = diagnoses
    reception=login(users["RECEPTIONIST"].username)
    assert c.get(P,headers=reception).status_code==403
    assert c.post(P,headers=reception,json={"name":"Blocked","category":"Test"}).status_code==403
    row=create(c,h)
    assert c.post(P,headers=h,json={"name":"  FICTIONAL   TEST DIAGNOSIS ","category":"Test"}).status_code==409
    assert c.post(P,headers=h,json={"name":" ","category":"Test"}).status_code==422
    assert c.post(P,headers=h,json={"name":"Awaiting","category":"Test","requires_review":True}).status_code==422
    body={"name":"Edited fictional diagnosis","category":"Test","active":False,"row_version":row["row_version"],"reason":"Duplicate correction"}
    assert c.patch(P+"/"+row["diagnosis_id"],headers=admin,json=body).status_code==200
    assert c.patch(P+"/"+row["diagnosis_id"],headers=admin,json=body).status_code==409
    other=Diagnosis(organization_id=branches[2].organization_id,name="Other clinic only",normalized_name="other clinic only",category="Test");db.add(other);db.commit()
    assert c.get(P+"?q=Other%20clinic",headers=h).json()==[]
    assert c.patch(P+"/"+str(other.diagnosis_id),headers=admin,json={**body,"row_version":1}).status_code==404
    assert c.delete(P+"/"+row["diagnosis_id"],headers=admin).status_code==405


def test_visit_diagnoses_retry_history_catalogue_edit_and_privacy(diagnoses):
    (c,db,branches,users,admin,login),h,visit,action,patient,doctor = diagnoses
    a=create(c,h,"Fictional diagnosis A");b=create(c,h,"Fictional diagnosis B")
    v=visit();v=action(v)[0].json()["visit"]
    r,p=action(v,"save",diagnoses=selected(a,b),assessment="Doctor text remains separate")
    assert r.status_code==200,r.text
    saved=r.json();assert len(saved["diagnoses"])==2
    assert c.post(D+"/"+v["visit_id"]+"/save",headers=h,json=p).status_code==200
    assert c.post(D+"/"+v["visit_id"]+"/save",headers=h,json={**p,"diagnoses":selected(b)}).status_code==409
    assert action(v,"save",diagnoses=selected(b))[0].status_code==409
    r=c.patch(P+"/"+a["diagnosis_id"],headers=admin,json={"name":"Renamed later A","category":"Changed","active":False,"row_version":a["row_version"],"reason":"Master renamed after clinical recording"});assert r.status_code==200
    # Existing inactive selections can remain; older clients also preserve them.
    r,_=action(saved["visit"],"save",assessment="Legacy client");assert r.status_code==200,r.text
    assert r.json()["diagnoses"][0]["name"]==a["name"]
    r,_=action(r.json()["visit"],"complete",diagnoses=selected(a,b));assert r.status_code==200,r.text
    done=r.json();assert done["diagnoses"][0]["name"]==a["name"]
    assert action(done["visit"],"save",diagnoses=[])[0].status_code==409
    detail=c.get(D+"/"+v["visit_id"],headers=h).json()
    assert detail["revisions"][1]["snapshot"]["diagnoses"][0]["name"]==a["name"]
    second=visit();history=c.get(D+"/"+second["visit_id"],headers=h).json()["previous_visits"]
    assert history[0]["diagnoses"][0]["name"]==a["name"]
    new=action(second)[0].json()["visit"]
    assert action(new,"save",diagnoses=selected(a))[0].status_code==409
    for headers in (admin,login(users["RECEPTIONIST"].username)):
        assert c.get(D+"/"+v["visit_id"],headers=headers).status_code==403
        ordinary=c.get("/api/v1/visits/"+v["visit_id"],headers=headers)
        assert a["name"] not in ordinary.text and 'diagnoses' not in ordinary.json()
        assert a["name"] not in c.get("/api/v1/patients/"+patient["patient_id"]+"/visits",headers=headers).text


def test_selection_validation_removal_and_atomic_rollback(diagnoses,monkeypatch):
    (c,db,branches,users,admin,login),h,visit,action,patient,doctor = diagnoses
    a=create(c,h);v=action(visit())[0].json()["visit"]
    for entries in ([{"diagnosis_id":a["diagnosis_id"],"is_primary":False}],selected(a,a),selected({"diagnosis_id":str(uuid.uuid4())})):
        assert action(v,"save",diagnoses=entries)[0].status_code==422
    other=Diagnosis(organization_id=branches[2].organization_id,name="Foreign",normalized_name="foreign",category="Test");db.add(other);db.commit()
    assert action(v,"save",diagnoses=selected({"diagnosis_id":str(other.diagnosis_id)}))[0].status_code==422
    r,_=action(v,"save",diagnoses=selected(a));assert r.status_code==200,r.text
    saved=r.json()["visit"]
    from app.api.routes import doctor_consultations as service
    payload=service.NoteAction(request_id=uuid.uuid4(),row_version=saved["row_version"],diagnoses=[])
    def broken(*args,**kwargs):raise RuntimeError("Injected failure")
    with monkeypatch.context() as m:
        m.setattr("app.services.audit.log_audit",broken)
        with pytest.raises(RuntimeError):service.mutate(uuid.UUID(v["visit_id"]),"save",payload,db,users["DOCTOR"])
    db.expire_all()
    assert c.get(D+"/"+v["visit_id"],headers=h).json()["diagnoses"][0]["name"]==a["name"]
    r,_=action(saved,"save",diagnoses=[]);assert r.status_code==200,r.text
    assert r.json()["diagnoses"]==[]
    row=db.scalar(select(VisitDiagnosis).where(VisitDiagnosis.visit_id==uuid.UUID(v["visit_id"])))
    assert not row.active  # Removal archives the relationship; it does not delete it.


def test_concurrent_diagnosis_saves_on_postgresql(diagnoses):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy.orm import Session
    from fastapi import HTTPException
    from app.api.routes import doctor_consultations as service
    from app.models.core import User
    (c,db,branches,users,admin,login),h,visit,action,patient,doctor=diagnoses
    if db.bind.dialect.name!="postgresql":pytest.skip("Real PostgreSQL locking required")
    a=create(c,h,"Concurrent fictional A");b=create(c,h,"Concurrent fictional B")
    v=action(visit())[0].json()["visit"];actor_id=users["DOCTOR"].user_id;engine=db.bind;db.commit();barrier=Barrier(2)
    def save(row):
        with Session(engine) as session:
            actor=session.get(User,actor_id);barrier.wait()
            payload=service.NoteAction(request_id=uuid.uuid4(),row_version=v["row_version"],diagnoses=selected(row))
            try:service.mutate(uuid.UUID(v["visit_id"]),"save",payload,session,actor);return 200
            except HTTPException as exc:return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(save,[a,b]))
    assert sorted(results)==[200,409]
    db.expire_all();rows=db.scalars(select(VisitDiagnosis).where(VisitDiagnosis.visit_id==uuid.UUID(v["visit_id"]),VisitDiagnosis.active.is_(True))).all()
    assert len(rows)==1 and rows[0].is_primary
