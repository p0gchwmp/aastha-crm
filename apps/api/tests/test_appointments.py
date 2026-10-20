"""HTTP scheduling workflow plus real concurrent PostgreSQL slot writers."""
import os
import uuid
from datetime import date,datetime,time,timedelta,timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import select,func,text
from sqlalchemy.orm import Session
from fastapi import HTTPException
from test_staff_access import clinic
from test_lead_register import leads
from app.models import Base
from app.models.core import Doctor,Permission,RolePermission,UserRole,User
from app.models.crm import Lead,LeadStatus
from app.models.patient import Patient
from app.models.scheduling import Appointment,AppointmentStatus,DoctorSchedule,ScheduleException
from app.models.integration import AuditEvent
from app.schemas.scheduling import AppointmentCreate
from app.services import appointments as engine
DAY=date(2030,1,7)

@pytest.fixture
def scheduling(leads,monkeypatch):
    clinic_data,create_lead,statuses,lost=leads
    c,db,branches,users,admin,login=clinic_data
    if db.bind.dialect.name=="sqlite":
        Base.metadata.create_all(db.bind,tables=[m.__table__ for m in (Doctor,AppointmentStatus,Appointment,DoctorSchedule,ScheduleException)])
    for code in ("APPOINTMENT_CREATE","APPOINTMENT_EDIT","APPOINTMENT_SCHEDULE_MANAGE"):
        p=db.scalar(select(Permission).where(Permission.code==code))
        if not p: p=Permission(code=code,name=code);db.add(p);db.flush()
        targets=[users["ADMIN"]] if code=="APPOINTMENT_SCHEDULE_MANAGE" else [users["ADMIN"],users["RECEPTIONIST"]]
        for u in targets:
            role=db.scalar(select(UserRole.role_id).where(UserRole.user_id==u.user_id))
            if not db.scalar(select(RolePermission).where(RolePermission.role_id==role,RolePermission.permission_id==p.permission_id)):
                db.add(RolePermission(role_id=role,permission_id=p.permission_id))
    for code in ("SCHEDULED","CONFIRMED","CHECKED_IN","RESCHEDULED","NO_SHOW","CANCELLED","COMPLETED","WAITLISTED"):
        if not db.scalar(select(AppointmentStatus).where(AppointmentStatus.code==code)):
            db.add(AppointmentStatus(code=code,name=code.replace('_',' ').title()))
    if not db.scalar(select(LeadStatus).where(LeadStatus.code=="APPOINTMENT_BOOKED")):db.add(LeadStatus(code="APPOINTMENT_BOOKED",name="Appointment Booked"))
    doc=Doctor(organization_id=users["ADMIN"].organization_id,doctor_code=uuid.uuid4().hex[:15],doctor_name="Fictional Doctor")
    db.add(doc);db.flush()
    for b in branches[:2]:db.add(DoctorSchedule(doctor_id=doc.doctor_id,branch_id=b.branch_id,day_of_week=0,start_time=time(11),end_time=time(12),slot_duration_minutes=15,effective_from=DAY))
    db.commit();monkeypatch.setattr(engine,"now",lambda:datetime(2030,1,7,4,tzinfo=timezone.utc))
    def slots(branch=0,day=DAY):
        r=c.get('/api/v1/appointments/availability',headers=admin,params={"branch_id":str(branches[branch].branch_id),"doctor_id":str(doc.doctor_id),"on_date":day.isoformat()});assert r.status_code==200,r.text
        return r.json()['slots']
    def payload(lead_id=None,branch=0,start="11:00",day=DAY,**extra):
        lead_id=lead_id or create_lead().json()['lead_id']
        begin=datetime.fromisoformat(f'{day}T{start}:00+05:30')
        return {"organization_id":str(users["ADMIN"].organization_id),"branch_id":str(branches[branch].branch_id),"doctor_id":str(doc.doctor_id),"lead_id":lead_id,"patient_id":None,"scheduled_start":begin.isoformat(),"scheduled_end":(begin+timedelta(minutes=15)).isoformat(),"appointment_status_id":str(engine.status(db,"SCHEDULED").appointment_status_id),"booking_request_id":str(uuid.uuid4()),**extra}
    yield clinic_data,doc,payload,slots,create_lead

