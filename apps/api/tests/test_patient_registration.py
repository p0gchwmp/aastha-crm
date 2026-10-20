"""Module 4 HTTP identity tests and real PostgreSQL concurrent registrations."""
import uuid
from datetime import date,datetime,timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from test_staff_access import clinic
from test_lead_register import leads
from test_appointments import scheduling
from app.models import Base
from app.models.core import NumberSeries,Permission,RolePermission,UserRole,User
from app.models.patient import Patient,PatientContact,PatientAddress,Region,District,Locality
from app.models.crm import Lead,LeadPatientLink,LeadStatusHistory
from app.models.clinical import Visit
from app.models.scheduling import Appointment
from app.models.integration import AuditEvent
from app.schemas.patient import PatientCreate,LeadPatientConversionCreate

@pytest.fixture
def registration(scheduling):
    clinic_data,doc,appointment,slots,new_lead=scheduling
    c,db,branches,users,admin,login=clinic_data
    if db.bind.dialect.name=='sqlite':
        Base.metadata.create_all(db.bind,tables=[m.__table__ for m in (NumberSeries,PatientContact,PatientAddress,Region,District,Locality,LeadPatientLink,Visit)])
    for code in ('PATIENT_CREATE','PATIENT_VIEW','PATIENT_EDIT'):
        p=db.scalar(select(Permission).where(Permission.code==code))
        if not p:p=Permission(code=code,name=code);db.add(p);db.flush()
        for user in (users['ADMIN'],users['RECEPTIONIST']):
            role=db.scalar(select(UserRole.role_id).where(UserRole.user_id==user.user_id))
            if not db.scalar(select(RolePermission).where(RolePermission.role_id==role,RolePermission.permission_id==p.permission_id)):
                db.add(RolePermission(role_id=role,permission_id=p.permission_id))
    series=NumberSeries(organization_id=users['ADMIN'].organization_id,series_code='UHID',branch_id=None,fiscal_year=None,prefix_template='AAS-{NUMBER}',current_number=0,reset_rule='NEVER')
    db.add(series);db.commit()
    def payload(**extra):
        return {'organization_id':str(users['ADMIN'].organization_id),'registration_branch_id':str(branches[0].branch_id),'full_name':'Fictional Patient','mobile':'9876543210','gender':'Female','age_years':35,'identity_verified':True,'registration_request_id':str(uuid.uuid4()),**extra}
    yield clinic_data,payload,new_lead,appointment,series


def test_verified_registration_retry_global_search_and_shared_mobile(registration):
    (c,db,branches,users,admin,login),payload,new_lead,appointment,series=registration
    reception=login(users['RECEPTIONIST'].username)
    p=payload()
    assert c.post('/api/v1/patients',headers=reception,json={**p,'identity_verified':False}).status_code==422
    assert c.post('/api/v1/patients',headers=reception,json={**p,'registration_request_id':None}).status_code==422
    r=c.post('/api/v1/patients',headers=reception,json=p);assert r.status_code==200,r.text
    pid=r.json()['patient_id'];uhid=r.json()['uhid']
    assert c.post('/api/v1/patients',headers=reception,json=p).json()['patient_id']==pid
    assert c.post('/api/v1/patients',headers=reception,json={**p,'full_name':'Changed retry'}).status_code==409
    detail=c.get('/api/v1/patients/'+pid,headers=admin).json()
    assert detail['dob'] is None and detail['age']==35 and detail['age_is_estimated'] is True
    assert detail['age_recorded_on']==str(datetime.now().astimezone(__import__('zoneinfo').ZoneInfo('Asia/Kolkata')).date())
    second=payload(full_name='Fictional Family Member',registration_branch_id=str(branches[1].branch_id))
    assert c.post('/api/v1/patients',headers=admin,json=second).status_code==409
    r=c.post('/api/v1/patients',headers=admin,json={**second,'duplicate_override_confirmed':True});assert r.status_code==200,r.text
    assert r.json()['uhid']!=uhid
    rows=c.get('/api/v1/patients/search?q=9876543210',headers=reception).json()
    assert {pid,r.json()['patient_id']} <= {x['patient_id'] for x in rows}
    assert c.get('/api/v1/patients/search?q='+uhid,headers=reception).json()[0]['patient_id']==pid
    db.refresh(series);assert series.current_number==2
    assert db.scalar(select(func.count()).select_from(Visit))==0


