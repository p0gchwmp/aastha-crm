"""HTTP encounter verification, branch boundaries and real PostgreSQL races."""
import uuid
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from test_staff_access import clinic
from test_lead_register import leads
from test_appointments import scheduling
from test_patient_registration import registration
from app.models import Base
from app.models.core import Permission, RolePermission, UserRole, User
from app.models.clinical import Visit, VisitType, VisitStatus, VisitComplaint, ChiefComplaint
from app.models.patient import Patient
from app.models.scheduling import Appointment, AppointmentStatus
from app.models.integration import AuditEvent
from app.services import visits as service
from app.schemas.clinical import VisitCreate

@pytest.fixture
def encounters(registration, monkeypatch):
    data, patient_payload, new_lead, appointment, series = registration
    c,db,branches,users,admin,login = data
    if db.bind.dialect.name=='sqlite':Base.metadata.create_all(db.bind,tables=[m.__table__ for m in (VisitType,VisitStatus,ChiefComplaint,VisitComplaint)])
    for code in ('CONSULTATION','REPORT_CHECK'):
        if not db.scalar(select(VisitType).where(VisitType.code==code)):db.add(VisitType(code=code,name=code))
    for code in ('WAITING','COMPLETED'):
        if not db.scalar(select(VisitStatus).where(VisitStatus.code==code)):db.add(VisitStatus(code=code,name=code))
    p=db.scalar(select(Permission).where(Permission.code=='VISIT_CREATE'))
    if not p:p=Permission(code='VISIT_CREATE',name='Create Visit');db.add(p);db.flush()
    for u in (users['ADMIN'],users['RECEPTIONIST']):
        role=db.scalar(select(UserRole.role_id).where(UserRole.user_id==u.user_id))
        if not db.scalar(select(RolePermission).where(RolePermission.role_id==role,RolePermission.permission_id==p.permission_id)):db.add(RolePermission(role_id=role,permission_id=p.permission_id))
    complaint=ChiefComplaint(name='Fictional complaint',approval_status='PENDING');db.add(complaint);db.commit()
    patient=c.post('/api/v1/patients',headers=admin,json=patient_payload()).json()
    kind=db.scalar(select(VisitType).where(VisitType.code=='CONSULTATION'))
    monkeypatch.setattr(service,'now',lambda:datetime(2030,1,7,18,45,tzinfo=timezone.utc))
    def payload():return dict(patient_id=patient['patient_id'],patient_row_version=patient['row_version'],creation_request_id=str(uuid.uuid4()),branch_id=str(branches[0].branch_id),visit_type_id=str(kind.visit_type_id),chief_complaint_ids=[str(complaint.chief_complaint_id)],identity_confirmed=True)
    return data,payload,patient,complaint,appointment,series


def test_visit_identity_retry_history_and_no_uhid_change(encounters):
    (c,db,branches,users,admin,login),payload,patient,complaint,appointment,series=encounters
    p=payload();before=series.current_number
    for extra in ({'identity_confirmed':False},{'patient_row_version':999}):assert c.post('/api/v1/visits',headers=admin,json={**p,**extra}).status_code==409
    for extra in ({'visit_status_id':str(uuid.uuid4())},{'checkin_at':'2001-01-01T00:00:00Z'},{'creation_request_id':None}):assert c.post('/api/v1/visits',headers=admin,json={**p,**extra}).status_code==422
    p['chief_complaint_ids']*=2
    r=c.post('/api/v1/visits',headers=admin,json=p);assert r.status_code==200,r.text
    vid=r.json()['visit_id'];assert c.post('/api/v1/visits',headers=admin,json=p).json()['visit_id']==vid
    assert c.post('/api/v1/visits',headers=admin,json={**p,'doctor_id':str(uuid.uuid4())}).status_code==409
    detail=c.get('/api/v1/visits/'+vid,headers=admin).json()
    assert detail['status_code']=='WAITING' and detail['uhid']==patient['uhid'] and len(detail['complaints'])==1 and detail['identity_confirmed_at']
    assert vid in {v['visit_id'] for v in c.get('/api/v1/visits?on_date=2030-01-08',headers=admin).json()}
    assert vid not in {v['visit_id'] for v in c.get('/api/v1/visits?on_date=2030-01-07',headers=admin).json()}
    assert c.get('/api/v1/patients/'+patient['patient_id']+'/visits',headers=admin).json()[0]['visit_id']==vid
    assert db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_id==uuid.UUID(vid),AuditEvent.action=='VISIT_CREATED'))==1
    db.refresh(series);assert series.current_number==before
    r=c.post('/api/v1/visits',headers=admin,json=payload());assert r.status_code==200 and r.json()['visit_id']!=vid
    report=db.scalar(select(VisitType).where(VisitType.code=='REPORT_CHECK'))
    assert c.post('/api/v1/visits',headers=admin,json={**payload(),'visit_type_id':str(report.visit_type_id),'chief_complaint_ids':[]}).status_code==200