def test_booking_retry_reschedule_cancel_and_no_uhid(scheduling):
    (c,db,branches,users,admin,login),doc,payload,slots,create=scheduling
    count=db.scalar(select(func.count()).select_from(Patient))
    p=payload();r=c.post('/api/v1/appointments',headers=admin,json=p);assert r.status_code==200,r.text
    row=r.json();aid=row['appointment_id'];url='/api/v1/appointments/'+aid
    assert c.post('/api/v1/appointments',headers=admin,json=p).json()['appointment_id']==aid
    assert db.scalar(select(func.count()).select_from(Appointment).where(Appointment.organization_id==users["ADMIN"].organization_id))==1
    assert db.scalar(select(func.count()).select_from(Patient))==count
    assert c.get('/api/v1/leads/'+p['lead_id'],headers=admin).json()['status_code']=='APPOINTMENT_BOOKED'
    assert len(slots())==3 and len(slots(branch=1))==3
    assert c.post('/api/v1/appointments',headers=admin,json=payload(branch=1)).status_code==409
    assert c.post('/api/v1/appointments',headers=admin,json={**p,'scheduled_start':f'{DAY}T11:15:00+05:30','scheduled_end':f'{DAY}T11:30:00+05:30'}).status_code==409
    assert c.post('/api/v1/appointments',headers=admin,json=payload(start='13:00')).status_code==409
    move={'branch_id':p['branch_id'],'doctor_id':p['doctor_id'],'scheduled_start':f'{DAY}T11:30:00+05:30','scheduled_end':f'{DAY}T11:45:00+05:30','row_version':row['row_version'],'reason':'Fictional requested change'}
    r=c.patch(url+'/reschedule',headers=admin,json=move);assert r.status_code==200,r.text
    row=r.json();assert row['status_code']=='RESCHEDULED'
    assert c.patch(url+'/reschedule',headers=admin,json=move).status_code==409
    detail=c.get(url,headers=admin).json();assert {x['action'] for x in detail['history']}>={'APPOINTMENT_BOOKED','APPOINTMENT_RESCHEDULED'}
    r=c.patch(url+'/status',headers=admin,params={'status_code':'CANCELLED','row_version':row['row_version'],'reason':'Fictional cancellation'});assert r.status_code==200,r.text
    assert len(slots())==4
    assert c.get('/api/v1/leads/'+p['lead_id'],headers=admin).json()['status_code']=='FOLLOW_UP_REQUIRED'
    assert c.patch(url+'/status',headers=admin,params={'status_code':'CONFIRMED','row_version':r.json()['row_version']}).status_code==409


def test_attendance_no_show_and_lead_with_multiple_bookings(scheduling,monkeypatch):
    (c,db,branches,users,admin,login),doc,payload,slots,create=scheduling
    lead=create().json()['lead_id']
    a=c.post('/api/v1/appointments',headers=admin,json=payload(lead_id=lead)).json()
    b=c.post('/api/v1/appointments',headers=admin,json=payload(lead_id=lead,start='11:15')).json()
    def change(row,code):return c.patch('/api/v1/appointments/'+row['appointment_id']+'/attendance',headers=admin,json={'status_code':code,'row_version':row['row_version'],'reason':'Fictional attendance test'})
    assert change(a,'NO_SHOW').status_code==409
    monkeypatch.setattr(engine,'now',lambda:datetime(2030,1,7,6,tzinfo=timezone.utc))
    assert change(a,'NO_SHOW').status_code==200
    assert c.get('/api/v1/leads/'+lead,headers=admin).json()['status_code']=='APPOINTMENT_BOOKED'
    assert change(b,'NO_SHOW').status_code==200
    assert c.get('/api/v1/leads/'+lead,headers=admin).json()['status_code']=='NO_SHOW'
    future=c.post('/api/v1/appointments',headers=admin,json=payload(day=DAY+timedelta(days=7))).json()
    assert change(future,'CHECKED_IN').status_code==409
    monkeypatch.setattr(engine,'now',lambda:datetime(2030,1,14,4,tzinfo=timezone.utc))
    arrived=change(future,'CHECKED_IN');assert arrived.status_code==200,arrived.text
    assert change(arrived.json(),'NO_SHOW').status_code==409
    done=change(arrived.json(),'COMPLETED');assert done.status_code==200,done.text
    assert change(done.json(),'CONFIRMED').status_code==409


