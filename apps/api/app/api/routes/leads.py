import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.access import allowed_branch_ids, ensure_branch_access
from app.core.permissions import require_permission
from app.models.core import Branch, User
from app.models.crm import (
    Lead,
    LeadContact,
    LeadInteraction,
    LeadSource,
    LeadStatus,
    LeadStatusHistory,
    LostReason,
)
from app.schemas.crm import DncChange, LeadCreate, LeadInteractionCreate, LeadOut, LeadUpdate, ThirdPartyAssignmentCreate
from app.schemas.patient import ConversionPreviewOut, LeadPatientConversionCreate, PatientDetailOut
from app.services.leads import add_interaction, assign_to_partner, change_dnc, create_lead, reopen_lead, search_previous_inquiries
from app.services.patients import conversion_preview, convert_lead_to_patient, current_fiscal_year, get_patient_detail

router = APIRouter(prefix="/leads", tags=["leads"])


def _lead_row(db: Session, lead: Lead) -> dict:
    contact = db.scalar(select(LeadContact).where(LeadContact.lead_id == lead.lead_id, LeadContact.is_primary.is_(True)).limit(1))
    status = db.get(LeadStatus, lead.lead_status_id)
    source = db.get(LeadSource, lead.lead_source_id)
    branch = db.get(Branch, lead.preferred_branch_id) if lead.preferred_branch_id else None
    return {
        "lead_id": lead.lead_id,
        "lead_name": lead.lead_name,
        "mobile": contact.contact_value if contact else None,
        "age": lead.age,
        "gender": lead.gender,
        "concern_text": lead.concern_text,
        "source": source.name if source else None,
        "source_code": source.code if source else None,
        "status": status.name if status else None,
        "status_code": status.code if status else None,
        "preferred_branch": branch.branch_name if branch else None,
        "dnc": lead.dnc,
        "next_followup_at": lead.next_followup_at,
        "last_interaction_at": lead.last_interaction_at,
        "created_at": lead.created_at,
        "updated_at": lead.updated_at,
        "row_version": lead.row_version,
    }


@router.post("", response_model=LeadOut)
def create(payload: LeadCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("LEAD_CREATE"))):
    if payload.organization_id != user.organization_id:
        raise HTTPException(403, "Cannot create Lead for another organization")
    if payload.preferred_branch_id:
        ensure_branch_access(db, user, payload.preferred_branch_id)
    lead = create_lead(db, payload=payload, actor_user_id=user.user_id)
    db.commit(); db.refresh(lead)
    return lead


@router.get("")
def list_leads(
    q: str | None = Query(default=None),
    status_code: str | None = Query(default=None),
    followups_due: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=250),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("LEAD_VIEW")),
):
    stmt = select(Lead).where(Lead.organization_id == user.organization_id)
    allowed = allowed_branch_ids(db, user)
    if allowed is not None:
        stmt = stmt.where((Lead.preferred_branch_id.in_(allowed)) | (Lead.preferred_branch_id.is_(None)))
    if status_code:
        stmt = stmt.join(LeadStatus, LeadStatus.lead_status_id == Lead.lead_status_id).where(LeadStatus.code == status_code)
    if q:
        normalized = "".join(ch for ch in q if ch.isdigit())[-10:]
        stmt = stmt.outerjoin(LeadContact, LeadContact.lead_id == Lead.lead_id).where(
            or_(Lead.lead_name.ilike(f"%{q.strip()}%"), LeadContact.normalized_value == normalized)
        ).distinct()
    if followups_due:
        stmt = stmt.where(Lead.dnc.is_(False), Lead.next_followup_at.is_not(None), Lead.next_followup_at <= datetime.now(timezone.utc))
    leads = list(db.scalars(stmt.order_by(Lead.updated_at.desc()).limit(limit)).all())
    return [_lead_row(db, lead) for lead in leads]


@router.get("/search")
def search(name: str | None = Query(default=None), mobile: str | None = Query(default=None), db: Session = Depends(get_db), user: User = Depends(require_permission("LEAD_VIEW"))):
    rows = [x for x in search_previous_inquiries(db, name=name, mobile=mobile) if x.organization_id == user.organization_id]
    return [_lead_row(db, x) for x in rows]


@router.get("/{lead_id}")
def detail(lead_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_permission("LEAD_VIEW"))):
    lead = db.get(Lead, lead_id)
    if not lead or lead.organization_id != user.organization_id:
        raise HTTPException(404, "Lead not found")
    interactions = list(db.scalars(select(LeadInteraction).where(LeadInteraction.lead_id == lead_id).order_by(LeadInteraction.interaction_at.desc()).limit(100)).all())
    status_history = list(db.execute(
        select(LeadStatusHistory, LeadStatus.code, LeadStatus.name)
        .join(LeadStatus, LeadStatus.lead_status_id == LeadStatusHistory.new_status_id)
        .where(LeadStatusHistory.lead_id == lead_id)
        .order_by(LeadStatusHistory.changed_at.desc())
    ).all())
    return {
        **_lead_row(db, lead),
        "interactions": [{
            "interaction_id": x.interaction_id,
            "type": x.interaction_type,
            "channel": x.channel,
            "summary": x.summary,
            "outcome": x.outcome,
            "interaction_at": x.interaction_at,
            "next_followup_at": x.next_followup_at,
        } for x in interactions],
        "status_history": [{
            "code": code,
            "status": name,
            "changed_at": hist.changed_at,
            "reason": hist.reason,
        } for hist, code, name in status_history],
    }


