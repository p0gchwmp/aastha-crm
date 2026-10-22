"""Doctor clinical workflow, retry protection and Reception privacy."""
import uuid
import pytest
from sqlalchemy import select
from test_staff_access import clinic
from test_lead_register import leads
from test_appointments import scheduling
from test_patient_registration import registration
from test_visit_management import encounters
from app.models import Base
from app.models.core import Doctor, Permission, RolePermission, UserRole
from app.models.clinical import Visit, VisitStatus, VisitType, ConsultationNote
from app.api.routes import doctor_consultations as service
P='/api/v1/doctor-consultations'

@pytest.fixture
def clinical(encounters):
    data,payload,patient,*_=encounters
    c,db,branches,users,admin,login=data
    if db.bind.dialect.name=='sqlite':Base.metadata.create_all(db.bind)
    doctor=db.scalar(select(Doctor).where(Doctor.organization_id==users['DOCTOR'].organization_id))
    doctor.user_id=users['DOCTOR'].user_id
    for code in ('IN_PROGRESS','CANCELLED'):
        if not db.scalar(select(VisitStatus).where(VisitStatus.code==code)):db.add(VisitStatus(code=code,name=code))
    perm=db.scalar(select(Permission).where(Permission.code=='CONSULTATION_CLINICAL'))
    if not perm:perm=Permission(code='CONSULTATION_CLINICAL',name='Clinical consultation');db.add(perm);db.flush()
    role=db.scalar(select(UserRole.role_id).where(UserRole.user_id==users['DOCTOR'].user_id))
    if not db.scalar(select(RolePermission).where(RolePermission.role_id==role,RolePermission.permission_id==perm.permission_id)):db.add(RolePermission(role_id=role,permission_id=perm.permission_id))
    db.commit();headers=login(users['DOCTOR'].username)
    def visit():
        r=c.post('/api/v1/visits',headers=admin,json={**payload(),'doctor_id':str(doctor.doctor_id)});assert r.status_code==200,r.text
        return r.json()
    def action(v,which='start',**extra):
        p={'request_id':str(uuid.uuid4()),'row_version':v['row_version'],'patient_version':patient['row_version'],'identity_confirmed':True,**extra}
        return c.post(P+'/'+v['visit_id']+'/'+which,headers=headers,json=p),p
    return data,headers,visit,action,patient,doctor


def test_full_workflow_retries_and_privacy(clinical):
    (c,db,branches,users,admin,login),h,visit,action,patient,doctor=clinical
    v=visit();assert v['visit_id'] in {x['visit_id'] for x in c.get(P+'?on_date=2030-01-08',headers=h).json()}
    assert action(v,identity_confirmed=False)[0].status_code==409
    assert action(v,patient_version=999)[0].status_code==409
    r,p=action(v);assert r.status_code==200,r.text
    started=r.json();assert started['visit']['status_code']=='IN_PROGRESS'
    assert c.post(P+'/'+v['visit_id']+'/start',headers=h,json=p).json()['visit']['row_version']==started['visit']['row_version']
    assert c.post(P+'/'+v['visit_id']+'/start',headers=h,json={**p,'patient_version':999}).status_code==409
    assert action(v,'save',history='stale')[0].status_code==409
    r,p=action(started['visit'],'save',history='Private clinical history',assessment='Fictional assessment',plan='Fictional plan',followup_date='2030-01-15');assert r.status_code==200,r.text
    saved=r.json();assert saved['note']['history']=='Private clinical history'
    assert c.post(P+'/'+v['visit_id']+'/save',headers=h,json=p).status_code==200
    r,_=action(saved['visit'],'complete',history='Final history',plan='Final plan',followup_advice='Return if required',followup_date='2030-01-15');assert r.status_code==200,r.text
    done=r.json();assert done['visit']['status_code']=='COMPLETED' and done['visit']['completed_at']
    assert action(done['visit'],'save')[0].status_code==409
    d=c.get(P+'/'+v['visit_id'],headers=h).json();assert len(d['revisions'])==3 and d['revisions'][1]['snapshot']['history']=='Private clinical history'
    second=visit();assert c.get(P+'/'+second['visit_id'],headers=h).json()['previous_visits'][0]['note']['history']=='Final history'
    reception=login(users['RECEPTIONIST'].username)
    assert c.get(P+'/'+v['visit_id'],headers=reception).status_code==403
    assert c.get(P+'?on_date=2030-01-08',headers=reception).status_code==403
    ordinary=c.get('/api/v1/visits/'+v['visit_id'],headers=reception);assert ordinary.json()['status_code']=='COMPLETED' and 'Final history' not in ordinary.text
    assert 'Final history' not in c.get('/api/v1/patients/'+patient['patient_id']+'/visits',headers=reception).text


