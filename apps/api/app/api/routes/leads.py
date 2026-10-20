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
    LeadDncHistory,
    LeadInteraction,
    LeadSource,
    LeadStatus,
    LeadStatusHistory,
    LostReason,
)
from app.schemas.crm import LeadVersion, DncChange, LeadCreate, LeadInteractionCreate, LeadOut, LeadUpdate, ThirdPartyAssignmentCreate
from app.schemas.patient import ConversionPreviewOut, LeadPatientConversionCreate, PatientDetailOut
from app.services.leads import add_interaction, assign_to_partner, change_dnc, create_lead, reopen_lead, search_previous_inquiries
from app.services.patients import conversion_preview, convert_lead_to_patient, current_fiscal_year, get_patient_detail

router = APIRouter(prefix="/leads", tags=["leads"])


def _get_lead(db, user, lead_id, row_version=None):
    lead = db.scalar(select(Lead).where(Lead.lead_id == lead_id, Lead.organization_id == user.organization_id).with_for_update().execution_options(populate_existing=True))
    if not lead:
        raise HTTPException(404, "Lead not found")
    if lead.preferred_branch_id:
        ensure_branch_access(db, user, lead.preferred_branch_id)
    if row_version is not None and lead.row_version != row_version:
        raise HTTPException(409, "Lead changed. Reload and review before saving")
    return lead


def _validate_owner(db, user, owner_id, branch_id):
    if owner_id is None:
        return
    owner = db.get(User, owner_id)
    if not owner or owner.organization_id != user.organization_id or owner.status != "ACTIVE":
        raise HTTPException(422, "Choose an active staff member from this clinic")
    try:
        require_permission("LEAD_EDIT")(user=owner, db=db)
        if branch_id:
            ensure_branch_access(db, owner, branch_id)
    except HTTPException:
        raise HTTPException(422, "Owner must have Lead access at the selected branch")


@router.get("/owners")
def owners(db: Session = Depends(get_db), user: User = Depends(require_permission("LEAD_VIEW"))):
    result = []
    allowed = allowed_branch_ids(db, user)
    for owner in db.scalars(select(User).where(User.organization_id == user.organization_id, User.status == "ACTIVE").order_by(User.name)).all():
        try:
            require_permission("LEAD_EDIT")(user=owner, db=db)
        except HTTPException:
            continue
        branches = allowed_branch_ids(db, owner)
        if allowed is not None and branches is not None and not allowed.intersection(branches):
            continue
        result.append({"id": owner.user_id, "name": owner.name, "branch_ids": list(branches) if branches is not None else None})
    return result


def _lead_row(db: Session, lead: Lead) -> dict:
    contact = db.scalar(select(LeadContact).where(LeadContact.lead_id == lead.lead_id, LeadContact.is_primary.is_(True)).limit(1))
    status = db.get(LeadStatus, lead.lead_status_id)
    source = db.get(LeadSource, lead.lead_source_id)
    branch = db.get(Branch, lead.preferred_branch_id) if lead.preferred_branch_id else None
    owner = db.get(User, lead.lead_owner_user_id) if lead.lead_owner_user_id else None
    return {
        "lead_owner_user_id": lead.lead_owner_user_id,
        "owner_name": owner.name if owner else None,
        "preferred_branch_id": lead.preferred_branch_id,
        "lead_source_id": lead.lead_source_id,
        "lead_status_id": lead.lead_status_id,
        "lost_reason_id": lead.lost_reason_id,
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
    _validate_owner(db, user, payload.lead_owner_user_id, payload.preferred_branch_id)
    lead = create_lead(db, payload=payload, actor_user_id=user.user_id)
    db.commit(); db.refresh(lead)
    return lead


@router.get("")
def list_leads(
    q: str | None = Query(default=None),
    status_code: str | None = Query(default=None),
    followups_due: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=250),
    offset: int = Query(default=0, ge=0),
    owner_id: uuid.UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("LEAD_VIEW")),
):
    stmt = select(Lead).where(Lead.organization_id == user.organization_id)
    allowed = allowed_branch_ids(db, user)
    if allowed is not None:
        stmt = stmt.where((Lead.preferred_branch_id.in_(allowed)) | (Lead.preferred_branch_id.is_(None)))
    if owner_id:
        stmt = stmt.where(Lead.lead_owner_user_id == owner_id)
    if status_code:
        stmt = stmt.join(LeadStatus, LeadStatus.lead_status_id == Lead.lead_status_id).where(LeadStatus.code == status_code)
    if q:
        normalized = "".join(ch for ch in q if ch.isdigit())[-10:]
        stmt = stmt.outerjoin(LeadContact, LeadContact.lead_id == Lead.lead_id).where(
            or_(Lead.lead_name.ilike(f"%{q.strip()}%"), LeadContact.normalized_value == normalized)
        ).distinct()
    if followups_due:
        stmt = stmt.where(Lead.dnc.is_(False), Lead.next_followup_at.is_not(None), Lead.next_followup_at <= datetime.now(timezone.utc))
    leads = list(db.scalars(stmt.order_by(Lead.updated_at.desc(), Lead.lead_id).offset(offset).limit(limit)).all())
    return [_lead_row(db, lead) for lead in leads]


