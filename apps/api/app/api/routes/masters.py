import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.permissions import require_permission
from app.models.clinical import ChiefComplaint, VisitComplaint
from app.models.core import User
from app.models.patient import District, Locality, PatientAddress
from app.schemas.masters import ComplaintProposalCreate, LocalityProposalCreate, MasterResolve
from app.services.audit import log_audit

router = APIRouter(prefix="/masters", tags=["masters"])


def _creator_name(db: Session, user_id):
    u = db.get(User, user_id) if user_id else None
    return u.name if u else None


@router.post("/localities")
def propose_locality(
    payload: LocalityProposalCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PATIENT_EDIT")),
):
    district = db.get(District, payload.district_id)
    if not district:
        raise HTTPException(400, "District not found")
    name = " ".join(payload.name.split()).strip()
    existing = db.scalar(
        select(Locality).where(
            Locality.district_id == payload.district_id,
            func.lower(Locality.locality_name) == name.lower(),
            Locality.merged_into_locality_id.is_(None),
        ).limit(1)
    )
    if existing:
        return {"locality_id": existing.locality_id, "name": existing.locality_name, "approval_status": existing.approval_status, "existing": True}
    item = Locality(
        district_id=payload.district_id,
        locality_name=name,
        approval_status="PENDING",
        created_by=user.user_id,
    )
    db.add(item); db.flush()
    log_audit(db, organization_id=user.organization_id, entity_type="LOCALITY", entity_id=item.locality_id, action="MASTER_PROPOSED", actor_user_id=user.user_id, after_data={"name": name, "status": "PENDING"})
    db.commit(); db.refresh(item)
    return {"locality_id": item.locality_id, "name": item.locality_name, "approval_status": item.approval_status, "existing": False}


@router.post("/chief-complaints")
def propose_complaint(
    payload: ComplaintProposalCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("VISIT_CREATE")),
):
    name = " ".join(payload.name.split()).strip()
    existing = db.scalar(select(ChiefComplaint).where(func.lower(ChiefComplaint.name) == name.lower(), ChiefComplaint.merged_into_complaint_id.is_(None)).limit(1))
    if existing:
        return {"chief_complaint_id": existing.chief_complaint_id, "name": existing.name, "approval_status": existing.approval_status, "existing": True}
    item = ChiefComplaint(name=name, approval_status="PENDING", created_by=user.user_id, active=True)
    db.add(item); db.flush()
    log_audit(db, organization_id=user.organization_id, entity_type="CHIEF_COMPLAINT", entity_id=item.chief_complaint_id, action="MASTER_PROPOSED", actor_user_id=user.user_id, after_data={"name": name, "status": "PENDING"})
    db.commit(); db.refresh(item)
    return {"chief_complaint_id": item.chief_complaint_id, "name": item.name, "approval_status": item.approval_status, "existing": False}


@router.get("/pending")
def pending_masters(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("MASTER_APPROVE")),
):
    localities = list(db.scalars(select(Locality).where(Locality.approval_status == "PENDING").order_by(Locality.created_at)).all())
    complaints = list(db.scalars(select(ChiefComplaint).where(ChiefComplaint.approval_status == "PENDING").order_by(ChiefComplaint.created_at)).all())
    out = []
    for x in localities:
        usage = db.scalar(select(func.count()).select_from(PatientAddress).where(PatientAddress.locality_id == x.locality_id)) or 0
        out.append({"master_type":"LOCALITY","id":x.locality_id,"name":x.locality_name,"parent_id":x.district_id,"created_by":x.created_by,"created_by_name":_creator_name(db,x.created_by),"created_at":x.created_at.isoformat() if x.created_at else None,"usage_count":usage})
    for x in complaints:
        usage = db.scalar(select(func.count()).select_from(VisitComplaint).where(VisitComplaint.chief_complaint_id == x.chief_complaint_id)) or 0
        out.append({"master_type":"CHIEF_COMPLAINT","id":x.chief_complaint_id,"name":x.name,"parent_id":None,"created_by":x.created_by,"created_by_name":_creator_name(db,x.created_by),"created_at":x.created_at.isoformat() if x.created_at else None,"usage_count":usage})
    return out