def test_visit_permissions_masters_and_patient_history(encounters):
    (c,db,branches,users,admin,login),payload,patient,complaint,appointment,series=encounters
    reception=login(users['RECEPTIONIST'].username);p=payload()
    assert c.post('/api/v1/visits',json=p).status_code==401
    assert c.post('/api/v1/visits',headers=login(users['DOCTOR'].username),json=p).status_code==403
    assert c.post('/api/v1/visits',headers=reception,json={**p,'branch_id':str(branches[1].branch_id)}).status_code==403
    assert c.post('/api/v1/visits',headers=admin,json={**p,'branch_id':str(branches[2].branch_id)}).status_code==404
    hidden=c.post('/api/v1/visits',headers=admin,json={**p,'branch_id':str(branches[1].branch_id)}).json()['visit_id']
    assert c.get('/api/v1/visits/'+hidden,headers=reception).status_code==403
    for path in ('/patients/'+patient['patient_id']+'/visits','/visits'):
        assert hidden not in {x['visit_id'] for x in c.get('/api/v1'+path,headers=reception).json()}
    complaint.approval_status='REJECTED';db.commit()
    assert c.post('/api/v1/visits',headers=admin,json=payload()).status_code==409
    for extra in ({'doctor_id':str(uuid.uuid4())},{'visit_type_id':str(uuid.uuid4())}):assert c.post('/api/v1/visits',headers=admin,json={**payload(),**extra}).status_code==400
    other=Patient(organization_id=branches[2].organization_id,registration_branch_id=branches[2].branch_id,full_name='Other organization',uhid=uuid.uuid4().hex);db.add(other);db.commit()
    assert c.post('/api/v1/visits',headers=admin,json={**payload(),'patient_id':str(other.patient_id),'patient_row_version':other.row_version}).status_code==404


def appointment_payload(encounters,monkeypatch):
    (c,db,branches,users,admin,login),payload,patient,complaint,appointment,series=encounters
    monkeypatch.setattr(service,'now',lambda:datetime(2030,1,7,6,tzinfo=timezone.utc))
    # Lead booking followed by verified identity linkage, as registration performs.
    r=c.post('/api/v1/appointments',headers=admin,json=appointment());assert r.status_code==200,r.text
    a=r.json();row=db.get(Appointment,uuid.UUID(a['appointment_id']));row.patient_id=uuid.UUID(patient['patient_id']);db.commit()
    return {**payload(),'appointment_id':a['appointment_id'],'appointment_row_version':a['row_version'],'doctor_id':a['doctor_id']},row


def test_appointment_identity_date_branch_version_and_duplicate(encounters,monkeypatch):
    (c,db,branches,users,admin,login),payload,patient,complaint,appointment,series=encounters
    p,row=appointment_payload(encounters,monkeypatch)
    for extra in ({'branch_id':str(branches[1].branch_id)},{'appointment_row_version':999},{'doctor_id':None}):assert c.post('/api/v1/visits',headers=admin,json={**p,**extra}).status_code==409
    row.patient_id=None;db.commit();assert c.post('/api/v1/visits',headers=admin,json=p).status_code==409
    row.patient_id=uuid.UUID(patient['patient_id']);row.appointment_status_id=db.scalar(select(AppointmentStatus.appointment_status_id).where(AppointmentStatus.code=='CANCELLED'));db.commit()
    assert c.post('/api/v1/visits',headers=admin,json=p).status_code==409
    row.appointment_status_id=db.scalar(select(AppointmentStatus.appointment_status_id).where(AppointmentStatus.code=='COMPLETED'));db.commit()
    monkeypatch.setattr(service,'now',lambda:datetime(2030,1,8,6,tzinfo=timezone.utc));assert c.post('/api/v1/visits',headers=admin,json=p).status_code==409
    monkeypatch.setattr(service,'now',lambda:datetime(2030,1,7,6,tzinfo=timezone.utc))
    r=c.post('/api/v1/visits',headers=admin,json=p);assert r.status_code==200,r.text
    assert c.post('/api/v1/visits',headers=admin,json=p).json()['visit_id']==r.json()['visit_id']
    assert c.post('/api/v1/visits',headers=admin,json={**p,'creation_request_id':str(uuid.uuid4())}).status_code==409
    assert c.get('/api/v1/appointments/'+p['appointment_id'],headers=admin).json()['status_code']=='COMPLETED'


def test_visit_failure_rolls_back(encounters,monkeypatch):
    (c,db,branches,users,admin,login),payload,patient,complaint,appointment,series=encounters
    p=payload();original=service.log_audit
    def fail(*a,**kw):raise RuntimeError('Injected Visit failure')
    monkeypatch.setattr(service,'log_audit',fail)
    with pytest.raises(RuntimeError,match='Injected Visit failure'):c.post('/api/v1/visits',headers=admin,json=p)
    assert not db.scalar(select(Visit).where(Visit.creation_request_id==uuid.UUID(p['creation_request_id'])))
    monkeypatch.setattr(service,'log_audit',original);assert c.post('/api/v1/visits',headers=admin,json=p).status_code==200


def test_postgres_visit_concurrent_retry_and_appointment(encounters,monkeypatch):
    (c,db,branches,users,admin,login),payload,patient,complaint,appointment,series=encounters
    if db.bind.dialect.name!='postgresql':pytest.skip('Real PostgreSQL locks required')
    def race(requests,actors):
        barrier=Barrier(2)
        def run(i):
            with Session(db.bind,expire_on_commit=False) as local:
                actor=local.get(User,actors[i]);barrier.wait(timeout=10)
                try:return str(service.create_visit(local,user=actor,payload=VisitCreate(**requests[i])).visit_id)
                except HTTPException as e:return e.status_code
        with ThreadPoolExecutor(2) as pool:return list(pool.map(run,range(2)))
    p=payload();uid=users['ADMIN'].user_id;ids=race([p,p],[uid,uid]);assert isinstance(ids[0],str) and ids[0]==ids[1]
    p,row=appointment_payload(encounters,monkeypatch)
    ids=race([p,{**p,'creation_request_id':str(uuid.uuid4())}],[uid,users['RECEPTIONIST'].user_id]);assert len([x for x in ids if isinstance(x,str)])==1 and 409 in ids
