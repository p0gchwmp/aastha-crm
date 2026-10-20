import uuid
from datetime import datetime, timezone
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session
from app.models.crm import (
    Lead,
    LeadContact,
    LeadDncHistory,
    LeadExternalAssignment,
    LeadInteraction,
    LeadStatus,
    LeadSource,
    LeadStatusHistory,
)
from app.services.dnc import assert_outbound_allowed
from app.services.utils import normalize_mobile


def create_lead(db: Session, *, payload, actor_user_id: uuid.UUID | None) -> Lead:
    source = db.get(LeadSource, payload.lead_source_id)
    status = db.get(LeadStatus, payload.lead_status_id)
    from fastapi import HTTPException
    if not source or not source.active:
        raise HTTPException(422, "Select an active lead source")
    if not status or status.code != "NEW":
        raise HTTPException(422, "New leads must start with New status")
    lead = Lead(
        organization_id=payload.organization_id,
        lead_name=payload.lead_name.strip(),
        age=payload.age,
        gender=payload.gender,
        concern_text=payload.concern_text,
        interested_service_id=payload.interested_service_id,
        lead_source_id=payload.lead_source_id,
        campaign_id=payload.campaign_id,
        preferred_branch_id=payload.preferred_branch_id,
        lead_owner_user_id=payload.lead_owner_user_id,
        lead_status_id=payload.lead_status_id,
        next_followup_at=payload.next_followup_at,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    db.add(lead)
    db.flush()
    db.add(
        LeadContact(
            lead_id=lead.lead_id,
            contact_type="MOBILE",
            contact_value=payload.mobile,
            normalized_value=normalize_mobile(payload.mobile),
            is_primary=True,
        )
    )
    db.add(
        LeadStatusHistory(
            lead_id=lead.lead_id,
            old_status_id=None,
            new_status_id=lead.lead_status_id,
            changed_by=actor_user_id,
            changed_at=datetime.now(timezone.utc),
            reason="Lead created",
        )
    )
    return lead


def search_previous_inquiries(db: Session, *, name: str | None, mobile: str | None, organization_id=None, branch_ids=None) -> list[Lead]:
    stmt = select(Lead).distinct().outerjoin(LeadContact, LeadContact.lead_id == Lead.lead_id)
    if organization_id is not None:
        stmt = stmt.where(Lead.organization_id == organization_id)
    if branch_ids is not None:
        stmt = stmt.where(or_(Lead.preferred_branch_id.in_(branch_ids), Lead.preferred_branch_id.is_(None)))
    predicates = []
    if name and name.strip():
        predicates.append(Lead.lead_name.ilike(f"%{name.strip()}%"))
    if mobile and normalize_mobile(mobile):
        predicates.append(LeadContact.normalized_value == normalize_mobile(mobile))
    if not predicates:
        return []
    stmt = stmt.where(or_(*predicates))
    return list(db.scalars(stmt.order_by(Lead.updated_at.desc()).limit(30)).all())


def change_dnc(db: Session, *, lead: Lead, new_value: bool, actor_user_id: uuid.UUID | None, reason: str | None) -> Lead:
    old = lead.dnc
    if old == new_value:
        return lead
    if new_value:
        lead.next_followup_at = None
        db.execute(update(LeadExternalAssignment).where(LeadExternalAssignment.lead_id == lead.lead_id, LeadExternalAssignment.status == "ACTIVE").values(status="REVOKED"))
    lead.dnc = new_value
    lead.updated_by = actor_user_id
    lead.row_version += 1
    db.add(
        LeadDncHistory(
            lead_id=lead.lead_id,
            old_dnc=old,
            new_dnc=new_value,
            changed_by=actor_user_id,
            changed_at=datetime.now(timezone.utc),
            reason=reason,
        )
    )
    return lead


def reopen_lead(db: Session, *, lead: Lead, actor_user_id: uuid.UUID | None, followup_status_id: uuid.UUID, reason: str | None = None) -> Lead:
    old = lead.lead_status_id
    lead.lead_status_id = followup_status_id
    lead.lost_reason_id = None
    lead.updated_by = actor_user_id
    lead.row_version += 1
    db.add(
        LeadStatusHistory(
            lead_id=lead.lead_id,
            old_status_id=old,
            new_status_id=followup_status_id,
            changed_by=actor_user_id,
            changed_at=datetime.now(timezone.utc),
            reason=reason or "Lead reopened",
        )
    )
    return lead


def add_interaction(db: Session, *, lead: Lead, payload, actor_user_id: uuid.UUID | None) -> LeadInteraction:
    if payload.interaction_type not in {"INBOUND_CALL", "INBOUND_WHATSAPP", "OUTBOUND_CALL", "OUTBOUND_WHATSAPP", "NOTE", "FOLLOW_UP"}:
        from fastapi import HTTPException
        raise HTTPException(422, "Choose an inbound, outbound, note or follow-up interaction")
    if payload.interaction_type.startswith("OUTBOUND") or payload.interaction_type == "FOLLOW_UP" or payload.next_followup_at is not None:
        assert_outbound_allowed(lead)
    now = datetime.now(timezone.utc)
    item = LeadInteraction(
        lead_id=lead.lead_id,
        interaction_type=payload.interaction_type,
        channel=payload.channel,
        interaction_at=now,
        performed_by_user_id=actor_user_id,
        summary=payload.summary,
        outcome=payload.outcome,
        next_followup_at=payload.next_followup_at,
    )
    db.add(item)
    lead.last_interaction_at = now
    if "next_followup_at" in payload.model_fields_set:
        lead.next_followup_at = payload.next_followup_at
    lead.updated_by = actor_user_id
    lead.row_version += 1
    if payload.next_followup_at is not None:
        ensure_followup_status(db, lead=lead, actor_user_id=actor_user_id)
    return item


def assign_to_partner(db: Session, *, lead: Lead, partner_id: uuid.UUID, actor_user_id: uuid.UUID, valid_until=None) -> LeadExternalAssignment:
    assert_outbound_allowed(lead)
    assignment = LeadExternalAssignment(
        lead_id=lead.lead_id,
        partner_id=partner_id,
        assigned_by=actor_user_id,
        valid_until=valid_until,
        status="ACTIVE",
    )
    db.add(assignment)
    return assignment


def ensure_followup_status(db: Session, *, lead: Lead, actor_user_id: uuid.UUID | None) -> None:
    """Move an active Lead into FOLLOW_UP_REQUIRED when a future follow-up is scheduled."""
    current = db.get(LeadStatus, lead.lead_status_id)
    if not current or current.code in {"CONVERTED", "LOST", "SPAM_FAKE", "DO_NOT_CALL"}:
        return
    followup = db.scalar(select(LeadStatus).where(LeadStatus.code == "FOLLOW_UP_REQUIRED"))
    if followup and lead.lead_status_id != followup.lead_status_id:
        old = lead.lead_status_id
        lead.lead_status_id = followup.lead_status_id
        db.add(LeadStatusHistory(
            lead_id=lead.lead_id,
            old_status_id=old,
            new_status_id=followup.lead_status_id,
            changed_by=actor_user_id,
            changed_at=datetime.now(timezone.utc),
            reason="Follow-up scheduled",
        ))
