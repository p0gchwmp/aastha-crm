"""Structured observations only. No interaction clearance or dosing is inferred."""
import hashlib
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.permissions import current_user
from app.models.core import User
from app.models.clinical import Visit, VisitStatus
from app.models.safety import SafetyAssessment, SafetyEntry, SafetyRevision
from app.api.routes.clinical_preparations import permission, visit_context, get_preparation
from app.api.routes.doctor_consultations import context as doctor_context
from app.core.access import allowed_branch_ids
from app.services.audit import log_audit

router=APIRouter(prefix="/patient-safety",tags=["patient-safety"])
STATUS_FIELDS=("allergy_status","medicine_status","condition_status","pregnancy_status","breastfeeding_status")
ENTRY_FIELDS=("kind","name","reaction","severity","strength","regimen","exposure_status","source","value","unit","observed_on","notes")

def today(): return datetime.now(timezone.utc).astimezone(__import__('zoneinfo').ZoneInfo('Asia/Kolkata')).date()

class Entry(BaseModel):
    model_config=ConfigDict(extra="forbid",str_strip_whitespace=True)
    entry_id: uuid.UUID
    kind: Literal["ALLERGY","MEDICINE","CONDITION","RESULT"]
    name: str=Field(min_length=1,max_length=300)
    reaction: str=Field(default="",max_length=500)
    severity: Literal["UNKNOWN","MILD","MODERATE","SEVERE"]="UNKNOWN"
    strength: str=Field(default="",max_length=240)
    regimen: str=Field(default="",max_length=500)
    exposure_status: Literal["CURRENT","RECENTLY_STOPPED"]="CURRENT"
    source: str=Field(default="",max_length=240)
    value: str=Field(default="",max_length=120)
    unit: str=Field(default="",max_length=80)
    observed_on: date | None=None
    notes: str=Field(default="",max_length=1000)
    @model_validator(mode="after")
    def valid(self):
        if self.observed_on and self.observed_on>today(): raise ValueError("Observation date cannot be in the future")
        if self.kind=="ALLERGY" and not self.reaction: raise ValueError("Record the allergy reaction, or explicitly enter unknown")
        if self.kind=="MEDICINE" and not self.source: raise ValueError("Record the medicine information source")
        if self.kind=="RESULT" and (not self.value or not self.unit or not self.observed_on): raise ValueError("A result needs its value, unit (or not applicable), and sample date")
        return self

class AssessmentInput(BaseModel):
    model_config=ConfigDict(extra="forbid",allow_inf_nan=False)
    request_id: uuid.UUID
    row_version: int=Field(ge=0)
    patient_version: int=Field(ge=1)
    identity_confirmed: bool=False
    doctor_confirmed: bool=False
    allergy_status: Literal["NOT_ASSESSED","NONE_REPORTED","REPORTED"]="NOT_ASSESSED"
    medicine_status: Literal["NOT_ASSESSED","NONE_REPORTED","REPORTED"]="NOT_ASSESSED"
    condition_status: Literal["NOT_ASSESSED","NONE_REPORTED","REPORTED"]="NOT_ASSESSED"
    pregnancy_status: Literal["NOT_ASSESSED","UNKNOWN","NOT_APPLICABLE","NOT_PREGNANT","PREGNANT"]="NOT_ASSESSED"
    breastfeeding_status: Literal["NOT_ASSESSED","UNKNOWN","NOT_APPLICABLE","NO","YES"]="NOT_ASSESSED"
    weight_kg: Decimal | None=Field(default=None,gt=0,le=1000,max_digits=6,decimal_places=2)
    weight_date: date | None=None
    entries: list[Entry]=Field(default_factory=list,max_length=150)
    @model_validator(mode="after")
    def valid(self):
        if (self.weight_kg is None)!=(self.weight_date is None): raise ValueError("Weight requires its measurement date")
        if self.weight_date and self.weight_date>today(): raise ValueError("Weight date cannot be in the future")
        if len({e.entry_id for e in self.entries})!=len(self.entries): raise ValueError("Duplicate entry identifiers")
        for kind,field in (("ALLERGY","allergy_status"),("MEDICINE","medicine_status"),("CONDITION","condition_status")):
            if bool([e for e in self.entries if e.kind==kind])!=(getattr(self,field)=="REPORTED"): raise ValueError(f"{field}: choose Reported and provide entries, or remove the entries")
        return self

