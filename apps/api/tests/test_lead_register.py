"""Module 2 HTTP regression tests, also run against PostgreSQL in CI."""
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select, func
from test_staff_access import clinic
from app.models import Base
from app.models.core import Permission, RolePermission, UserRole
from app.models.crm import Lead, LeadSource, LeadStatus, LostReason, LeadContact, LeadInteraction, LeadStatusHistory, LeadDncHistory, LeadExternalAssignment, ExternalPartner
from app.models.patient import Patient
from app.models.integration import AuditEvent

@pytest.fixture
def leads(clinic):
    c, db, branches, users, admin, login = clinic
    if db.bind.dialect.name == "sqlite":
        Base.metadata.create_all(db.bind, tables=[m.__table__ for m in (LeadSource,LeadStatus,LostReason,Lead,LeadContact,LeadInteraction,LeadStatusHistory,LeadDncHistory,ExternalPartner,LeadExternalAssignment,Patient)])
    for code in ("LEAD_CREATE","LEAD_VIEW","LEAD_EDIT","LEAD_EXTERNAL_ASSIGN"):
        p=db.scalar(select(Permission).where(Permission.code==code))
        if not p:
            p=Permission(code=code,name=code);db.add(p);db.flush()
        for user in (users["ADMIN"],users["RECEPTIONIST"]):
            role=db.scalar(select(UserRole.role_id).where(UserRole.user_id==user.user_id))
            if not db.scalar(select(RolePermission).where(RolePermission.role_id==role,RolePermission.permission_id==p.permission_id)):
                db.add(RolePermission(role_id=role,permission_id=p.permission_id))
    def master(model,code):
        row=db.scalar(select(model).where(model.code==code))
        if not row:
            row=model(code=code,name=code);db.add(row);db.flush()
        return row
    source=master(LeadSource,"TEST_SOURCE")
    statuses={code:master(LeadStatus,code) for code in ("NEW","FOLLOW_UP_REQUIRED","LOST","CONVERTED","NO_SHOW","SPAM_FAKE")}
    lost=master(LostReason,"TEST_LOST");db.commit()
    def create(branch=0,**extra):
        payload={"organization_id":str(users["ADMIN"].organization_id),"lead_name":"Fictional Lead","mobile":"9876543210","lead_source_id":str(source.lead_source_id),"lead_status_id":str(statuses["NEW"].lead_status_id),"preferred_branch_id":str(branches[branch].branch_id)}
        return c.post("/api/v1/leads",headers=admin,json={**payload,**extra})
    yield clinic,create,statuses,lost


def test_lead_shared_mobile_edit_followup_lost_reopen_history(leads):
    (c,db,branches,users,admin,login),create,statuses,lost=leads
    before=db.scalar(select(func.count()).select_from(Patient))
    first=create();assert first.status_code==200,first.text
    lid=first.json()["lead_id"];url=f"/api/v1/leads/{lid}"
    assert create(lead_name="Different inquiry",concern_text="Hair fall").status_code==200
    assert len(c.get("/api/v1/leads/search?mobile=9876543210",headers=admin).json())>=2
    row=c.get(url,headers=admin).json()
    edit={"lead_name":"Corrected Name","mobile":"+91 91234 56789","lead_owner_user_id":str(users["RECEPTIONIST"].user_id),"row_version":row["row_version"]}
    r=c.patch(url,headers=admin,json=edit);assert r.status_code==200,r.text
    assert c.patch(url,headers=admin,json=edit).status_code==409
    row=c.get(url,headers=admin).json();assert row["owner_name"]=="RECEPTIONIST"
    when=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    r=c.post(url+"/interactions",headers=admin,json={"interaction_type":"FOLLOW_UP","summary":"Call requested tomorrow","next_followup_at":when,"row_version":row["row_version"]});assert r.status_code==200,r.text
    row=c.get(url,headers=admin).json();assert row["status_code"]=="FOLLOW_UP_REQUIRED"
    assert c.post(url+"/interactions",headers=admin,json={"interaction_type":"NOTE","summary":"Internal note","row_version":row["row_version"]}).status_code==200
    row=c.get(url,headers=admin).json();assert row["next_followup_at"] is not None
    r=c.patch(url,headers=admin,json={"lead_status_id":str(statuses["LOST"].lead_status_id),"lost_reason_id":str(lost.lost_reason_id),"row_version":row["row_version"]});assert r.status_code==200,r.text
    row=c.get(url,headers=admin).json();assert row["next_followup_at"] is None
    assert c.post(url+"/reopen",headers=admin,json={"row_version":row["row_version"]}).status_code==200
    row=c.get(url,headers=admin).json();assert row["status_code"]=="FOLLOW_UP_REQUIRED" and len(row["interactions"])==2
    assert {x["code"] for x in row["status_history"]}>={"NEW","FOLLOW_UP_REQUIRED","LOST"}
    assert db.scalar(select(func.count()).select_from(Patient))==before
    audit=db.scalar(select(AuditEvent).where(AuditEvent.entity_id==uuid.UUID(lid),AuditEvent.action=="LEAD_UPDATED"))
    assert audit.before_data["lead_name"]=="Fictional Lead"


