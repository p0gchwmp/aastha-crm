"""Assigned Assistant observations and explicit Doctor review, never a prescription."""
import hashlib
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.access import allowed_branch_ids, ensure_branch_access
from app.core.permissions import require_permission
from app.models.core import Doctor, User
from app.models.patient import Patient
from app.models.clinical import Visit, VisitStatus, VisitType
from app.models.preparation import ClinicalPreparation, PreparationRevision
from app.api.routes.visits import _serialize, _local_bounds
from app.api.routes.doctor_consultations import context as doctor_context
from app.services.audit import log_audit

router=APIRouter(prefix="/clinical-preparations",tags=["clinical-preparations"])
TEXT_FIELDS=("history","allergies","current_medicines","observations")
VALUE_FIELDS=("weight_kg","height_cm","systolic","diastolic","pulse","respiratory_rate","spo2","temperature_c")
FIELDS=(*TEXT_FIELDS,"allergy_status",*VALUE_FIELDS)


class Request(BaseModel):
    model_config=ConfigDict(extra="forbid",allow_inf_nan=False)
    request_id: uuid.UUID
    row_version: int = Field(ge=0)


class ReturnRequest(Request):
    reason: str = Field(min_length=3,max_length=1000)


class Assignment(Request):
    assistant_user_id: uuid.UUID
    reason: str = Field(min_length=3,max_length=500)


class Draft(Request):
    identity_confirmed: bool
    patient_version: int = Field(ge=1)
    history: str | None = Field(default=None,max_length=10000)
    allergy_status: Literal["UNKNOWN","NONE_REPORTED","REPORTED"] = "UNKNOWN"
    allergies: str | None = Field(default=None,max_length=5000)
    current_medicines: str | None = Field(default=None,max_length=10000)
    observations: str | None = Field(default=None,max_length=10000)
    weight_kg: Decimal | None = Field(default=None,gt=0,le=1000,max_digits=6,decimal_places=2)
    height_cm: Decimal | None = Field(default=None,gt=0,le=400,max_digits=6,decimal_places=2)
    systolic: int | None = Field(default=None,gt=0,le=400)
    diastolic: int | None = Field(default=None,gt=0,le=300)
    pulse: int | None = Field(default=None,gt=0,le=400)
    respiratory_rate: int | None = Field(default=None,gt=0,le=150)
    spo2: Decimal | None = Field(default=None,ge=0,le=100,max_digits=5,decimal_places=2)
    temperature_c: Decimal | None = Field(default=None,ge=20,le=50,max_digits=4,decimal_places=1)

    @model_validator(mode="after")
    def consistent(self):
        if (self.systolic is None)!=(self.diastolic is None): raise ValueError("Enter both blood-pressure values or neither")
        if self.systolic is not None and self.systolic<self.diastolic: raise ValueError("Review blood-pressure values")
        if self.allergy_status=="REPORTED" and not (self.allergies or "").strip(): raise ValueError("Record the reported allergies")
        if self.allergy_status!="REPORTED" and (self.allergies or "").strip(): raise ValueError("Choose Reported to record allergy details")
        return self


def permission(db,user,code):
    try: require_permission(code)(user,db); return True
    except HTTPException: return False


def visit_context(db,user,visit_id,lock=False):
    initial=db.get(Visit,visit_id)
    if not initial: raise HTTPException(404,"Visit not found")
    stmt=select(Patient).where(Patient.patient_id==initial.patient_id).execution_options(populate_existing=True)
    patient=db.scalar(stmt.with_for_update() if lock else stmt)
    if not patient or patient.organization_id!=user.organization_id: raise HTTPException(404,"Visit not found")
    ensure_branch_access(db,user,initial.branch_id)
    stmt=select(Visit).where(Visit.visit_id==visit_id).execution_options(populate_existing=True)
    visit=db.scalar(stmt.with_for_update() if lock else stmt)
    if db.get(VisitType,visit.visit_type_id).code=="PROCEDURE": raise HTTPException(409,"Procedure Visits use their existing session workflow")
    return visit,patient


