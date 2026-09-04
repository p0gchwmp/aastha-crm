from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.permissions import require_permission
from app.models.core import User
from app.models.crm import Lead
from app.models.scheduling import Appointment
from app.models.clinical import Visit
from app.models.finance import ConsultationPayment

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _utc_day_bounds(now: datetime | None = None):
    ist = ZoneInfo("Asia/Kolkata")
    local_now = (now or datetime.now(timezone.utc)).astimezone(ist)
    local_start = datetime.combine(local_now.date(), time.min, tzinfo=ist)
    local_end = local_start + timedelta(days=1)
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)


@router.get("/summary")
def summary(db: Session = Depends(get_db), user: User = Depends(require_permission("LEAD_VIEW"))):
    start, end = _utc_day_bounds()
    leads_today = db.scalar(select(func.count()).select_from(Lead).where(Lead.organization_id == user.organization_id, Lead.created_at.between(start, end))) or 0
    appointments_today = db.scalar(select(func.count()).select_from(Appointment).where(Appointment.organization_id == user.organization_id, Appointment.scheduled_start.between(start, end))) or 0
    visits_today = db.scalar(select(func.count()).select_from(Visit).where(Visit.checkin_at.between(start, end))) or 0
    consultation_collection = db.scalar(select(func.coalesce(func.sum(ConsultationPayment.amount), 0)).where(ConsultationPayment.received_at.between(start, end), ConsultationPayment.payment_status == "COMPLETED")) or 0
    followups_due = db.scalar(select(func.count()).select_from(Lead).where(Lead.organization_id == user.organization_id, Lead.dnc.is_(False), Lead.next_followup_at <= end, Lead.next_followup_at.is_not(None))) or 0
    return {
        "leads_today": leads_today,
        "appointments_today": appointments_today,
        "visits_today": visits_today,
        "consultation_collection": str(consultation_collection),
        "followups_due": followups_due,
    }
