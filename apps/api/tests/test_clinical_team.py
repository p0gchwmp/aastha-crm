"""Clinical accounts, assigned preparation privacy, review gates and transactions."""
import uuid
import pytest
from sqlalchemy import select,func
from test_staff_access import clinic,TEMP,NEW,RESET
from test_lead_register import leads
from test_appointments import scheduling
from test_patient_registration import registration
from test_visit_management import encounters
from app.models import Base
from app.models.core import Doctor,User,UserRole,Permission,RolePermission
from app.models.clinical import Visit,VisitStatus
from app.models.preparation import ClinicalPreparation,PreparationRevision
from app.services.clinical_team import configure_permissions
from app.api.routes import clinical_preparations as service
TEAM='/api/v1/admin/clinical-team';PREP='/api/v1/clinical-preparations';DOC='/api/v1/doctor-consultations'

@pytest.fixture
def team(encounters):
 data,payload,patient,*_=encounters;c,db,branches,users,admin,login=data
 if db.bind.dialect.name=='sqlite':Base.metadata.create_all(db.bind)
 configure_permissions(db)
 for code in ('IN_PROGRESS','CANCELLED'):
  if not db.scalar(select(VisitStatus).where(VisitStatus.code==code)):db.add(VisitStatus(code=code,name=code))
 role=db.scalar(select(UserRole.role_id).where(UserRole.user_id==users['DOCTOR'].user_id));perm=db.scalar(select(Permission).where(Permission.code=='CONSULTATION_CLINICAL'))
 if not perm:perm=Permission(code='CONSULTATION_CLINICAL',name='Consultation');db.add(perm);db.flush()
 if not db.scalar(select(RolePermission).where(RolePermission.role_id==role,RolePermission.permission_id==perm.permission_id)):db.add(RolePermission(role_id=role,permission_id=perm.permission_id))
 db.commit()
 def create(kind='DOCTOR',branch=0):
  p={'name':'Fictional '+kind,'username':'clinical'+uuid.uuid4().hex[:18],'role':kind,'branch_ids':[str(branches[branch].branch_id)],'temporary_password':TEMP,**({'doctor_code':uuid.uuid4().hex[:12]} if kind=='DOCTOR' else {})}
  r=c.post(TEAM,headers=admin,json=p);assert r.status_code==201,r.text
  temp=login(p['username'],TEMP);assert c.post('/api/v1/auth/change-password',headers=temp,json={'current_password':TEMP,'new_password':NEW}).status_code==200
  user=next(x for x in c.get(TEAM,headers=admin).json()['users'] if x['username']==p['username']);return user,login(p['username'])
 doctor,dh=create();assistant,ah=create('CLINICAL_ASSISTANT')
 def visit():
  r=c.post('/api/v1/visits',headers=admin,json={**payload(),'doctor_id':doctor['doctor']['doctor_id']});assert r.status_code==200,r.text;return r.json()
 def assign(v,who=assistant,version=0):
  p={'request_id':str(uuid.uuid4()),'row_version':version,'assistant_user_id':who['user_id'],'reason':'Fictional preparation assignment'};r=c.post(PREP+'/'+v['visit_id']+'/assign',headers=admin,json=p);assert r.status_code==200,r.text;return r.json(),p
 def draft(v,p,**extra):return {'request_id':str(uuid.uuid4()),'row_version':p['row_version'],'identity_confirmed':True,'patient_version':patient['row_version'],'history':'Fictional assistant history','allergy_status':'UNKNOWN','weight_kg':'50.25',**extra}
 return data,create,doctor,dh,assistant,ah,visit,assign,draft,patient