def test_wrong_doctor_inactive_procedure_cancelled(clinical):
    (c,db,branches,users,admin,login),h,visit,action,patient,doctor=clinical
    v=visit();row=db.get(Visit,uuid.UUID(v['visit_id']));row.doctor_id=None;db.commit()
    assert c.get(P+'/'+v['visit_id'],headers=h).status_code==403
    row.doctor_id=doctor.doctor_id;doctor.active=False;db.commit();assert action(v)[0].status_code==403
    doctor.active=True
    kind=db.scalar(select(VisitType).where(VisitType.code=='PROCEDURE'))
    if not kind:kind=VisitType(code='PROCEDURE',name='Procedure');db.add(kind);db.flush()
    row.visit_type_id=kind.visit_type_id;db.commit();assert action(v)[0].status_code==409
    assert c.get(P+'?on_date=2030-01-08',headers=h).json()==[]
    row.visit_type_id=db.scalar(select(VisitType.visit_type_id).where(VisitType.code=='CONSULTATION'))
    row.visit_status_id=db.scalar(select(VisitStatus.visit_status_id).where(VisitStatus.code=='CANCELLED'));db.commit();assert action(v)[0].status_code==409


def test_atomic_rollback(clinical,monkeypatch):
    (c,db,branches,users,admin,login),h,visit,action,patient,doctor=clinical
    v=visit();payload=service.NoteAction(request_id=uuid.uuid4(),row_version=v['row_version'],identity_confirmed=True,patient_version=patient['row_version'])
    def broken(*args,**kwargs):raise RuntimeError('Injected audit failure')
    monkeypatch.setattr('app.services.audit.log_audit',broken)
    with pytest.raises(RuntimeError):service.mutate(uuid.UUID(v['visit_id']),'start',payload,db,users['DOCTOR'])
    db.expire_all();row=db.get(Visit,uuid.UUID(v['visit_id']))
    assert db.get(VisitStatus,row.visit_status_id).code=='WAITING' and row.started_at is None
    assert db.scalar(select(ConsultationNote).where(ConsultationNote.visit_id==row.visit_id)) is None


def test_branch_scope_patient_change_and_duplicate_profiles(clinical):
    (c,db,branches,users,admin,login),h,visit,action,patient,doctor=clinical
    from app.models.patient import Patient
    v=visit();p=db.get(Patient,uuid.UUID(patient['patient_id']));p.row_version+=1;db.commit()
    assert action(v)[0].status_code==409
    role=db.scalar(select(UserRole).where(UserRole.user_id==users['DOCTOR'].user_id));role.branch_id=branches[1].branch_id;db.commit()
    assert c.get(P+'/'+v['visit_id'],headers=h).status_code==403
    assert c.get(P+'?on_date=2030-01-08',headers=h).json()==[]
    role.branch_id=None
    duplicate=Doctor(organization_id=doctor.organization_id,user_id=doctor.user_id,doctor_code=uuid.uuid4().hex[:12],doctor_name='Ambiguous Doctor',active=True);db.add(duplicate);db.commit()
    assert c.get(P+'/'+v['visit_id'],headers=h).status_code==403
    duplicate.active=False;p.organization_id=branches[2].organization_id;db.commit()
    assert c.get(P+'/'+v['visit_id'],headers=h).status_code==404


def test_concurrent_writers_reject_stale_second_save(clinical):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy.orm import Session
    from fastapi import HTTPException
    from app.models.core import User
    from app.models.clinical import ConsultationNoteRevision
    (c,db,branches,users,admin,login),h,visit,action,patient,doctor=clinical
    if db.bind.dialect.name!='postgresql':pytest.skip('Real PostgreSQL row locks required')
    v=visit();started=action(v)[0].json()['visit'];actor_id=users['DOCTOR'].user_id;engine=db.bind;db.commit();barrier=Barrier(2)
    def save(text):
        with Session(engine) as session:
            actor=session.get(User,actor_id);barrier.wait()
            payload=service.NoteAction(request_id=uuid.uuid4(),row_version=started['row_version'],history=text)
            try:service.mutate(uuid.UUID(v['visit_id']),'save',payload,session,actor);return 200
            except HTTPException as exc:return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(save,['First Doctor screen','Second Doctor screen']))
    assert sorted(results)==[200,409]
    db.expire_all();note=db.scalar(select(ConsultationNote).where(ConsultationNote.visit_id==uuid.UUID(v['visit_id'])))
    revisions=db.scalars(select(ConsultationNoteRevision).where(ConsultationNoteRevision.note_id==note.note_id)).all();assert len(revisions)==2 and note.row_version==2
