from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.permissions import require_permission
from app.models.core import User
from app.models.crm import Lead, LeadContact
from app.services.dnc import apply_dnc_export_boundary

router = APIRouter(prefix="/external", tags=["external-integrations"])


@router.get("/leads")
def outbound_leads(
    export_purpose: str = Query(...),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("LEAD_EXPORT")),
):
    stmt = select(Lead).order_by(Lead.updated_at.desc()).limit(limit)
    stmt = apply_dnc_export_boundary(stmt, export_purpose)
    leads = list(db.scalars(stmt).all())
    return [
        {
            "lead_id": x.lead_id,
            "lead_name": x.lead_name,
            "concern_text": x.concern_text,
            "dnc": x.dnc,
            "next_followup_at": x.next_followup_at,
        }
        for x in leads
    ]