def test_account_lifecycle_and_privileged_boundaries(team):
 (c,db,branches,users,admin,login),create,d,dh,a,ah,*_=team
 listing=c.get(TEAM,headers=admin);assert 'password_hash' not in listing.text and TEMP not in listing.text
 assert c.get(TEAM,headers=dh).status_code==403 and c.get(TEAM,headers=ah).status_code==403
 p={'row_version':d['row_version'],'temporary_password':RESET,'reason':'Forgot credentials'}
 assert c.post(TEAM+'/'+d['user_id']+'/reset-password',headers=admin,json=p).status_code==200
 assert c.get('/api/v1/auth/me',headers=dh).status_code==401
 temp=login(d['username'],RESET);assert c.get(DOC+'?on_date=2030-01-08',headers=temp).status_code==403
 assert c.post('/api/v1/auth/change-password',headers=temp,json={'current_password':RESET,'new_password':NEW}).status_code==200
 dh=login(d['username']);current=next(x for x in c.get(TEAM,headers=admin).json()['users'] if x['user_id']==d['user_id'])
 change={'name':d['name'],'role':'DOCTOR','branch_ids':d['branch_ids'],'status':'INACTIVE','row_version':current['row_version'],'reason':'Disable access'}
 assert c.patch(TEAM+'/'+d['user_id'],headers=admin,json=change).status_code==200
 assert c.get('/api/v1/auth/me',headers=dh).status_code==401 and db.get(Doctor,uuid.UUID(d['doctor']['doctor_id'])).active is False
 assert c.patch(TEAM+'/'+d['user_id'],headers=admin,json=change).status_code==409
 assert c.post(TEAM+'/'+str(users['ADMIN'].user_id)+'/reset-password',headers=admin,json={'row_version':users['ADMIN'].row_version,'temporary_password':RESET,'reason':'Forbidden reset'}).status_code==403
 assert c.get(TEAM,headers=login(users['RECEPTIONIST'].username)).status_code==403
 assert c.post('/api/v1/admin/staff/'+d['user_id']+'/reset-password',headers=admin,json=p).status_code==403


def test_handover_retry_review_completion_and_privacy(team):
 (c,db,branches,users,admin,login),create,d,dh,a,ah,visit,assign,draft,patient=team
 v=visit();p,assignment=assign(v);url=PREP+'/'+v['visit_id'];du=DOC+'/'+v['visit_id']
 assert c.post(url+'/assign',headers=admin,json=assignment).json()['row_version']==p['row_version']
 assert c.get(PREP+'?on_date=2030-01-08',headers=ah).json()[0]['visit']['visit_id']==v['visit_id']
 for path in ('/patients/'+patient['patient_id'],'/doctor-consultations/'+v['visit_id'],'/consultation-finance/setup'):assert c.get('/api/v1'+path,headers=ah).status_code==403
 body=draft(v,p)
 for extra in ({'identity_confirmed':False},{'patient_version':999}):assert c.post(url+'/save',headers=ah,json={**body,**extra}).status_code==409
 assert c.post(url+'/save',headers=ah,json={**body,'diagnosis':'Forbidden'}).status_code==422
 r=c.post(url+'/save',headers=ah,json=body);assert r.status_code==200,r.text;saved=r.json()
 assert c.post(url+'/save',headers=ah,json=body).json()['row_version']==saved['row_version']
 assert c.post(url+'/save',headers=ah,json={**body,'history':'Changed'}).status_code==409
 assert c.post(url+'/save',headers=ah,json=draft(v,p)).status_code==409
 r=c.post(url+'/submit',headers=ah,json=draft(v,saved));assert r.status_code==200,r.text;submitted=r.json()
 assert submitted['state']=='SUBMITTED' and submitted['submitted_at']
 assert c.post(url+'/save',headers=ah,json=draft(v,submitted)).status_code==409
 context=c.get(du,headers=dh).json();assert context['preparation']['history']=='Fictional assistant history' and context['note'] is None
 start={'request_id':str(uuid.uuid4()),'row_version':context['visit']['row_version'],'identity_confirmed':True,'patient_version':patient['row_version']}
 r=c.post(du+'/start',headers=dh,json=start);assert r.status_code==200,r.text
 finish={'request_id':str(uuid.uuid4()),'row_version':r.json()['visit']['row_version'],'history':'Doctor private note'}
 assert c.post(du+'/complete',headers=dh,json=finish).status_code==409
 review={'request_id':str(uuid.uuid4()),'row_version':submitted['row_version']}
 assert c.post(du+'/review-preparation',headers=ah,json=review).status_code==403
 r=c.post(du+'/review-preparation',headers=dh,json=review);assert r.status_code==200,r.text
 assert r.json()['reviewed_by_doctor_id']==d['doctor']['doctor_id'] and c.post(du+'/review-preparation',headers=dh,json=review).status_code==200
 finish.update(row_version=c.get(du,headers=dh).json()['visit']['row_version'],request_id=str(uuid.uuid4()))
 assert c.post(du+'/complete',headers=dh,json=finish).status_code==200
 assert 'Doctor private note' not in c.get(url,headers=ah).text
 reception=login(users['RECEPTIONIST'].username);ordinary=c.get('/api/v1/visits/'+v['visit_id'],headers=reception)
 assert c.get(url,headers=reception).status_code==403 and ordinary.json()['status_code']=='COMPLETED' and 'Fictional assistant history' not in ordinary.text
 assert db.scalar(select(func.count()).select_from(PreparationRevision).join(ClinicalPreparation).where(ClinicalPreparation.visit_id==uuid.UUID(v['visit_id'])))==4