def get_preparation(db,visit_id,lock=False):
    stmt=select(ClinicalPreparation).where(ClinicalPreparation.visit_id==visit_id).execution_options(populate_existing=True)
    return db.scalar(stmt.with_for_update() if lock else stmt)


def snapshot(db,p):
    if not p: return None
    assistant=db.get(User,p.assistant_user_id)
    return {"preparation_id":str(p.preparation_id),"assistant_user_id":str(p.assistant_user_id),"assistant_name":assistant.name if assistant else None,"state":p.state,"return_note":p.return_note,"updated_at":p.updated_at.isoformat() if p.updated_at else None,"row_version":p.row_version,"submitted_at":p.submitted_at.isoformat() if p.submitted_at else None,"reviewed_at":p.reviewed_at.isoformat() if p.reviewed_at else None,"reviewed_by_doctor_id":str(p.reviewed_by_doctor_id) if p.reviewed_by_doctor_id else None,**{k:str(getattr(p,k)) if isinstance(getattr(p,k),Decimal) else getattr(p,k) for k in FIELDS}}


def revision(db,p,user,payload,action,visit_id):
    digest=hashlib.sha256((str(visit_id)+action+payload.model_dump_json()).encode()).hexdigest()
    old=db.scalar(select(PreparationRevision).where(PreparationRevision.actor_user_id==user.user_id,PreparationRevision.request_id==payload.request_id))
    if old:
        if old.request_hash!=digest: raise HTTPException(409,"Request identifier already used for different data")
        return True,digest
    return False,digest


def record(db,p,user,payload,action,digest):
    db.add(PreparationRevision(preparation_id=p.preparation_id,actor_user_id=user.user_id,request_id=payload.request_id,request_hash=digest,action=action,occurred_at=datetime.now(timezone.utc),snapshot={**snapshot(db,p),"action_reason":getattr(payload,"reason",None),"identity_patient_version":getattr(payload,"patient_version",None)}))
    log_audit(db,organization_id=user.organization_id,entity_type="VISIT",entity_id=p.visit_id,action="ASSISTANT_"+action,actor_user_id=user.user_id,after_data={"preparation_id":str(p.preparation_id),"version":p.row_version,"state":p.state})


def eligible(db,user,branch):
    return user and user.status=="ACTIVE" and permission(db,user,"CLINICAL_PREPARATION") and (allowed_branch_ids(db,user) is None or branch in allowed_branch_ids(db,user))


def assigner(db,user,visit):
    if not permission(db,user,"CLINICAL_TEAM_MANAGE"):
        doctor_context(db,user,visit.visit_id)


@router.get("/assignments")
def assignments(on_date:date,offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),db:Session=Depends(get_db),user:User=Depends(require_permission("CLINICAL_ASSIGN"))):
    start,end=_local_bounds(on_date)
    stmt=select(Visit).join(Patient).join(VisitType).join(VisitStatus).where(Patient.organization_id==user.organization_id,VisitType.code!="PROCEDURE",VisitStatus.code.in_(["CREATED","WAITING","IN_PROGRESS"]),Visit.checkin_at.between(start,end))
    if not permission(db,user,"CLINICAL_TEAM_MANAGE"):
        from app.api.routes.doctor_consultations import doctor_for
        stmt=stmt.where(Visit.doctor_id==doctor_for(db,user).doctor_id)
    allowed=allowed_branch_ids(db,user)
    if allowed is not None: stmt=stmt.where(Visit.branch_id.in_(allowed))
    rows=[]
    candidates=db.scalars(select(User).where(User.organization_id==user.organization_id,User.status=="ACTIVE")).all()
    for v in db.scalars(stmt.order_by(Visit.checkin_at,Visit.visit_id).offset(offset).limit(limit)).all():
        p=get_preparation(db,v.visit_id)
        rows.append({"visit":_serialize(db,v),"assignment":{"assistant_name":db.get(User,p.assistant_user_id).name,"assistant_user_id":str(p.assistant_user_id),"row_version":p.row_version,"state":p.state} if p else None,"assistants":[{"user_id":str(a.user_id),"name":a.name} for a in candidates if eligible(db,a,v.branch_id)]})
    return rows