def test_conversion_verification_existing_selection_history_and_retry(registration):
    (c,db,branches,users,admin,login),payload,new_lead,appointment,series=registration
    lead=new_lead(lead_name='Fictional Conversion',age=41).json();url='/api/v1/leads/'+lead['lead_id']
    appt=c.post('/api/v1/appointments',headers=admin,json=appointment(lead_id=lead['lead_id'])).json()
    preview=c.get(url+'/conversion-preview',headers=admin).json()
    assert preview['age']==41 and preview['already_converted_patient_id'] is None
    assert db.scalar(select(func.count()).select_from(Patient).where(Patient.organization_id==users['ADMIN'].organization_id))==0
    p=payload(full_name='Verified Corrected Name',lead_row_version=preview['lead_row_version'])
    assert c.post(url+'/convert',headers=admin,json={**p,'identity_verified':False}).status_code==422
    assert c.post(url+'/convert',headers=admin,json={**p,'lead_row_version':1}).status_code==409
    r=c.post(url+'/convert',headers=admin,json=p);assert r.status_code==200,r.text
    patient=r.json();assert patient['full_name']=='Verified Corrected Name'
    assert c.post(url+'/convert',headers=admin,json=p).json()['patient_id']==patient['patient_id']
    assert c.get(url,headers=admin).json()['status_code']=='CONVERTED'
    db.refresh(db.get(Appointment,uuid.UUID(appt['appointment_id'])))
    linked=db.get(Appointment,uuid.UUID(appt['appointment_id']))
    assert str(linked.patient_id)==patient['patient_id'] and str(linked.lead_id)==lead['lead_id'] and linked.row_version==appt['row_version']+1
    assert c.get(url+'/conversion-preview',headers=admin).json()['already_converted_patient_id']==patient['patient_id']
    new=new_lead(lead_name='New Inquiry').json();newurl='/api/v1/leads/'+new['lead_id']
    assert c.post(newurl+'/dnc',headers=admin,json={'dnc':True,'reason':'Fictional inbound only','row_version':new['row_version']}).status_code==200
    new=c.get(newurl,headers=admin).json()
    q=payload(lead_row_version=new['row_version'],existing_patient_id=patient['patient_id'],existing_patient_row_version=patient['row_version'])
    assert c.post(newurl+'/convert',headers=admin,json={**q,'existing_patient_row_version':999}).status_code==409
    r=c.post(newurl+'/convert',headers=admin,json=q);assert r.status_code==200,r.text
    assert r.json()['patient_id']==patient['patient_id']
    assert c.get(newurl,headers=admin).json()['dnc'] is True
    db.refresh(series);assert series.current_number==1
    assert len(db.scalars(select(LeadPatientLink).where(LeadPatientLink.patient_id==uuid.UUID(patient['patient_id']))).all())==2
    assert db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action=='LEAD_CONVERTED',AuditEvent.entity_id==uuid.UUID(lead['lead_id'])))==1


def test_registration_boundaries_validation_duplicate_review_and_stale_edit(registration):
    (c,db,branches,users,admin,login),payload,new_lead,appointment,series=registration
    reception=login(users['RECEPTIONIST'].username)
    for bad in ({'full_name':'  '},{'mobile':'123'},{'dob':'2999-01-01','age_years':None},{'age_years':-1},{'gender':'invalid'},{'dob':'2000-01-01','age_years':20}):
        assert c.post('/api/v1/patients',headers=admin,json=payload(**bad)).status_code==422
    assert c.post('/api/v1/patients',json=payload()).status_code==401
    assert c.post('/api/v1/patients',headers=login(users['DOCTOR'].username),json=payload()).status_code==403
    for branch,org,status in ((branches[1],users['ADMIN'].organization_id,403),(branches[2],branches[2].organization_id,403)):
        assert c.post('/api/v1/patients',headers=reception,json=payload(registration_branch_id=str(branch.branch_id),organization_id=str(org))).status_code==status
    lead=new_lead().json();p=payload(lead_row_version=lead['row_version'],registration_branch_id=str(branches[1].branch_id))
    assert c.post('/api/v1/leads/'+lead['lead_id']+'/convert',headers=reception,json=p).status_code==403
    first=c.post('/api/v1/patients',headers=admin,json=payload()).json();pid=first['patient_id']
    assert c.post('/api/v1/patients',headers=admin,json=payload()).status_code==409
    q=payload(lead_row_version=lead['row_version'])
    assert c.post('/api/v1/leads/'+lead['lead_id']+'/convert',headers=admin,json=q).status_code==409
    assert c.post('/api/v1/leads/'+lead['lead_id']+'/convert',headers=admin,json={**q,'duplicate_override_confirmed':True}).status_code==200
    patch={'row_version':first['row_version'],'full_name':'Corrected Patient','reason':'Verified spelling correction'}
    r=c.patch('/api/v1/patients/'+pid,headers=reception,json=patch);assert r.status_code==200,r.text
    assert c.patch('/api/v1/patients/'+pid,headers=reception,json=patch).status_code==409
    assert c.patch('/api/v1/patients/'+pid,headers=reception,json={'row_version':r.json()['row_version'],'reason':'   '}).status_code==422
    assert db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action=='PATIENT_UPDATED',AuditEvent.entity_id==uuid.UUID(pid)))==1