def access(db,user,visit_id,lock=False):
    if permission(db,user,"CONSULTATION_CLINICAL"):
        v,p,d=doctor_context(db,user,visit_id,lock);return v,p,d
    if not permission(db,user,"CLINICAL_PREPARATION"): raise HTTPException(403,"Clinical access required")
    v,p=visit_context(db,user,visit_id,lock);prep=get_preparation(db,visit_id,lock)
    if not prep or prep.assistant_user_id!=user.user_id: raise HTTPException(403,"Visit is not assigned to you")
    return v,p,None

def assessment(db,visit_id,lock=False):
    stmt=select(SafetyAssessment).where(SafetyAssessment.visit_id==visit_id).execution_options(populate_existing=True)
    return db.scalar(stmt.with_for_update() if lock else stmt)

def snapshot(db,a):
    if not a:return None
    entries=db.scalars(select(SafetyEntry).where(SafetyEntry.assessment_id==a.assessment_id,SafetyEntry.active.is_(True)).order_by(SafetyEntry.created_at,SafetyEntry.entry_id)).all()
    return {"assessment_id":str(a.assessment_id),"visit_id":str(a.visit_id),"row_version":a.row_version,**{f:getattr(a,f) for f in STATUS_FIELDS},"weight_kg":str(a.weight_kg) if a.weight_kg is not None else None,"weight_date":a.weight_date.isoformat() if a.weight_date else None,"reviewed_at":a.reviewed_at.isoformat() if a.reviewed_at else None,"reviewed_by_doctor_id":str(a.reviewed_by_doctor_id) if a.reviewed_by_doctor_id else None,"recorded_by":str(a.recorded_by),"updated_at":a.updated_at.isoformat(),"entries":[{"entry_id":str(e.entry_id),**{f:getattr(e,f).isoformat() if isinstance(getattr(e,f),date) else getattr(e,f) for f in ENTRY_FIELDS}} for e in entries]}

@router.get("/{visit_id}")
def detail(visit_id:uuid.UUID,db:Session=Depends(get_db),user:User=Depends(current_user)):
    v,p,d=access(db,user,visit_id);a=assessment(db,visit_id)
    previous=None
    # Previous records are Doctor-only historical context, never automatically current.
    if d:
        stmt=select(SafetyAssessment).join(Visit).where(Visit.patient_id==p.patient_id,Visit.visit_id!=visit_id,Visit.checkin_at<=v.checkin_at)
        allowed=allowed_branch_ids(db,user)
        if allowed is not None:stmt=stmt.where(Visit.branch_id.in_(allowed))
        previous=snapshot(db,db.scalar(stmt.order_by(Visit.checkin_at.desc(),SafetyAssessment.updated_at.desc()).limit(1)))
    revisions=db.scalars(select(SafetyRevision).where(SafetyRevision.assessment_id==a.assessment_id).order_by(SafetyRevision.occurred_at)).all() if a and d else []
    status=db.get(VisitStatus,v.visit_status_id).code
    prep=get_preparation(db,visit_id) if not d else None
    editable=status=="IN_PROGRESS" if d else status in {"CREATED","WAITING","IN_PROGRESS"} and prep.state in {"ASSIGNED","DRAFT"} and not (a and a.reviewed_at)
    return {"assessment":snapshot(db,a),"previous":previous,"revisions":[{"occurred_at":r.occurred_at,"snapshot":r.snapshot} for r in revisions],"editable":editable,"can_review":bool(d),"patient_version":p.row_version}