def test_two_doctors_assistants_and_branch_isolation(team):
 (c,db,branches,users,admin,login),create,d,dh,a,ah,visit,assign,draft,patient=team
 d2,h2=create();a2,ah2=create('CLINICAL_ASSISTANT');a3,ah3=create('CLINICAL_ASSISTANT',1)
 v=visit();p,_=assign(v);url=PREP+'/'+v['visit_id']
 assert c.get(DOC+'/'+v['visit_id'],headers=h2).status_code==403 and c.get(DOC+'?on_date=2030-01-08',headers=h2).json()==[]
 assert c.get(url,headers=ah2).status_code==403 and c.get(PREP+'?on_date=2030-01-08',headers=ah2).json()==[]
 bad={'request_id':str(uuid.uuid4()),'row_version':p['row_version'],'assistant_user_id':a3['user_id'],'reason':'Wrong branch'}
 assert c.post(url+'/assign',headers=admin,json=bad).status_code==422
 assert c.post(url+'/assign',headers=h2,json={**bad,'assistant_user_id':a2['user_id']}).status_code==403
 r=c.post(url+'/save',headers=ah,json=draft(v,p));assert r.status_code==200
 assign(v,a2,r.json()['row_version']);assert c.get(url,headers=ah).status_code==403
 assert c.get(url,headers=ah2).json()['preparation']['history'] is None
 prep=db.scalar(select(ClinicalPreparation).where(ClinicalPreparation.visit_id==uuid.UUID(v['visit_id'])))
 assert any(r.snapshot['history']=='Fictional assistant history' for r in db.scalars(select(PreparationRevision).where(PreparationRevision.preparation_id==prep.preparation_id)).all())
 row=db.get(Visit,uuid.UUID(v['visit_id']));payload={'patient_id':patient['patient_id'],'patient_row_version':patient['row_version'],'creation_request_id':str(uuid.uuid4()),'branch_id':str(branches[1].branch_id),'doctor_id':d['doctor']['doctor_id'],'visit_type_id':str(row.visit_type_id),'identity_confirmed':True}
 assert c.post('/api/v1/visits',headers=admin,json=payload).status_code==409


def test_validation_and_atomic_rollback(team,monkeypatch):
 (c,db,branches,users,admin,login),create,d,dh,a,ah,visit,assign,draft,patient=team
 v=visit();p,_=assign(v)
 for extra in ({'systolic':120},{'weight_kg':'NaN'},{'spo2':'101'},{'temperature_c':'-1'},{'allergy_status':'NONE_REPORTED','allergies':'Contradictory text'}):assert c.post(PREP+'/'+v['visit_id']+'/save',headers=ah,json=draft(v,p,**extra)).status_code==422
 def fail(*args,**kwargs):raise RuntimeError('Injected audit failure')
 monkeypatch.setattr(service,'log_audit',fail)
 with pytest.raises(RuntimeError):service.write(uuid.UUID(v['visit_id']),'save',service.Draft(**draft(v,p)),db,db.get(User,uuid.UUID(a['user_id'])))
 db.expire_all();prep=db.scalar(select(ClinicalPreparation).where(ClinicalPreparation.visit_id==uuid.UUID(v['visit_id'])))
 assert prep.state=='ASSIGNED' and prep.history is None and prep.row_version==p['row_version']


