"""Module 6 HTTP financial workflow and real PostgreSQL writer races."""
import uuid
from datetime import datetime,timezone,timedelta,date
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from test_staff_access import clinic
from test_lead_register import leads
from test_appointments import scheduling
from test_patient_registration import registration
from test_visit_management import encounters
from app.models import Base
from app.models.core import Service,Doctor,Permission,RolePermission,UserRole,NumberSeries,User
from app.models.clinical import Visit,VisitStatus
from app.models.finance import ConsultationBill,ConsultationPayment,ConsultationFeeVersion,ConsultationPolicyVersion,PaymentMode,FollowupEntitlement,EntitlementUsage,ConsultationClearance
from app.models.integration import AuditEvent
from app.services import consultation as engine
from app.schemas.finance import ConsultationPaymentCreate

STAMP=datetime(2030,1,8,6,tzinfo=timezone.utc)
PREFIX='/api/v1/consultation-finance'

@pytest.fixture
def finance(encounters,monkeypatch):
    data,visit_payload,patient,complaint,appointment,series=encounters
    c,db,branches,users,admin,login=data
    if db.bind.dialect.name=='sqlite':Base.metadata.create_all(db.bind)
    doctor=db.scalar(select(Doctor).where(Doctor.organization_id==users['ADMIN'].organization_id))
    doctor.user_id=users['DOCTOR'].user_id
    svc=Service(organization_id=users['ADMIN'].organization_id,service_code=uuid.uuid4().hex[:20],service_name='Consultation',clinical_type='CONSULTATION');db.add(svc)
    # No global seed masters in the HTTP fixture; make this org's policy explicit.
    policy=ConsultationPolicyVersion(organization_id=users['ADMIN'].organization_id,name='Test ten days',effective_from=date(2029,1,1),free_followup_window_days=10,max_free_followups=1);db.add(policy)
    for code in ('CASH','UPI','CARD'):
        if not db.scalar(select(PaymentMode).where(PaymentMode.code==code)):db.add(PaymentMode(code=code,name=code))
    for code in ('CONSULTATION_FINANCE_VIEW','CONSULTATION_BILL_CREATE','CONSULTATION_PAYMENT_CREATE','CONSULTATION_COMPLIMENTARY','FINANCE_CORRECT'):
        perm=db.scalar(select(Permission).where(Permission.code==code))
        if not perm:perm=Permission(code=code,name=code);db.add(perm);db.flush()
        for role,u in users.items():
            if role=='RECEPTIONIST' and code in {'FINANCE_CORRECT','CONSULTATION_COMPLIMENTARY'}:continue
            if role=='DOCTOR' and code not in {'CONSULTATION_FINANCE_VIEW','CONSULTATION_COMPLIMENTARY'}:continue
            rid=db.scalar(select(UserRole.role_id).where(UserRole.user_id==u.user_id))
            if not db.scalar(select(RolePermission).where(RolePermission.role_id==rid,RolePermission.permission_id==perm.permission_id)):db.add(RolePermission(role_id=rid,permission_id=perm.permission_id))
    db.commit();monkeypatch.setattr(engine,'_utc_now',lambda:STAMP)
    fee=c.post(PREFIX+'/fees',headers=admin,json={'service_id':str(svc.service_id),'amount':'500.00','effective_from':'2029-01-01'});assert fee.status_code==200,fee.text
    reception=login(users['RECEPTIONIST'].username)
    def visit(**extra):
        p={**visit_payload(),'doctor_id':str(doctor.doctor_id),**extra};r=c.post('/api/v1/visits',headers=reception,json=p);assert r.status_code==200,r.text
        return r.json()
    def decision(v):return c.get(PREFIX+'/visits/'+v['visit_id']+'/decision',headers=reception).json()
    def identity(v):d=decision(v);return {'identity_confirmed':True,'patient_row_version':d['patient_row_version']}
    def draft(v):
        r=c.post(PREFIX+'/bills/from-visit',headers=reception,json={'visit_id':v['visit_id'],**identity(v)});assert r.status_code==200,r.text
        return r.json()
    def finalize(v):
        b=draft(v);r=c.post(PREFIX+'/bills/'+b['consultation_bill_id']+'/finalize',headers=reception,json={'expected_row_version':b['row_version']});assert r.status_code==200,r.text
        return r.json()
    def payment(v,amount='500.00',**extra):
        d=decision(v);mode=db.scalar(select(PaymentMode).where(PaymentMode.code=='CASH'))
        return {'consultation_bill_id':d['bill_id'],'branch_id':str(branches[0].branch_id),'payment_mode_id':str(mode.payment_mode_id),'amount':amount,'payment_request_id':str(uuid.uuid4()),'expected_bill_row_version':d['bill_row_version'],**identity(v),**extra}
    return data,reception,visit,decision,draft,finalize,payment,svc,doctor,patient