@router.post("/{visit_id}/assign")
def assign(visit_id:uuid.UUID,payload:Assignment,db:Session=Depends(get_db),user:User=Depends(require_permission("CLINICAL_ASSIGN"))):
    try:
        visit,_=visit_context(db,user,visit_id,True); assigner(db,user,visit)
        if db.get(VisitStatus,visit.visit_status_id).code not in {"CREATED","WAITING","IN_PROGRESS"}: raise HTTPException(409,"Visit is closed")
        doctor = db.get(Doctor, visit.doctor_id) if visit.doctor_id else None
        if not doctor or not doctor.active or doctor.organization_id != user.organization_id:
            raise HTTPException(409,"Assign an active Doctor to the Visit before assigning an Assistant")
        from app.services.clinical_team import ensure_doctor_branch
        ensure_doctor_branch(db,doctor,visit.branch_id)
        p=get_preparation(db,visit_id,True)
        repeated,digest=revision(db,p,user,payload,"ASSIGNED",visit_id)
        if repeated: return {"state":p.state,"return_note":p.return_note,"updated_at":p.updated_at.isoformat() if p.updated_at else None,"row_version":p.row_version}
        if payload.row_version!=(p.row_version if p else 0): raise HTTPException(409,"Assignment changed. Refresh before saving")
        assistant=db.get(User,payload.assistant_user_id)
        if not assistant or assistant.organization_id!=user.organization_id or not eligible(db,assistant,visit.branch_id): raise HTTPException(422,"Select an active Assistant with access to this branch")
        if not payload.reason.strip(): raise HTTPException(422,"Assignment reason is required")
        if p:
            if p.state=="REVIEWED": raise HTTPException(409,"Reviewed preparation cannot be reassigned")
            for key in FIELDS: setattr(p,key,"UNKNOWN" if key=="allergy_status" else None)
            p.assistant_user_id=assistant.user_id;p.assigned_by=user.user_id;p.return_note=None;p.state="ASSIGNED";p.submitted_at=None;p.row_version+=1
        else:
            p=ClinicalPreparation(visit_id=visit_id,assistant_user_id=assistant.user_id,assigned_by=user.user_id);db.add(p)
        visit.row_version+=1;db.flush();record(db,p,user,payload,"ASSIGNED",digest);db.commit()
        return {"state":p.state,"return_note":p.return_note,"updated_at":p.updated_at.isoformat() if p.updated_at else None,"row_version":p.row_version}
    except Exception as exc:
        db.rollback()
        if isinstance(exc,IntegrityError):raise HTTPException(409,"Assignment conflicted. Refresh and review") from exc
        raise


@router.get("")
def queue(on_date:date,offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=100),db:Session=Depends(get_db),user:User=Depends(require_permission("CLINICAL_PREPARATION"))):
    start,end=_local_bounds(on_date)
    stmt=select(Visit).join(ClinicalPreparation).join(Patient).where(ClinicalPreparation.assistant_user_id==user.user_id,Patient.organization_id==user.organization_id,Visit.checkin_at.between(start,end))
    allowed=allowed_branch_ids(db,user)
    if allowed is not None:stmt=stmt.where(Visit.branch_id.in_(allowed))
    return [{"visit":_serialize(db,v),"preparation":snapshot(db,get_preparation(db,v.visit_id))} for v in db.scalars(stmt.order_by(Visit.checkin_at,Visit.visit_id).offset(offset).limit(limit)).all()]


@router.get("/{visit_id}")
def detail(visit_id:uuid.UUID,db:Session=Depends(get_db),user:User=Depends(require_permission("CLINICAL_PREPARATION"))):
    visit,patient=visit_context(db,user,visit_id);p=get_preparation(db,visit_id)
    if not p or p.assistant_user_id!=user.user_id: raise HTTPException(403,"Visit is not assigned to you")
    return {"visit":_serialize(db,visit),"patient":{"full_name":patient.full_name,"uhid":patient.uhid,"age_years":patient.age_years,"age_recorded_on":patient.age_recorded_on,"dob":patient.dob,"gender":patient.gender,"row_version":patient.row_version},"preparation":snapshot(db,p)}