def test_doctor_returns_preparation_without_losing_observations(team):
 (c,db,branches,users,admin,login),create,d,dh,a,ah,visit,assign,draft,patient=team
 v=visit();p,_=assign(v);url=PREP+'/'+v['visit_id'];du=DOC+'/'+v['visit_id']
 submitted=c.post(url+'/submit',headers=ah,json=draft(v,p)).json()
 request={'row_version':submitted['row_version'],'request_id':str(uuid.uuid4()),'reason':'Please check the recorded measurements'}
 r=c.post(du+'/return-preparation',headers=dh,json=request);assert r.status_code==200,r.text
 returned=r.json();assert returned['state']=='DRAFT' and returned['history']=='Fictional assistant history' and returned['return_note']==request['reason']
 assert c.post(du+'/return-preparation',headers=dh,json=request).status_code==200
 r=c.post(url+'/submit',headers=ah,json=draft(v,returned,observations='Measurements rechecked'));assert r.status_code==200 and r.json()['state']=='SUBMITTED'


def test_postgresql_concurrent_preparation_saves(team):
 from concurrent.futures import ThreadPoolExecutor
 from threading import Barrier
 from sqlalchemy.orm import Session
 from fastapi import HTTPException
 (c,db,branches,users,admin,login),create,d,dh,a,ah,visit,assign,draft,patient=team
 if db.bind.dialect.name!='postgresql':pytest.skip('Real PostgreSQL row locks required')
 v=visit();p,_=assign(v);body=draft(v,p);actor_id=uuid.UUID(a['user_id']);engine=db.bind;db.commit();barrier=Barrier(2)
 def save(text):
  with Session(engine) as session:
   actor=session.get(User,actor_id);payload=service.Draft(**{**body,'request_id':str(uuid.uuid4()),'history':text});barrier.wait()
   try:service.write(uuid.UUID(v['visit_id']),'save',payload,session,actor);return 200
   except HTTPException as exc:return exc.status_code
 with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(save,['First screen','Second screen']))
 assert sorted(results)==[200,409]
 db.expire_all();prep=db.scalar(select(ClinicalPreparation).where(ClinicalPreparation.visit_id==uuid.UUID(v['visit_id'])))
 assert prep.row_version==2 and db.scalar(select(func.count()).select_from(PreparationRevision).where(PreparationRevision.preparation_id==prep.preparation_id))==2


def test_branch_removal_expiry_and_old_profile_linking(team):
 from datetime import date,timedelta
 (c,db,branches,users,admin,login),create,d,dh,a,ah,visit,assign,draft,patient=team
 v=visit();p,_=assign(v)
 change={'name':d['name'],'role':'DOCTOR','branch_ids':[str(branches[1].branch_id)],'status':'ACTIVE','row_version':d['row_version'],'reason':'Try removing branch with an open Visit'}
 assert c.patch(TEAM+'/'+d['user_id'],headers=admin,json=change).status_code==409
 user=db.get(User,uuid.UUID(a['user_id']));role=db.scalar(select(UserRole).where(UserRole.user_id==user.user_id));role.valid_until=date.today()-timedelta(days=1);db.commit()
 assert c.get(PREP+'/'+v['visit_id'],headers=ah).status_code==403
 # Attaching a login to an old operational Doctor must retain its permanent ID.
 old=Doctor(organization_id=users['ADMIN'].organization_id,doctor_code=uuid.uuid4().hex[:15],doctor_name='Existing operational Doctor',active=True);db.add(old);db.commit();old_id=str(old.doctor_id)
 payload={'name':'Existing operational Doctor','username':'linked'+uuid.uuid4().hex[:15],'role':'DOCTOR','existing_doctor_id':old_id,'branch_ids':[str(branches[0].branch_id)],'temporary_password':TEMP}
 r=c.post(TEAM,headers=admin,json=payload);assert r.status_code==201,r.text
 assert r.json()['doctor']['doctor_id']==old_id
 assert c.post(TEAM,headers=admin,json={**payload,'username':'other'+uuid.uuid4().hex[:15]}).status_code==409
 # Administrative accounts cannot be smuggled through the clinical role selector.
 assert c.post(TEAM,headers=admin,json={**payload,'role':'SUPER_ADMIN'}).status_code==422