def test_schedule_exceptions_permissions_and_booked_window_protection(scheduling):
    (c,db,branches,users,admin,login),doc,payload,slots,create=scheduling
    reception=login(users['RECEPTIONIST'].username)
    window={'doctor_id':str(doc.doctor_id),'branch_id':str(branches[0].branch_id),'day_of_week':1,'start_time':'11:00','end_time':'12:00','slot_duration_minutes':15,'effective_from':str(DAY),'reason':'Fictional extra weekly clinic'}
    assert c.post('/api/v1/appointments/schedules',headers=reception,json=window).status_code==403
    r=c.post('/api/v1/appointments/schedules',headers=admin,json=window);assert r.status_code==201,r.text
    schedule=r.json();assert len(slots(day=DAY+timedelta(days=1)))==4
    assert c.post('/api/v1/appointments/schedules',headers=admin,json={**window,'day_of_week':0}).status_code==409
    assert c.post('/api/v1/appointments/schedules',headers=admin,json={**window,'slot_duration_minutes':0}).status_code==422
    r=c.patch('/api/v1/appointments/schedules/'+schedule['schedule_id'],headers=admin,json={**window,'active':False,'row_version':schedule['row_version']});assert r.status_code==200,r.text
    assert c.patch('/api/v1/appointments/schedules/'+schedule['schedule_id'],headers=admin,json={**window,'active':False,'row_version':schedule['row_version']}).status_code==409
    exception={'doctor_id':str(doc.doctor_id),'branch_id':str(branches[0].branch_id),'date':str(DAY),'start_time':'11:00','end_time':'11:15','exception_type':'BREAK','reason':'Fictional doctor break'}
    r=c.post('/api/v1/appointments/schedule-exceptions',headers=admin,json=exception);assert r.status_code==201,r.text
    exc=r.json();assert len(slots())==3
    assert c.post('/api/v1/appointments',headers=admin,json=payload()).status_code==409
    booked=c.post('/api/v1/appointments',headers=admin,json=payload(start='11:15'));assert booked.status_code==200,booked.text
    assert c.post('/api/v1/appointments/schedule-exceptions',headers=admin,json={**exception,'start_time':None,'end_time':None,'exception_type':'LEAVE'}).status_code==409
    r=c.patch('/api/v1/appointments/schedule-exceptions/'+exc['exception_id']+'/cancel',headers=admin,json={'row_version':exc['row_version'],'reason':'Fictional break cancelled'});assert r.status_code==200,r.text
    assert len(slots())==3
    r=c.post('/api/v1/appointments/schedule-exceptions',headers=admin,json={**exception,'exception_type':'ADDITIONAL','start_time':'12:00','end_time':'12:30'});assert r.status_code==201,r.text
    assert len(slots())==5
    additional=r.json();assert c.post('/api/v1/appointments',headers=admin,json=payload(start='12:00')).status_code==200
    assert c.patch('/api/v1/appointments/schedule-exceptions/'+additional['exception_id']+'/cancel',headers=admin,json={'row_version':1,'reason':'Attempt to remove booked clinic'}).status_code==409


def test_appointment_branch_identity_and_payload_boundaries(scheduling):
    (c,db,branches,users,admin,login),doc,payload,slots,create=scheduling
    p=payload();reception=login(users['RECEPTIONIST'].username)
    row=c.post('/api/v1/appointments',headers=admin,json=payload(branch=1)).json()
    url='/api/v1/appointments/'+row['appointment_id']
    assert c.get(url,headers=reception).status_code==403
    assert c.patch(url+'/status',headers=reception,params={'status_code':'CANCELLED','row_version':1,'reason':'Unauthorized'}).status_code==403
    assert c.get('/api/v1/appointments/availability',headers=reception,params={'doctor_id':str(doc.doctor_id),'branch_id':str(branches[1].branch_id),'on_date':str(DAY)}).status_code==403
    assert c.post('/api/v1/appointments',headers=admin,json={**p,'patient_id':str(uuid.uuid4())}).status_code==422
    assert c.post('/api/v1/appointments',headers=admin,json={**p,'doctor_id':str(uuid.uuid4())}).status_code==404
    assert c.post('/api/v1/appointments',headers=admin,json={**p,'lead_id':None,'patient_id':str(uuid.uuid4())}).status_code==404
    assert c.post('/api/v1/appointments',headers=admin,json={**p,'scheduled_start':f'{DAY}T11:00:00','scheduled_end':f'{DAY}T11:15:00'}).status_code==422
    assert c.get('/api/v1/appointments').status_code==401
    assert c.get('/api/v1/appointments',headers=login(users['DOCTOR'].username)).status_code==403

@pytest.mark.skipif(not os.getenv('STAFF_TEST_DATABASE_URL'),reason='Requires real PostgreSQL for concurrent row locks')
def test_postgres_simultaneous_cross_branch_booking_and_retry(scheduling):
    (c,db,branches,users,admin,login),doc,payload,slots,create=scheduling
    first=payload();second=payload(branch=1)
    actor_id=users['ADMIN'].user_id;binding=db.bind
    db.commit()
    def race(payloads):
        barrier=Barrier(2)
        def attempt(raw):
            with Session(binding) as transaction:
                transaction.execute(text("SET statement_timeout = '10000'"))
                actor=transaction.get(User,actor_id);barrier.wait(timeout=5)
                try:
                    item=engine.book(transaction,actor,AppointmentCreate(**raw));transaction.commit()
                    return 200,str(item.appointment_id)
                except HTTPException as e:
                    transaction.rollback();return e.status_code,None
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(attempt,p) for p in payloads]
            return [f.result(timeout=15) for f in futures]
    result=race([first,second]);assert sorted(r[0] for r in result)==[200,409],result
    same=payload(start='11:30')
    result=race([same,same]);assert [r[0] for r in result]==[200,200] and result[0][1]==result[1][1],result