def test_address_hierarchy_and_global_patient_existing_choice(registration):
    (c,db,branches,users,admin,login),payload,new_lead,appointment,series=registration
    region=Region(name=uuid.uuid4().hex);other=Region(name=uuid.uuid4().hex);db.add_all([region,other]);db.flush()
    district=District(region_id=region.region_id,name='Test District');db.add(district);db.flush()
    locality=Locality(district_id=district.district_id,locality_name='Provisional Test',approval_status='PENDING');db.add(locality);db.commit()
    address={'region_id':str(region.region_id),'district_id':str(district.district_id),'locality_id':str(locality.locality_id),'address_line':'Fictional address'}
    assert c.post('/api/v1/patients',headers=admin,json=payload(**{**address,'region_id':str(other.region_id)})).status_code==400
    r=c.post('/api/v1/patients',headers=admin,json=payload(registration_branch_id=str(branches[1].branch_id),**address));assert r.status_code==200,r.text
    patient=c.get('/api/v1/patients/'+r.json()['patient_id'],headers=admin).json()
    matches=c.get('/api/v1/patients/match',headers=admin,params={'name':'Fictional Patient','mobile':'9876543210','age_years':35,'gender':'Female',**{'locality_id':address['locality_id'],'address_line':address['address_line']}}).json()
    assert {'Same mobile','Same age','Same gender','Same locality','Same address'} <= set(matches[0]['match_reasons'])
    lead=new_lead().json();p=payload(lead_row_version=lead['row_version'],existing_patient_id=patient['patient_id'],existing_patient_row_version=patient['row_version'])
    r=c.post('/api/v1/leads/'+lead['lead_id']+'/convert',headers=login(users['RECEPTIONIST'].username),json=p);assert r.status_code==200,r.text
    assert r.json()['patient_id']==patient['patient_id']


def test_postgres_concurrent_conversion_registration_retries_and_uhids(registration):
    (c,db,branches,users,admin,login),payload,new_lead,appointment,series=registration
    if db.bind.dialect.name!='postgresql':pytest.skip('Real PostgreSQL row locks required')
    from app.api.routes.patients import create
    from app.api.routes.leads import convert_to_patient
    lead=new_lead().json();p=payload(lead_row_version=lead['row_version']);uid=users['ADMIN'].user_id
    def race(fn):
        barrier=Barrier(2)
        def run(i):
            with Session(db.bind,expire_on_commit=False) as local:
                user=local.get(User,uid);barrier.wait(timeout=10)
                return fn(local,user,i)
        with ThreadPoolExecutor(2) as pool:return list(pool.map(run,range(2)))
    def convert(local,user,i):
        return convert_to_patient(uuid.UUID(lead['lead_id']),LeadPatientConversionCreate(**p),None,local,user)['patient_id']
    ids=race(convert);assert ids[0]==ids[1]
    direct=payload(full_name='Separate fictional patient',mobile='9123456789')
    def retry(local,user,i):
        return create(PatientCreate(**direct),None,local,user).patient_id
    ids=race(retry);assert ids[0]==ids[1]
    requests=[payload(full_name='Concurrent '+str(i),mobile='923456789'+str(i),registration_branch_id=str(branches[i].branch_id)) for i in range(2)]
    def unique(local,user,i):return create(PatientCreate(**requests[i]),None,local,user).uhid
    numbers=race(unique);assert len(set(numbers))==2
    db.expire_all();assert db.get(NumberSeries,series.number_series_id).current_number==4
