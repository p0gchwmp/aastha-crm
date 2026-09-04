import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.access import allowed_branch_ids, ensure_branch_access
from app.core.permissions import require_permission
from app.models.core import Branch, Doctor, User
from app.models.crm import Lead, LeadStatus, LeadStatusHistory
from app.models.scheduling import Appointment, AppointmentStatus, DoctorSchedule, ScheduleException
from app.schemas.scheduling import AppointmentCreate, AppointmentOut

router = APIRouter(prefix="/appointments", tags=["appointments"])
IST = ZoneInfo("Asia/Kolkata")


def _serialize(db: Session, item: Appointment):
    branch = db.get(Branch, item.branch_id)
    doctor = db.get(Doctor, item.doctor_id) if item.doctor_id else None
    status = db.get(AppointmentStatus, item.appointment_status_id)
    lead = db.get(Lead, item.lead_id) if item.lead_id else None
    return {
        "appointment_id": item.appointment_id,
        "branch_id": item.branch_id,
        "branch": branch.branch_name if branch else None,
        "doctor_id": item.doctor_id,
        "doctor": doctor.doctor_name if doctor else None,
        "lead_id": item.lead_id,
        "lead_name": lead.lead_name if lead else None,
        "patient_id": item.patient_id,
        "scheduled_start": item.scheduled_start,
        "scheduled_end": item.scheduled_end,
        "status": status.name if status else None,
        "status_code": status.code if status else None,
        "booked_via": item.booked_via,
        "row_version": item.row_version,
    }


def _local_bounds(target: date):
    start_local = datetime.combine(target, time.min, tzinfo=IST)
    end_local = datetime.combine(target, time.max, tzinfo=IST)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


@router.get("")
def list_appointments(
    on_date: date | None = Query(default=None),
    branch_id: uuid.UUID | None = None,
    patient_id: uuid.UUID | None = None,
    lead_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("APPOINTMENT_CREATE")),
):
    target = on_date or datetime.now(IST).date()
    start, end = _local_bounds(target)
    stmt = select(Appointment).where(Appointment.organization_id == user.organization_id, Appointment.scheduled_start.between(start, end))
    allowed = allowed_branch_ids(db, user)
    if branch_id:
        ensure_branch_access(db, user, branch_id)
        stmt = stmt.where(Appointment.branch_id == branch_id)
    elif allowed is not None:
        stmt = stmt.where(Appointment.branch_id.in_(allowed))
    if patient_id:
        stmt = stmt.where(Appointment.patient_id == patient_id)
    if lead_id:
        stmt = stmt.where(Appointment.lead_id == lead_id)
    rows = list(db.scalars(stmt.order_by(Appointment.scheduled_start)).all())
    return [_serialize(db, x) for x in rows]


@router.get("/availability")
def availability(
    branch_id: uuid.UUID,
    doctor_id: uuid.UUID,
    on_date: date,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("APPOINTMENT_CREATE")),
):
    ensure_branch_access(db, user, branch_id)
    doctor = db.get(Doctor, doctor_id)
    if not doctor or doctor.organization_id != user.organization_id:
        raise HTTPException(404, "Branch or Doctor not found")
    schedule = db.scalar(select(DoctorSchedule).where(
        DoctorSchedule.doctor_id == doctor_id,
        DoctorSchedule.branch_id == branch_id,
        DoctorSchedule.day_of_week == on_date.weekday(),
        DoctorSchedule.active.is_(True),
        DoctorSchedule.effective_from <= on_date,
        (DoctorSchedule.effective_until.is_(None) | (DoctorSchedule.effective_until >= on_date)),
    ).order_by(DoctorSchedule.effective_from.desc()).limit(1))
    if not schedule:
        return {"date": on_date, "slots": []}
    full_day_closed = db.scalar(select(ScheduleException.exception_id).where(
        ScheduleException.doctor_id == doctor_id,
        ScheduleException.branch_id == branch_id,
        ScheduleException.date == on_date,
        ScheduleException.exception_type.in_(["LEAVE", "HOLIDAY", "CLOSED"]),
        ScheduleException.start_time.is_(None),
    ).limit(1))
    if full_day_closed:
        return {"date": on_date, "slots": []}
    start_utc, end_utc = _local_bounds(on_date)
    appointments = list(db.execute(
        select(Appointment.scheduled_start, Appointment.scheduled_end)
        .join(AppointmentStatus, AppointmentStatus.appointment_status_id == Appointment.appointment_status_id)
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.branch_id == branch_id,
            Appointment.scheduled_start.between(start_utc, end_utc),
            AppointmentStatus.code.not_in(["CANCELLED", "NO_SHOW"]),
        )
    ).all())
    exceptions = list(db.scalars(select(ScheduleException).where(
        ScheduleException.doctor_id == doctor_id,
        ScheduleException.branch_id == branch_id,
        ScheduleException.date == on_date,
        ScheduleException.start_time.is_not(None),
        ScheduleException.end_time.is_not(None),
    )).all())
    slots=[]
    cursor=datetime.combine(on_date,schedule.start_time,tzinfo=IST)
    end=datetime.combine(on_date,schedule.end_time,tzinfo=IST)
    delta=timedelta(minutes=schedule.slot_duration_minutes)
    while cursor+delta <= end:
        slot_end=cursor+delta
        s_utc=cursor.astimezone(timezone.utc); e_utc=slot_end.astimezone(timezone.utc)
        blocked_by_appt=any(a_start < e_utc and a_end > s_utc for a_start,a_end in appointments)
        blocked_by_exception=any(
            datetime.combine(on_date,x.start_time,tzinfo=IST) < slot_end and datetime.combine(on_date,x.end_time,tzinfo=IST) > cursor
            for x in exceptions
        )
        if not blocked_by_appt and not blocked_by_exception:
            slots.append({"start": cursor.isoformat(), "end": slot_end.isoformat()})
        cursor=slot_end
    return {"date": on_date, "slot_duration_minutes": schedule.slot_duration_minutes, "slots": slots}