def test_paid_partial_retry_receipts_and_report(finance):
    (c,db,branches,users,admin,login),reception,visit,decision,draft,finalize,payment,svc,doctor,patient=finance
    v=visit();assert decision(v)['status']=='PAID_CONSULTATION_REQUIRED'
    b=draft(v);assert draft(v)['consultation_bill_id']==b['consultation_bill_id']
    b=finalize(v);url=PREFIX+'/bills/'+b['consultation_bill_id']+'/finalize'
    assert c.post(url,headers=reception,json={'expected_row_version':1}).json()['bill_number']==b['bill_number']
    p=payment(v,'200.00');r=c.post(PREFIX+'/payments',headers=reception,json=p);assert r.status_code==200,r.text
    first=r.json();assert first['receipt_number'] and first['received_at'].startswith('2030-01-08')
    assert c.post(PREFIX+'/payments',headers=reception,json=p).json()['payment_id']==first['payment_id']
    assert c.post(PREFIX+'/payments',headers=reception,json={**p,'amount':'100.00'}).status_code==409
    assert c.post(PREFIX+'/payments',headers=reception,json={**p,'payment_request_id':str(uuid.uuid4())}).status_code==409
    d=decision(v);assert Decimal(d['balance'])==300 and d['status']=='BILL_PARTIALLY_PAID'
    assert c.post(PREFIX+'/payments',headers=reception,json=payment(v,'300.01')).status_code==409
    r=c.post(PREFIX+'/payments',headers=reception,json=payment(v,'300.00'));assert r.status_code==200,r.text
    second=r.json();assert second['receipt_number']!=first['receipt_number']
    assert decision(v)['status']=='CLEARED' and len(decision(v)['payments'])==2
    assert db.scalar(select(func.count()).select_from(FollowupEntitlement).where(FollowupEntitlement.source_bill_id==uuid.UUID(b['consultation_bill_id'])))==1
    doc=c.get(PREFIX+'/payments/'+first['payment_id']+'/document',headers=reception).json();assert doc['receipt_number']==first['receipt_number'] and Decimal(doc['payment']['amount'])==200
    report=c.get(PREFIX+'/reports/daily?on_date=2030-01-08',headers=reception).json();assert Decimal(report['cash'])==500 and report['paid_consultations']==1
    assert c.post(PREFIX+'/bills/'+b['consultation_bill_id']+'/void',headers=admin,json={'expected_row_version':decision(v)['bill_row_version'],'reason':'Attempt paid void'}).status_code==409


def test_validation_identity_permissions_and_tenant_boundaries(finance):
    (c,db,branches,users,admin,login),reception,visit,decision,draft,finalize,payment,svc,doctor,patient=finance
    v=visit();p={'visit_id':v['visit_id'],'identity_confirmed':False,'patient_row_version':1}
    assert c.post(PREFIX+'/bills/from-visit',headers=reception,json=p).status_code==409
    assert c.post(PREFIX+'/bills/from-visit',headers=reception,json={**p,'identity_confirmed':True,'patient_row_version':999}).status_code==409
    b=finalize(v);p=payment(v)
    for extra in ({'amount':'0'},{'amount':'1.001'},{'amount':'NaN'},{'received_at':'2000-01-01T00:00:00Z'},{'payment_request_id':None}):assert c.post(PREFIX+'/payments',headers=reception,json={**p,**extra}).status_code==422
    assert c.post(PREFIX+'/payments',headers=reception,json={**p,'identity_confirmed':False}).status_code==409
    assert c.post(PREFIX+'/payments',headers=login(users['DOCTOR'].username),json=p).status_code==403
    assert c.get(PREFIX+'/reports/daily').status_code==401
    assert c.post(PREFIX+'/fees',headers=reception,json={'service_id':str(svc.service_id),'amount':'1','effective_from':'2029-01-01'}).status_code==403
    # Same org, different branch is still inaccessible to the Reception user.
    bill=db.get(ConsultationBill,uuid.UUID(b['consultation_bill_id']));bill.branch_id=branches[1].branch_id;db.commit()
    assert c.post(PREFIX+'/payments',headers=reception,json=p).status_code==403
    assert c.get(PREFIX+'/bills/'+b['consultation_bill_id']+'/document',headers=reception).status_code==403
    # A user without finance permission cannot read internal collections.
    viewer=users['RECEPTIONIST'];rid=db.scalar(select(UserRole.role_id).where(UserRole.user_id==viewer.user_id));perm=db.scalar(select(Permission).where(Permission.code=='CONSULTATION_FINANCE_VIEW'));link=db.scalar(select(RolePermission).where(RolePermission.role_id==rid,RolePermission.permission_id==perm.permission_id));db.delete(link);db.commit()
    assert c.get(PREFIX+'/setup',headers=reception).status_code==403