def test_dnc_outbound_denied_inbound_allowed(leads):
    (c,db,branches,users,admin,login),create,statuses,lost=leads
    lid=create().json()["lead_id"];url=f"/api/v1/leads/{lid}"
    partner=ExternalPartner(partner_name="Fictional calling partner",partner_type="CALLING")
    db.add(partner);db.flush()
    assignment=LeadExternalAssignment(lead_id=uuid.UUID(lid),partner_id=partner.partner_id,assigned_by=users["ADMIN"].user_id,status="ACTIVE")
    db.add(assignment)
    lead=db.get(Lead,uuid.UUID(lid));lead.next_followup_at=datetime.now(timezone.utc)+timedelta(days=1)
    db.commit()
    row=c.get(url,headers=admin).json()
    assert c.post(url+"/dnc",headers=admin,json={"dnc":True,"reason":"No promotional contact requested","row_version":row["row_version"]}).status_code==200
    row=c.get(url,headers=admin).json();assert row["dnc"] is True and len(row["dnc_history"])==1
    assert row["next_followup_at"] is None
    db.refresh(assignment);assert assignment.status=="REVOKED" and assignment.row_version==2
    for kind in ("OUTBOUND_CALL","OUTBOUND_WHATSAPP","FOLLOW_UP"):
        assert c.post(url+"/interactions",headers=admin,json={"interaction_type":kind,"summary":"Attempt outbound","row_version":row["row_version"]}).status_code==409
    for kind in ("INBOUND_CALL","NOTE"):
        row=c.get(url,headers=admin).json()
        assert c.post(url+"/interactions",headers=admin,json={"interaction_type":kind,"summary":"Inbound or internal","row_version":row["row_version"]}).status_code==200
    assert c.post(url+"/interactions",headers=admin,json={"interaction_type":"UNKNOWN"}).status_code==422
    assert c.post(url+"/external-assignments",headers=admin,json={"partner_id":str(uuid.uuid4())}).status_code==409
    row=c.get(url,headers=admin).json()
    assert c.post(url+"/dnc",headers=admin,json={"dnc":False,"reason":"   ","row_version":row["row_version"]}).status_code==422
    assert c.post(url+"/dnc",headers=admin,json={"dnc":False,"reason":"Explicit renewed consent","row_version":row["row_version"]}).status_code==200


def test_lead_branch_and_owner_boundaries(leads):
    (c,db,branches,users,admin,login),create,statuses,lost=leads
    first=create().json();second=create(branch=1,lead_name="Other branch").json()
    reception=login(users["RECEPTIONIST"].username)
    for suffix,method,payload in (("","GET",None),("","PATCH",{"lead_name":"Attack","row_version":1}),("/interactions","POST",{"interaction_type":"NOTE","row_version":1}),("/dnc","POST",{"dnc":True,"reason":"Attempt","row_version":1}),("/reopen","POST",{"row_version":1})):
        r=c.request(method,f"/api/v1/leads/{second['lead_id']}"+suffix,headers=reception,json=payload);assert r.status_code==403,r.text
    rows=c.get("/api/v1/leads/search?mobile=9876543210",headers=reception).json()
    assert second["lead_id"] not in {r["lead_id"] for r in rows}
    assert c.get("/api/v1/leads/search",headers=admin).json()==[]
    url=f"/api/v1/leads/{first['lead_id']}"
    assert c.patch(url,headers=admin,json={"row_version":1,"lead_owner_user_id":str(users["DOCTOR"].user_id)}).status_code==422
    assert c.patch(url,headers=admin,json={"row_version":1,"preferred_branch_id":str(branches[1].branch_id),"lead_owner_user_id":str(users["RECEPTIONIST"].user_id)}).status_code==422
    for extra in ({"lead_name":"   "},{"mobile":"123"},{"lead_source_id":str(uuid.uuid4())},{"age":-1},{"lead_status_id":str(statuses["CONVERTED"].lead_status_id)}):
        r=create(**extra);assert r.status_code==422,r.text
    assert c.patch(url,headers=admin,json={"row_version":1,"lead_status_id":str(statuses["CONVERTED"].lead_status_id)}).status_code==409
    assert c.get("/api/v1/leads").status_code==401
    assert c.get("/api/v1/leads",headers=login(users["DOCTOR"].username)).status_code==403
    ids={x["id"] for x in c.get("/api/v1/leads/owners",headers=admin).json()}
    assert str(users["RECEPTIONIST"].user_id) in ids and str(users["DOCTOR"].user_id) not in ids


def test_dnc_filter_is_independent_of_lifecycle_and_branch_safe(leads):
    (c,db,branches,users,admin,login),create,statuses,lost=leads
    normal=create(lead_name="Normal inquiry").json()
    protected=create(lead_name="DNC inquiry").json()
    other_branch=create(branch=1,lead_name="Other branch DNC").json()
    for row in (protected,other_branch):
        r=c.post(f"/api/v1/leads/{row['lead_id']}/dnc",headers=admin,json={"dnc":True,"reason":"Requested no outbound contact","row_version":row["row_version"]})
        assert r.status_code==200,r.text
    headers=login(users["RECEPTIONIST"].username)
    def ids(query):
        r=c.get("/api/v1/leads?"+query,headers=headers)
        assert r.status_code==200,r.text
        return {row["lead_id"] for row in r.json()}
    assert ids("dnc=true")=={protected["lead_id"]}
    assert ids("dnc=false")=={normal["lead_id"]}
    assert ids("dnc=true&status_code=NEW")=={protected["lead_id"]}
    assert ids("dnc=true&status_code=LOST")==set()
    assert ids("")=={protected["lead_id"],normal["lead_id"]}
    row=c.get(f"/api/v1/leads/{protected['lead_id']}",headers=admin).json()
    assert row["status_code"]=="NEW" and row["dnc"] is True
    assert c.get("/api/v1/leads?dnc=invalid",headers=headers).status_code==422
    for code in ("CONVERTED","NO_SHOW"):
        r=c.patch(f"/api/v1/leads/{normal['lead_id']}",headers=headers,json={"lead_status_id":str(statuses[code].lead_status_id),"row_version":normal["row_version"]})
        assert r.status_code==409,r.text