def _resolve_locality(db: Session, item: Locality, payload: MasterResolve, user: User):
    before = {"name": item.locality_name, "status": item.approval_status}
    usage = db.scalar(select(func.count()).select_from(PatientAddress).where(PatientAddress.locality_id == item.locality_id)) or 0
    if payload.action == "APPROVE":
        item.approval_status = "APPROVED"; item.approved_by = user.user_id
    elif payload.action == "CORRECT":
        if not payload.corrected_name: raise HTTPException(400, "corrected_name is required")
        item.locality_name = " ".join(payload.corrected_name.split()).strip(); item.approval_status = "APPROVED"; item.approved_by = user.user_id
    elif payload.action == "MERGE":
        if not payload.merge_into_id or payload.merge_into_id == item.locality_id: raise HTTPException(400, "Valid merge_into_id is required")
        target = db.get(Locality, payload.merge_into_id)
        if not target or target.district_id != item.district_id or target.approval_status != "APPROVED": raise HTTPException(400, "Approved target locality in same district is required")
        db.execute(update(PatientAddress).where(PatientAddress.locality_id == item.locality_id).values(locality_id=target.locality_id))
        item.merged_into_locality_id = target.locality_id; item.approval_status = "MERGED"; item.approved_by = user.user_id
    else:
        if usage: raise HTTPException(409, "Referenced locality cannot be rejected. Correct or merge it instead.")
        item.approval_status = "REJECTED"; item.approved_by = user.user_id
    return before


def _resolve_complaint(db: Session, item: ChiefComplaint, payload: MasterResolve, user: User):
    before = {"name": item.name, "status": item.approval_status}
    usage = db.scalar(select(func.count()).select_from(VisitComplaint).where(VisitComplaint.chief_complaint_id == item.chief_complaint_id)) or 0
    if payload.action == "APPROVE":
        item.approval_status = "APPROVED"; item.approved_by = user.user_id
    elif payload.action == "CORRECT":
        if not payload.corrected_name: raise HTTPException(400, "corrected_name is required")
        item.name = " ".join(payload.corrected_name.split()).strip(); item.approval_status = "APPROVED"; item.approved_by = user.user_id
    elif payload.action == "MERGE":
        if not payload.merge_into_id or payload.merge_into_id == item.chief_complaint_id: raise HTTPException(400, "Valid merge_into_id is required")
        target = db.get(ChiefComplaint, payload.merge_into_id)
        if not target or target.approval_status != "APPROVED" or not target.active: raise HTTPException(400, "Approved target complaint is required")
        rows = list(db.scalars(select(VisitComplaint).where(VisitComplaint.chief_complaint_id == item.chief_complaint_id)).all())
        for row in rows:
            existing = db.scalar(select(VisitComplaint).where(VisitComplaint.visit_id == row.visit_id, VisitComplaint.chief_complaint_id == target.chief_complaint_id).limit(1))
            if existing: db.delete(row)
            else: row.chief_complaint_id = target.chief_complaint_id
        item.merged_into_complaint_id = target.chief_complaint_id; item.approval_status = "MERGED"; item.approved_by = user.user_id; item.active = False
    else:
        if usage: raise HTTPException(409, "Referenced complaint cannot be rejected. Correct or merge it instead.")
        item.approval_status = "REJECTED"; item.approved_by = user.user_id; item.active = False
    return before


@router.post("/localities/{locality_id}/resolve")
def resolve_locality(locality_id: uuid.UUID, payload: MasterResolve, db: Session = Depends(get_db), user: User = Depends(require_permission("MASTER_APPROVE"))):
    item = db.scalar(select(Locality).where(Locality.locality_id == locality_id).with_for_update())
    if not item: raise HTTPException(404, "Locality not found")
    if item.approval_status != "PENDING": raise HTTPException(409, "Locality is no longer pending")
    before = _resolve_locality(db,item,payload,user)
    log_audit(db, organization_id=user.organization_id, entity_type="LOCALITY", entity_id=item.locality_id, action=f"MASTER_{payload.action}", actor_user_id=user.user_id, before_data=before, after_data={"name":item.locality_name,"status":item.approval_status,"merged_into":str(item.merged_into_locality_id) if item.merged_into_locality_id else None}, reason=payload.reason)
    db.commit(); db.refresh(item)
    return {"id":item.locality_id,"name":item.locality_name,"status":item.approval_status}


@router.post("/chief-complaints/{complaint_id}/resolve")
def resolve_complaint(complaint_id: uuid.UUID, payload: MasterResolve, db: Session = Depends(get_db), user: User = Depends(require_permission("MASTER_APPROVE"))):
    item = db.scalar(select(ChiefComplaint).where(ChiefComplaint.chief_complaint_id == complaint_id).with_for_update())
    if not item: raise HTTPException(404, "Chief Complaint not found")
    if item.approval_status != "PENDING": raise HTTPException(409, "Chief Complaint is no longer pending")
    before = _resolve_complaint(db,item,payload,user)
    log_audit(db, organization_id=user.organization_id, entity_type="CHIEF_COMPLAINT", entity_id=item.chief_complaint_id, action=f"MASTER_{payload.action}", actor_user_id=user.user_id, before_data=before, after_data={"name":item.name,"status":item.approval_status,"merged_into":str(item.merged_into_complaint_id) if item.merged_into_complaint_id else None}, reason=payload.reason)
    db.commit(); db.refresh(item)
    return {"id":item.chief_complaint_id,"name":item.name,"status":item.approval_status}