@router.post("/{visit_id}")
def save(visit_id:uuid.UUID,payload:AssessmentInput,db:Session=Depends(get_db),user:User=Depends(current_user)):
    try:
        v,p,d=access(db,user,visit_id,True);a=assessment(db,visit_id,True)
        digest=hashlib.sha256((str(visit_id)+payload.model_dump_json()).encode()).hexdigest()
        old=db.scalar(select(SafetyRevision).where(SafetyRevision.actor_user_id==user.user_id,SafetyRevision.request_id==payload.request_id))
        if old:
            if old.request_hash!=digest:raise HTTPException(409,"Request identifier already used for different data")
            db.commit();return {"assessment":snapshot(db,a)}
        if payload.row_version!=(a.row_version if a else 0):raise HTTPException(409,"Safety record changed. Refresh and review")
        status=db.get(VisitStatus,v.visit_status_id).code
        if d:
            if status!="IN_PROGRESS":raise HTTPException(409,"Start the consultation before recording safety information")
        else:
            prep=get_preparation(db,visit_id,True)
            if status not in {"CREATED","WAITING","IN_PROGRESS"} or prep.state not in {"ASSIGNED","DRAFT"} or (a and a.reviewed_at):raise HTTPException(409,"Safety preparation is read-only")
            if payload.doctor_confirmed:raise HTTPException(403,"Only the assigned Doctor can confirm clinical review")
        if not payload.identity_confirmed or payload.patient_version!=p.row_version:raise HTTPException(409,"Confirm current Patient Name, Age/Gender and UHID")
        if not a:
            a=SafetyAssessment(visit_id=visit_id,recorded_by=user.user_id);db.add(a);db.flush()
        else:a.row_version+=1
        for f in STATUS_FIELDS:setattr(a,f,getattr(payload,f))
        a.weight_kg=payload.weight_kg;a.weight_date=payload.weight_date;a.recorded_by=user.user_id
        a.reviewed_at=datetime.now(timezone.utc) if d and payload.doctor_confirmed else None
        a.reviewed_by_doctor_id=d.doctor_id if d and payload.doctor_confirmed else None
        existing={e.entry_id:e for e in db.scalars(select(SafetyEntry).where(SafetyEntry.assessment_id==a.assessment_id)).all()}
        wanted={e.entry_id for e in payload.entries}
        for e in existing.values():
            if e.entry_id not in wanted and e.active:e.active=False;e.row_version+=1
        for item in payload.entries:
            e=existing.get(item.entry_id)
            if not e:
                if db.get(SafetyEntry,item.entry_id):raise HTTPException(422,"Entry belongs to another safety record")
                e=SafetyEntry(entry_id=item.entry_id,assessment_id=a.assessment_id);db.add(e)
            else:e.row_version+=1
            for f in ENTRY_FIELDS:setattr(e,f,getattr(item,f))
            e.active=True
        # Invalidate concurrent consultation saves; completion captures the current safety version.
        v.row_version+=1;db.flush();data=snapshot(db,a)
        db.add(SafetyRevision(assessment_id=a.assessment_id,actor_user_id=user.user_id,request_id=payload.request_id,request_hash=digest,occurred_at=datetime.now(timezone.utc),snapshot=data))
        log_audit(db,organization_id=user.organization_id,entity_type="VISIT",entity_id=visit_id,action="SAFETY_REVIEW" if a.reviewed_at else "SAFETY_SAVE",actor_user_id=user.user_id,after_data={"assessment_id":str(a.assessment_id),"version":a.row_version,"doctor_reviewed":bool(a.reviewed_at)})
        db.commit();return {"assessment":data}
    except IntegrityError as exc:
        db.rollback();raise HTTPException(409,"Safety record conflicted. Refresh and review") from exc
    except Exception:
        db.rollback();raise