def test_free_followup_once_and_wrong_patient_protection(finance,monkeypatch):
    (c,db,branches,users,admin,login),reception,visit,decision,draft,finalize,payment,svc,doctor,patient=finance
    source=visit();b=finalize(source);assert c.post(PREFIX+'/payments',headers=reception,json=payment(source)).status_code==200
    from app.services import visits
    monkeypatch.setattr(visits,'now',lambda:STAMP+timedelta(days=1));monkeypatch.setattr(engine,'_utc_now',lambda:STAMP+timedelta(days=1))
    follow=visit(chief_complaint_ids=[]);d=decision(follow);assert d['status']=='FREE_FOLLOWUP_ELIGIBLE'
    assert c.post(PREFIX+'/bills/from-visit',headers=reception,json={'visit_id':follow['visit_id'],'identity_confirmed':True,'patient_row_version':d['patient_row_version']}).status_code==409
    p={'entitlement_id':d['entitlement_id'],'identity_confirmed':True,'patient_row_version':d['patient_row_version']};url=PREFIX+'/visits/'+follow['visit_id']+'/free-followup'
    r=c.post(url,headers=reception,json=p);assert r.status_code==200,r.text
    assert c.post(url,headers=reception,json=p).json()['clearance_id']==r.json()['clearance_id']
    next_visit=visit();assert decision(next_visit)['status']=='PAID_CONSULTATION_REQUIRED'
    assert c.post(PREFIX+'/visits/'+next_visit['visit_id']+'/free-followup',headers=reception,json=p).status_code==409
    assert db.scalar(select(func.count()).select_from(EntitlementUsage).where(EntitlementUsage.visit_id==uuid.UUID(follow['visit_id'])))==1
    assert db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action=='FREE_FOLLOWUP_USED',AuditEvent.entity_id==uuid.UUID(follow['visit_id'])))==1
    ent=db.get(FollowupEntitlement,uuid.UUID(d['entitlement_id']));assert ent.max_uses==1
    with pytest.raises(ValueError,match='different Patient'):
        engine.consume_entitlement(db,entitlement_id=ent.entitlement_id,visit_id=uuid.uuid4(),at=STAMP+timedelta(days=1))


def test_fee_versions_policy_and_doctor_complimentary(finance):
    (c,db,branches,users,admin,login),reception,visit,decision,draft,finalize,payment,svc,doctor,patient=finance
    v=visit();b=finalize(v)
    changed=c.post(PREFIX+'/fees',headers=admin,json={'service_id':str(svc.service_id),'amount':'650.00','effective_from':'2030-01-01'});assert changed.status_code==200
    assert Decimal(decision(v)['amount'])==500
    another=visit();assert Decimal(decision(another)['amount'])==650
    assert c.post(PREFIX+'/complimentary',headers=reception,json={'visit_id':another['visit_id']}).status_code==403
    doc=login(users['DOCTOR'].username)
    r=c.post(PREFIX+'/complimentary',headers=doc,json={'visit_id':another['visit_id']});assert r.status_code==200,r.text
    assert decision(another)['clearance_type']=='COMPLIMENTARY'
    assert c.post(PREFIX+'/complimentary',headers=doc,json={'visit_id':v['visit_id']}).status_code==409
    assert c.post(PREFIX+'/policies',headers=admin,json={'name':'New clinic policy','free_followup_window_days':7,'max_free_followups':2,'effective_from':'2030-01-01'}).status_code==200
    selected=engine._active_policy(db,on_date=date(2030,1,8),organization_id=users['ADMIN'].organization_id);assert selected.free_followup_window_days==7 and selected.max_free_followups==2
    assert c.post(PREFIX+'/policies',headers=reception,json={'name':'Blocked change','free_followup_window_days':1,'max_free_followups':9,'effective_from':'2030-01-01'}).status_code==403


def test_payment_failure_rolls_back_receipt_counter_and_clearance(finance,monkeypatch):
    (c,db,branches,users,admin,login),reception,visit,decision,draft,finalize,payment,svc,doctor,patient=finance
    v=visit();b=finalize(v);p=payment(v)
    original=engine.log_audit
    def fail(*a,**kw):raise RuntimeError('Injected financial failure')
    monkeypatch.setattr(engine,'log_audit',fail)
    assert c.post(PREFIX+'/payments',headers=reception,json=p).status_code==409
    assert not db.scalar(select(ConsultationPayment).where(ConsultationPayment.consultation_bill_id==uuid.UUID(b['consultation_bill_id'])))
    assert not db.scalar(select(ConsultationClearance).where(ConsultationClearance.visit_id==uuid.UUID(v['visit_id'])))
    monkeypatch.setattr(engine,'log_audit',original)
    r=c.post(PREFIX+'/payments',headers=reception,json=p);assert r.status_code==200,r.text
    assert r.json()['receipt_number'].endswith('/000001')