@router.post("/{visit_id}/{action}")
def write(visit_id:uuid.UUID,action:str,payload:Draft,db:Session=Depends(get_db),user:User=Depends(require_permission("CLINICAL_PREPARATION"))):
    if action not in {"save","submit"}:raise HTTPException(404,"Unknown preparation action")
    try:
        visit,patient=visit_context(db,user,visit_id,True);p=get_preparation(db,visit_id,True)
        if not p or p.assistant_user_id!=user.user_id:raise HTTPException(403,"Visit is not assigned to you")
        repeated,digest=revision(db,p,user,payload,action.upper(),visit_id)
        if repeated:return snapshot(db,p)
        if p.row_version!=payload.row_version:raise HTTPException(409,"Preparation changed. Refresh before saving")
        if p.state not in {"ASSIGNED","DRAFT"}:raise HTTPException(409,"Submitted or reviewed preparation is read-only")
        if db.get(VisitStatus,visit.visit_status_id).code not in {"CREATED","WAITING","IN_PROGRESS"}:raise HTTPException(409,"Visit is closed")
        if not payload.identity_confirmed or patient.row_version!=payload.patient_version:raise HTTPException(409,"Confirm current Patient Name, Age/Gender and UHID")
        for key in FIELDS:setattr(p,key,getattr(payload,key))
        p.state="SUBMITTED" if action=="submit" else "DRAFT";p.row_version+=1
        if action=="submit":p.submitted_at=datetime.now(timezone.utc)
        db.flush();record(db,p,user,payload,action.upper(),digest);db.commit();return snapshot(db,p)
    except Exception as exc:
        db.rollback()
        if isinstance(exc,IntegrityError):raise HTTPException(409,"Preparation conflicted. Refresh and review") from exc
        raise


def review(visit_id,payload,db,user):
    try:
        visit,_,doctor=doctor_context(db,user,visit_id,True);p=get_preparation(db,visit_id,True)
        if not p:raise HTTPException(404,"Preparation not found")
        repeated,digest=revision(db,p,user,payload,"REVIEWED",visit_id)
        if repeated:return snapshot(db,p)
        if p.row_version!=payload.row_version:raise HTTPException(409,"Preparation changed. Review the current version")
        if p.state!="SUBMITTED" or db.get(VisitStatus,visit.visit_status_id).code!="IN_PROGRESS":raise HTTPException(409,"Start the consultation and review submitted preparation")
        p.state="REVIEWED";p.row_version+=1;p.reviewed_by_doctor_id=doctor.doctor_id;p.reviewed_at=datetime.now(timezone.utc);visit.row_version+=1
        db.flush();record(db,p,user,payload,"REVIEWED",digest);db.commit();return snapshot(db,p)
    except Exception:
        db.rollback();raise


def return_for_changes(visit_id,payload,db,user):
    try:
        visit,_,_=doctor_context(db,user,visit_id,True);p=get_preparation(db,visit_id,True)
        if not p:raise HTTPException(404,"Preparation not found")
        repeated,digest=revision(db,p,user,payload,"RETURNED",visit_id)
        if repeated:return snapshot(db,p)
        if p.row_version!=payload.row_version:raise HTTPException(409,"Preparation changed. Refresh before returning")
        if p.state!="SUBMITTED" or db.get(VisitStatus,visit.visit_status_id).code not in {"CREATED","WAITING","IN_PROGRESS"}:raise HTTPException(409,"Only submitted preparation for an open Visit can be returned")
        if not payload.reason.strip():raise HTTPException(422,"A correction reason is required")
        p.state="DRAFT";p.return_note=payload.reason.strip();p.row_version+=1;p.submitted_at=None;visit.row_version+=1
        db.flush();record(db,p,user,payload,"RETURNED",digest);db.commit();return snapshot(db,p)
    except Exception:
        db.rollback();raise
