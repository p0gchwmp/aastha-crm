import uuid
import pytest
from sqlalchemy import select
from test_staff_access import clinic
from test_lead_register import leads
from test_appointments import scheduling
from test_patient_registration import registration
from test_visit_management import encounters
from test_doctor_consultations import clinical
from app.models.safety import SafetyAssessment, SafetyEntry
S='/api/v1/patient-safety/'
def payload(p,**extra):return {'request_id':str(uuid.uuid4()),'row_version':0,'patient_version':p['row_version'],'identity_confirmed':True,**extra}
def entry(kind,**extra):return dict(entry_id=str(uuid.uuid4()),kind=kind,name='Fictional '+kind,**extra)

def test_review_retry_history_closed_visit_and_private_serializers(clinical):
 (c,db,branches,users,admin,login),h,visit,action,p,doctor=clinical
 v=action(visit())[0].json()['visit'];url=S+v['visit_id']
 assert c.get(url,headers=h).json()['assessment'] is None
 body=payload(p,allergy_status='REPORTED',medicine_status='REPORTED',doctor_confirmed=True,weight_kg='12.25',weight_date='2020-01-01',entries=[entry('ALLERGY',reaction='Private fictional reaction'),entry('MEDICINE',source='Patient report',exposure_status='RECENTLY_STOPPED'),entry('RESULT',value='1.2',unit='test',observed_on='2020-01-01')])
 r=c.post(url,headers=h,json=body);assert r.status_code==200,r.text
 a=r.json()['assessment'];assert a['reviewed_by_doctor_id']==str(doctor.doctor_id) and a['weight_kg']=='12.25'
 assert a['pregnancy_status']=='NOT_ASSESSED'
 assert c.post(url,headers=h,json=body).json()['assessment']['row_version']==1
 assert c.post(url,headers=h,json={**body,'weight_kg':'13.25'}).status_code==409
 assert c.post(url,headers=h,json={**body,'request_id':str(uuid.uuid4())}).status_code==409
 changed={**body,'row_version':1,'request_id':str(uuid.uuid4()),'doctor_confirmed':False,'entries':body['entries'][:1],'medicine_status':'NOT_ASSESSED'}
 r=c.post(url,headers=h,json=changed);assert r.status_code==200,r.text
 assert not r.json()['assessment']['reviewed_at']
 assert len(db.scalars(select(SafetyEntry).where(SafetyEntry.assessment_id==uuid.UUID(a['assessment_id']),SafetyEntry.active.is_(False))).all())==2
 assert len(c.get(url,headers=h).json()['revisions'])==2
 assert action(v,'save')[0].status_code==409
 v=c.get('/api/v1/doctor-consultations/'+v['visit_id'],headers=h).json()['visit']
 assert action(v,'complete')[0].status_code==409
 r=c.post(url,headers=h,json={**changed,'row_version':2,'request_id':str(uuid.uuid4()),'doctor_confirmed':True});assert r.status_code==200,r.text
 v=c.get('/api/v1/doctor-consultations/'+v['visit_id'],headers=h).json()['visit']
 r,_=action(v,'complete');assert r.status_code==200,r.text
 assert not c.get(url,headers=h).json()['editable']
 assert c.post(url,headers=h,json={**changed,'row_version':2,'request_id':str(uuid.uuid4())}).status_code==409
 v2=visit();d=c.get(S+v2['visit_id'],headers=h).json()
 assert d['assessment'] is None and d['previous']['row_version']==3
 history=c.get('/api/v1/doctor-consultations/'+v['visit_id'],headers=h).json()['revisions'][-1]['snapshot']['patient_safety']
 assert history['row_version']==3
 for header in (admin,login(users['RECEPTIONIST'].username)):
  assert c.get(url,headers=header).status_code==403
  assert c.post(url,headers=header,json=body).status_code==403
  assert 'Private fictional reaction' not in c.get('/api/v1/visits/'+v['visit_id'],headers=header).text
 assert c.get(url).status_code==401

@pytest.mark.parametrize('extra',[
 {'allergy_status':'NONE_REPORTED','entries':[entry('ALLERGY',reaction='Test')]},
 {'allergy_status':'REPORTED'}, {'entries':[entry('RESULT',value='1')]},
 {'medicine_status':'REPORTED','entries':[entry('MEDICINE')]},
 {'weight_kg':'0'},{'weight_kg':'10'},{'weight_date':'2020-01-01'},
 {'weight_kg':'10','weight_date':'2099-01-01'},
 {'entries':[entry('RESULT',value='1',observed_on='2099-01-01')]},
 {'allergy_status':'NONE_KNOWN'},{'entries':[entry('PROCEDURE')]}])