@router.post("", response_model=AppointmentOut)
def create(payload: AppointmentCreate, db: Session = Depends(get_db), user: User = Depends(require_permission("APPOINTMENT_CREATE"))):
    if payload.organization_id != user.organization_id:
        raise HTTPException(403, "Cannot book appointment for another organization")
    ensure_branch_access(db, user, payload.branch_id)
    if payload.lead_id:
        lead = db.get(Lead, payload.lead_id)
        if not lead or lead.organization_id != user.organization_id:
            raise HTTPException(400, "Lead not found")
    if payload.doctor_id:
        overlap = db.scalar(
            select(Appointment.appointment_id)
            .join(AppointmentStatus, AppointmentStatus.appointment_status_id == Appointment.appointment_status_id)
            .where(
                Appointment.doctor_id == payload.doctor_id,
                Appointment.branch_id == payload.branch_id,
                AppointmentStatus.code.not_in(["CANCELLED", "NO_SHOW"]),
                Appointment.scheduled_start < payload.scheduled_end,
                Appointment.scheduled_end > payload.scheduled_start,
            )
            .limit(1)
        )
        if overlap:
            raise HTTPException(409, "Doctor already has an overlapping appointment")
    item = Appointment(**payload.model_dump(), created_by=user.user_id)
    db.add(item); db.flush()
    if payload.lead_id:
        booked = db.scalar(select(LeadStatus).where(LeadStatus.code == "APPOINTMENT_BOOKED"))
        lead = db.get(Lead, payload.lead_id)
        if booked and lead.lead_status_id != booked.lead_status_id:
            old = lead.lead_status_id
            lead.lead_status_id = booked.lead_status_id
            lead.updated_by = user.user_id
            lead.row_version += 1
            db.add(LeadStatusHistory(lead_id=lead.lead_id, old_status_id=old, new_status_id=booked.lead_status_id, changed_by=user.user_id, changed_at=datetime.now(timezone.utc), reason="Appointment booked"))
    db.commit(); db.refresh(item)
    return item


@router.patch("/{appointment_id}/status")
def update_status(appointment_id: uuid.UUID, status_code: str, row_version: int, db: Session = Depends(get_db), user: User = Depends(require_permission("APPOINTMENT_EDIT"))):
    item = db.get(Appointment, appointment_id)
    if not item or item.organization_id != user.organization_id:
        raise HTTPException(404, "Appointment not found")
    ensure_branch_access(db, user, item.branch_id)
    if item.row_version != row_version:
        raise HTTPException(409, "Appointment was updated by another user")
    status = db.scalar(select(AppointmentStatus).where(AppointmentStatus.code == status_code))
    if not status:
        raise HTTPException(400, "Unknown appointment status")
    item.appointment_status_id = status.appointment_status_id
    item.row_version += 1
    db.commit(); db.refresh(item)
    return _serialize(db, item)