def race(db,users,fn):
    barrier=Barrier(2)
    def run(i):
        with Session(db.bind,expire_on_commit=False) as local:
            actor=local.get(User,users[i]);barrier.wait(timeout=15)
            try:return fn(local,actor,i)
            except ValueError:return 'CONFLICT'
    with ThreadPoolExecutor(2) as pool:return list(pool.map(run,range(2)))


def test_postgres_payment_retry_and_same_bill_concurrent_writers(finance):
    (c,db,branches,users,admin,login),reception,visit,decision,draft,finalize,payment,svc,doctor,patient=finance
    if db.bind.dialect.name!='postgresql':pytest.skip('Real PostgreSQL row locks required')
    v=visit();b=finalize(v);p=payment(v);uid=users['RECEPTIONIST'].user_id
    def send(local,actor,i):
        out=engine.record_payment(local,payload=ConsultationPaymentCreate(**p),actor_user_id=actor.user_id,organization_id=actor.organization_id);local.commit();return str(out.payment_id)
    ids=race(db,[uid,uid],send);assert ids[0]==ids[1] and ids[0]!='CONFLICT'
    v=visit();b=finalize(v);p=payment(v,'300.00')
    def collect(local,actor,i):
        out=engine.record_payment(local,payload=ConsultationPaymentCreate(**{**p,'payment_request_id':str(uuid.uuid4())}),actor_user_id=actor.user_id,organization_id=actor.organization_id);local.commit();return str(out.payment_id)
    ids=race(db,[uid,users['ADMIN'].user_id],collect);assert ids.count('CONFLICT')==1


def test_postgres_followup_race_and_bill_number_uniqueness(finance,monkeypatch):
    (c,db,branches,users,admin,login),reception,visit,decision,draft,finalize,payment,svc,doctor,patient=finance
    if db.bind.dialect.name!='postgresql':pytest.skip('Real PostgreSQL row locks required')
    # Draft two encounters before either payment; numbered finalization stays unique.
    a=visit();b=visit();bills=[draft(a),draft(b)];uid=users['ADMIN'].user_id
    def final(local,actor,i):
        bill=local.get(ConsultationBill,uuid.UUID(bills[i]['consultation_bill_id']));out=engine.finalize_bill(local,bill=bill,organization_id=actor.organization_id,fiscal_year='arbitrary',actor_user_id=actor.user_id);local.commit();return out.bill_number
    numbers=race(db,[uid,uid],final);assert len(set(numbers))==2 and 'CONFLICT' not in numbers
    assert c.post(PREFIX+'/payments',headers=reception,json=payment(a)).status_code==200
    from app.services import visits
    monkeypatch.setattr(visits,'now',lambda:STAMP+timedelta(days=1));monkeypatch.setattr(engine,'_utc_now',lambda:STAMP+timedelta(days=1))
    targets=[visit(),visit()];ent=decision(targets[0])['entitlement_id']
    def free(local,actor,i):
        out=engine.create_free_followup_clearance(local,visit_id=uuid.UUID(targets[i]['visit_id']),patient_id=uuid.UUID(patient['patient_id']),entitlement_id=uuid.UUID(ent));local.commit();return str(out.clearance_id)
    ids=race(db,[uid,users['RECEPTIONIST'].user_id],free);assert ids.count('CONFLICT')==1


def test_unassigned_doctor_requires_version_and_locks_after_billing(finance):
    (c,db,branches,users,admin,login),reception,visit,decision,draft,finalize,payment,svc,doctor,patient=finance
    p=db.scalar(select(Permission).where(Permission.code=='VISIT_EDIT'))
    if not p:p=Permission(code='VISIT_EDIT',name='Edit Visit');db.add(p);db.flush()
    rid=db.scalar(select(UserRole.role_id).where(UserRole.user_id==users['RECEPTIONIST'].user_id));db.add(RolePermission(role_id=rid,permission_id=p.permission_id));db.commit()
    v=visit(doctor_id=None);url='/api/v1/visits/'+v['visit_id']+'/doctor'
    payload={'doctor_id':str(doctor.doctor_id),'row_version':999,'reason':'Consulting Doctor verified'}
    assert c.patch(url,headers=reception,json=payload).status_code==409
    payload['row_version']=v['row_version'];r=c.patch(url,headers=reception,json=payload);assert r.status_code==200,r.text
    updated=r.json();assert updated['doctor_id']==str(doctor.doctor_id)
    draft(updated)
    assert c.patch(url,headers=reception,json={**payload,'row_version':updated['row_version']}).status_code==409