def test_reject_missing_inconsistent_future_information(clinical,extra):
 (c,*_),h,visit,action,p,_=clinical
 v=action(visit())[0].json()['visit']
 r=c.post(S+v['visit_id'],headers=h,json=payload(p,**extra));assert r.status_code==422,r.text
 assert c.get(S+v['visit_id'],headers=h).json()['assessment'] is None

def test_identity_access_cross_record_ids_and_rollback(clinical):
 (c,db,*_),h,visit,action,p,_=clinical
 v=visit();url=S+v['visit_id']
 assert c.post(url,headers=h,json=payload(p)).status_code==409
 action(v)
 assert c.post(url,headers=h,json=payload(p,identity_confirmed=False)).status_code==409
 assert c.post(url,headers=h,json=payload(p,patient_version=999)).status_code==409
 e=entry('CONDITION');body=payload(p,condition_status='REPORTED',entries=[e])
 assert c.post(url,headers=h,json=body).status_code==200
 v2=action(visit())[0].json()['visit']
 assert c.post(S+v2['visit_id'],headers=h,json=payload(p,condition_status='REPORTED',entries=[e])).status_code==422
 assert c.get(S+v2['visit_id'],headers=h).json()['assessment'] is None
 assert len(db.scalars(select(SafetyAssessment).where(SafetyAssessment.visit_id==uuid.UUID(v['visit_id']))).all())==1
 assert c.post(S+v2['visit_id'],headers=h,json=payload(p,condition_status='REPORTED',entries=[e,e])).status_code==422
 from app.models.clinical import Visit
 row=db.get(Visit,uuid.UUID(v['visit_id']));row.doctor_id=None;db.commit()
 assert c.get(url,headers=h).status_code==403

from test_clinical_team import team

def test_assistant_draft_submission_and_doctor_review(team):
 (c,db,branches,users,admin,login),create,d,dh,a,ah,visit,assign,draft,p=team
 v=visit();prep,_=assign(v);url=S+v['visit_id']
 assert c.get(url,headers=ah).json()['editable']
 assert c.post(url,headers=ah,json=payload(p,doctor_confirmed=True)).status_code==403
 r=c.post(url,headers=ah,json=payload(p,medicine_status='REPORTED',entries=[entry('MEDICINE',source='Outside prescription')]));assert r.status_code==200,r.text
 assert not r.json()['assessment']['reviewed_at']
 other,otherh=create('CLINICAL_ASSISTANT');assert c.get(url,headers=otherh).status_code==403
 r=c.post('/api/v1/clinical-preparations/'+v['visit_id']+'/submit',headers=ah,json=draft(v,prep));assert r.status_code==200,r.text
 assert not c.get(url,headers=ah).json()['editable']
 assert c.post(url,headers=ah,json=payload(p,row_version=1)).status_code==409
 du='/api/v1/doctor-consultations/'+v['visit_id'];current=c.get(du,headers=dh).json()['visit']
 r=c.post(du+'/start',headers=dh,json={'request_id':str(uuid.uuid4()),'row_version':current['row_version'],'patient_version':p['row_version'],'identity_confirmed':True});assert r.status_code==200,r.text
 saved=c.get(url,headers=dh).json()['assessment']
 r=c.post(url,headers=dh,json=payload(p,row_version=saved['row_version'],medicine_status='REPORTED',entries=saved['entries'],doctor_confirmed=True));assert r.status_code==200,r.text
 assert not c.get(url,headers=ah).json()['editable']

def test_concurrent_safety_writers(clinical):
 from concurrent.futures import ThreadPoolExecutor
 from threading import Barrier
 from sqlalchemy.orm import Session
 from app.models.core import User
 from app.api.routes.patient_safety import save,AssessmentInput
 from fastapi import HTTPException
 (c,db,branches,users,admin,login),h,visit,action,p,doctor=clinical
 if db.bind.dialect.name!='postgresql':pytest.skip('Real PostgreSQL row locks required')
 v=action(visit())[0].json()['visit'];engine=db.bind;actor=users['DOCTOR'].user_id;db.commit();barrier=Barrier(2)
 def write():
  with Session(engine) as session:
   user=session.get(User,actor);barrier.wait()
   try:save(uuid.UUID(v['visit_id']),AssessmentInput(**payload(p)),session,user);return 200
   except HTTPException as e:return e.status_code
 with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:write(),range(2)))
 assert sorted(results)==[200,409]
 db.expire_all();assert len(db.scalars(select(SafetyAssessment).where(SafetyAssessment.visit_id==uuid.UUID(v['visit_id']))).all())==1