@router.get("/search")
def search(name: str | None = Query(default=None), mobile: str | None = Query(default=None), db: Session = Depends(get_db), user: User = Depends(require_permission("LEAD_VIEW"))):
    rows = [x for x in search_previous_inquiries(db, name=name, mobile=mobile, organization_id=user.organization_id, branch_ids=allowed_branch_ids(db, user)) if x.organization_id == user.organization_id]
    return [_lead_row(db, x) for x in rows]


@router.get("/{lead_id}")
def detail(lead_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_permission("LEAD_VIEW"))):
    lead = _get_lead(db, user, lead_id)
    interactions = list(db.scalars(select(LeadInteraction).where(LeadInteraction.lead_id == lead_id).order_by(LeadInteraction.interaction_at.desc()).limit(100)).all())
    status_history = list(db.execute(
        select(LeadStatusHistory, LeadStatus.code, LeadStatus.name)
        .join(LeadStatus, LeadStatus.lead_status_id == LeadStatusHistory.new_status_id)
        .where(LeadStatusHistory.lead_id == lead_id)
        .order_by(LeadStatusHistory.changed_at.desc())
    ).all())
    return {
        **_lead_row(db, lead),
        "dnc_history": [{"old_dnc": x.old_dnc, "new_dnc": x.new_dnc, "reason": x.reason, "changed_at": x.changed_at, "changed_by": x.changed_by} for x in db.scalars(select(LeadDncHistory).where(LeadDncHistory.lead_id == lead_id).order_by(LeadDncHistory.changed_at.desc())).all()],
        "interactions": [{
            "interaction_id": x.interaction_id,
            "type": x.interaction_type,
            "performed_by": x.performed_by_user_id,
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
    lead = _get_lead(db, user, lead_id)
    if lead.row_version != payload.row_version:
        raise HTTPException(409, "Lead was updated by another user. Reload and review the latest record.")
    values = payload.model_dump(exclude={"row_version"}, exclude_unset=True)
    if any(values.get(k) is None for k in ("lead_name", "mobile", "lead_source_id", "lead_status_id") if k in values):
        raise HTTPException(422, "Name, mobile, source and status cannot be empty")
    branch_id = values.get("preferred_branch_id", lead.preferred_branch_id)
    if branch_id:
        ensure_branch_access(db, user, branch_id)
    _validate_owner(db, user, values.get("lead_owner_user_id", lead.lead_owner_user_id), branch_id)
    if "lead_source_id" in values:
        source = db.get(LeadSource, values["lead_source_id"])
        if not source or not source.active:
            raise HTTPException(422, "Select an active lead source")
    if values.get("next_followup_at") is not None and lead.dnc:
        raise HTTPException(409, "DNC blocks outbound follow-up scheduling")
    if "lead_status_id" in values and values["lead_status_id"] != lead.lead_status_id:
        current = db.get(LeadStatus, lead.lead_status_id)
        status = db.get(LeadStatus, values["lead_status_id"])
        if not status or status.code not in {"NEW", "FOLLOW_UP_REQUIRED", "LOST", "SPAM_FAKE"} or current.code in {"CONVERTED", "LOST", "NO_SHOW"}:
            raise HTTPException(409, "Use the dedicated reopen, conversion or appointment action for this status")
        if status.code == "LOST":
            reason = db.get(LostReason, values.get("lost_reason_id")) if values.get("lost_reason_id") else None
            if not reason or not reason.active:
                raise HTTPException(422, "Select a lost reason")
            values["next_followup_at"] = None
        else:
            values["lost_reason_id"] = None
        db.add(LeadStatusHistory(lead_id=lead_id, old_status_id=lead.lead_status_id, new_status_id=status.lead_status_id, changed_by=user.user_id, changed_at=datetime.now(timezone.utc), reason="Status updated by staff"))
    before = {key: str(getattr(lead, key, "")) for key in values}
    mobile = values.pop("mobile", None)
    if mobile:
        from app.services.utils import normalize_mobile
        contact = db.scalar(select(LeadContact).where(LeadContact.lead_id == lead_id, LeadContact.is_primary.is_(True)))
        if contact:
            before["mobile"] = contact.contact_value
            contact.contact_value = mobile
            contact.normalized_value = normalize_mobile(mobile)
        else:
            db.add(LeadContact(lead_id=lead_id, contact_type="MOBILE", contact_value=mobile, normalized_value=normalize_mobile(mobile), is_primary=True))
    for key, value in values.items():
        setattr(lead, key, value)
    from app.services.audit import log_audit
    log_audit(db, organization_id=user.organization_id, entity_type="LEAD", entity_id=lead_id, action="LEAD_UPDATED", actor_user_id=user.user_id, before_data=before, after_data={**{k:str(v) for k,v in values.items()}, **({"mobile":mobile} if mobile else {})})
    lead.updated_by = user.user_id
    lead.row_version += 1
    db.commit(); db.refresh(lead)
    return _lead_row(db, lead)


@router.post("/{lead_id}/interactions")
def interaction(lead_id: uuid.UUID, payload: LeadInteractionCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("LEAD_EDIT"))):
    lead = _get_lead(db, user, lead_id, payload.row_version)
    item = add_interaction(db, lead=lead, payload=payload, actor_user_id=user.user_id)
    db.commit()
    return {"interaction_id": item.interaction_id}


@router.post("/{lead_id}/dnc", response_model=LeadOut)
def set_dnc(lead_id: uuid.UUID, payload: DncChange, db: Session = Depends(get_db), user: User = Depends(require_permission("LEAD_EDIT"))):
    lead = _get_lead(db, user, lead_id, payload.row_version)
    if not payload.reason or not payload.reason.strip():
        raise HTTPException(422, "Enter a reason for the DNC change")
    change_dnc(db, lead=lead, new_value=payload.dnc, actor_user_id=user.user_id, reason=payload.reason)
    db.commit(); db.refresh(lead)
    return lead


@router.post("/{lead_id}/reopen", response_model=LeadOut)
def reopen(lead_id: uuid.UUID, payload: LeadVersion, db: Session = Depends(get_db), user: User = Depends(require_permission("LEAD_EDIT"))):
    lead = _get_lead(db, user, lead_id, payload.row_version)
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
def mark_lost(lead_id: uuid.UUID, lost_reason_id: uuid.UUID, row_version: int = Query(ge=1), note: str | None = None, db: Session = Depends(get_db), user: User = Depends(require_permission("LEAD_EDIT"))):
    lead = _get_lead(db, user, lead_id)
    if lead.row_version != row_version:
        raise HTTPException(409, "Lead changed. Reload before saving")
    reason = db.get(LostReason, lost_reason_id)
    if not reason or not reason.active:
        raise HTTPException(400, "Lost reason required")
    lost = db.scalar(select(LeadStatus).where(LeadStatus.code == "LOST"))
    if not lost:
        raise HTTPException(503, "Lost status master missing")
    current = db.get(LeadStatus, lead.lead_status_id)
    if current.code == "CONVERTED":
        raise HTTPException(409, "Converted leads cannot be marked lost")
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
    lead = _get_lead(db, user, lead_id)
    assignment = assign_to_partner(db, lead=lead, partner_id=payload.partner_id, actor_user_id=user.user_id, valid_until=payload.valid_until)
    db.commit()
    return {"assignment_id": assignment.assignment_id}


@router.get("/{lead_id}/conversion-preview", response_model=ConversionPreviewOut)
def preview_conversion(
    lead_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PATIENT_CREATE")),
):
    lead = _get_lead(db, user, lead_id)
    return conversion_preview(db, lead=lead)


@router.post("/{lead_id}/convert", response_model=PatientDetailOut)
def convert_to_patient(
    lead_id: uuid.UUID,
    payload: LeadPatientConversionCreate,
    fiscal_year: str | None = Query(default=None, examples=["2026-27"]),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PATIENT_CREATE")),
):
    lead = _get_lead(db, user, lead_id)
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
