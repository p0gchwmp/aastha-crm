import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.permissions import require_permission
from app.models.core import User
from app.models.finance import FinancialChangeRequest
from app.models.integration import AuditEvent

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/audit")
def audit_events(
    entity_type: str | None = None,
    action: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("AUDIT_VIEW")),
):
    stmt = select(AuditEvent).where(AuditEvent.organization_id == user.organization_id)
    if entity_type: stmt = stmt.where(AuditEvent.entity_type == entity_type)
    if action: stmt = stmt.where(AuditEvent.action == action)
    if actor_user_id: stmt = stmt.where(AuditEvent.actor_user_id == actor_user_id)
    rows = list(db.scalars(stmt.order_by(AuditEvent.occurred_at.desc()).limit(limit)).all())
    users = {u.user_id:u.name for u in db.scalars(select(User).where(User.organization_id==user.organization_id)).all()}
    return [{
        "audit_event_id":x.audit_event_id,"entity_type":x.entity_type,"entity_id":x.entity_id,"action":x.action,
        "actor_user_id":x.actor_user_id,"actor_name":users.get(x.actor_user_id),"before_data":x.before_data,"after_data":x.after_data,
        "reason":x.reason,"occurred_at":x.occurred_at,
    } for x in rows]


@router.get("/financial-change-requests")
def financial_change_requests(
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("FINANCE_CORRECT")),
):
    stmt = select(FinancialChangeRequest).where(FinancialChangeRequest.organization_id == user.organization_id)
    if status: stmt = stmt.where(FinancialChangeRequest.status == status)
    rows = list(db.scalars(stmt.order_by(FinancialChangeRequest.created_at.desc()).limit(300)).all())
    users = {u.user_id:u.name for u in db.scalars(select(User).where(User.organization_id==user.organization_id)).all()}
    return [{
        "change_request_id":x.change_request_id,"entity_type":x.entity_type,"entity_id":x.entity_id,"requested_change":x.requested_change,
        "requested_by":x.requested_by,"requested_by_name":users.get(x.requested_by),"status":x.status,"resolved_by":x.resolved_by,
        "resolved_by_name":users.get(x.resolved_by),"resolved_at":x.resolved_at,"created_at":x.created_at,
    } for x in rows]