@router.patch("/{lead_id}")
def update_lead(lead_id: uuid.UUID, payload: LeadUpdate, db: Session = Depends(get_db), user: User = Depends(require_permission("LEAD_EDIT"))):
    lead = db.get(Lead, lead_id)
    if not lead or lead.organization_id != user.organization_id:
        raise HTTPException(404, "Lead not found")
    if lead.row_version != payload.row_version:
        raise HTTPException(409, "Lead was updated by another user. Reload and review the latest record.")
    values = payload.model_dump(exclude={"row_version"}, exclude_unset=True)
    if "preferred_branch_id" in values and values["preferred_branch_id"] is not None:
        ensure_branch_access(db, user, values["preferred_branch_id"])
    for key, value in values.items():
        setattr(lead, key, value)
    lead.updated_by = user.user_id
    lead.row_version += 1
    db.commit(); db.refresh(lead)
    return _lead_row(db, lead)


@router.post("/{lead_id}/interactions")
def interaction(lead_id: uuid.UUID, payload: LeadInteractionCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("LEAD_EDIT"))):
    lead = db.get(Lead, lead_id)
    if not lead or lead.organization_id != user.organization_id:
        raise HTTPException(404, "Lead not found")
    item = add_interaction(db, lead=lead, payload=payload, actor_user_id=user.user_id)
    db.commit()
    return {"interaction_id": item.interaction_id}


@router.post("/{lead_id}/dnc", response_model=LeadOut)
def set_dnc(lead_id: uuid.UUID, payload: DncChange, db: Session = Depends(get_db), user: User = Depends(require_permission("LEAD_EDIT"))):
    lead = db.get(Lead, lead_id)
    if not lead or lead.organization_id != user.organization_id:
        raise HTTPException(404, "Lead not found")
    change_dnc(db, lead=lead, new_value=payload.dnc, actor_user_id=user.user_id, reason=payload.reason)
    db.commit(); db.refresh(lead)
    return lead


@router.post("/{lead_id}/reopen", response_model=LeadOut)
def reopen(lead_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_permission("LEAD_EDIT"))):
    lead = db.get(Lead, lead_id)
    if not lead or lead.organization_id != user.organization_id:
        raise HTTPException(404, "Lead not found")
    current = db.get(LeadStatus, lead.lead_status_id)
    if not current or current.code not in {"LOST", "NO_SHOW"}:
        raise HTTPException(409, "Only Lost/No-show Leads can be reopened")
    followup = db.scalar(select(LeadStatus).where(LeadStatus.code == "FOLLOW_UP_REQUIRED"))
    if not followup:
        raise HTTPException(503, "FOLLOW_UP_REQUIRED status master missing")
    reopen_lead(db, lead=lead, actor_user_id=user.user_id, followup_status_id=followup.lead_status_id)
    db.commit(); db.refresh(lead)
    return lead


@router.post("/{lead_id}/mark-lost", response_model=LeadOut)
def mark_lost(lead_id: uuid.UUID, lost_reason_id: uuid.UUID, note: str | None = None, db: Session = Depends(get_db), user: User = Depends(require_permission("LEAD_EDIT"))):
    lead = db.get(Lead, lead_id)
    if not lead or lead.organization_id != user.organization_id:
        raise HTTPException(404, "Lead not found")
    reason = db.get(LostReason, lost_reason_id)
    if not reason:
        raise HTTPException(400, "Lost reason required")
    lost = db.scalar(select(LeadStatus).where(LeadStatus.code == "LOST"))
    old = lead.lead_status_id
    lead.lead_status_id = lost.lead_status_id
    lead.lost_reason_id = reason.lost_reason_id
    lead.next_followup_at = None
    lead.updated_by = user.user_id
    lead.row_version += 1
    db.add(LeadStatusHistory(lead_id=lead.lead_id, old_status_id=old, new_status_id=lost.lead_status_id, changed_by=user.user_id, changed_at=datetime.now(timezone.utc), reason=note or reason.name))
    db.commit(); db.refresh(lead)
    return lead


@router.post("/{lead_id}/external-assignments")
def external_assignment(lead_id: uuid.UUID, payload: ThirdPartyAssignmentCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("LEAD_EXTERNAL_ASSIGN"))):
    lead = db.get(Lead, lead_id)
    if not lead or lead.organization_id != user.organization_id:
        raise HTTPException(404, "Lead not found")
    assignment = assign_to_partner(db, lead=lead, partner_id=payload.partner_id, actor_user_id=user.user_id, valid_until=payload.valid_until)
    db.commit()
    return {"assignment_id": assignment.assignment_id}


@router.get("/{lead_id}/conversion-preview", response_model=ConversionPreviewOut)
def preview_conversion(
    lead_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PATIENT_CREATE")),
):
    lead = db.get(Lead, lead_id)
    if not lead or lead.organization_id != user.organization_id:
        raise HTTPException(404, "Lead not found")
    return conversion_preview(db, lead=lead)


@router.post("/{lead_id}/convert", response_model=PatientDetailOut)
def convert_to_patient(
    lead_id: uuid.UUID,
    payload: LeadPatientConversionCreate,
    fiscal_year: str | None = Query(default=None, examples=["2026-27"]),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PATIENT_CREATE")),
):
    lead = db.get(Lead, lead_id)
    if not lead or lead.organization_id != user.organization_id:
        raise HTTPException(404, "Lead not found")
    patient, _created_new = convert_lead_to_patient(
        db,
        lead_id=lead_id,
        payload=payload,
        actor_user_id=user.user_id,
        fiscal_year=fiscal_year or current_fiscal_year(),
    )
    db.commit()
    db.refresh(patient)
    return get_patient_detail(db, patient=patient)
