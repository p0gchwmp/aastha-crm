import uuid
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.access import allowed_branch_ids, ensure_branch_access
from app.core.permissions import require_permission
from app.models.clinical import ChiefComplaint, Visit, VisitComplaint, VisitStatus, VisitType
from app.models.core import Branch, Doctor, User
from app.models.patient import Patient
from app.models.scheduling import Appointment, AppointmentStatus
from app.schemas.clinical import VisitCreate, VisitOut
from app.schemas.procedures import ProcedureOrderFromVisitRequest
from app.services import procedures as procedure_service

router = APIRouter(prefix="/visits", tags=["visits"])
IST = ZoneInfo("Asia/Kolkata")


def _local_bounds(target: date):
    start = datetime.combine(target, time.min, tzinfo=IST).astimezone(timezone.utc)
    end = datetime.combine(target, time.max, tzinfo=IST).astimezone(timezone.utc)
    return start, end


def _serialize(db: Session, visit: Visit) -> dict:
    patient = db.get(Patient, visit.patient_id)
    branch = db.get(Branch, visit.branch_id)
    doctor = db.get(Doctor, visit.doctor_id) if visit.doctor_id else None
    visit_type = db.get(VisitType, visit.visit_type_id)
    status = db.get(VisitStatus, visit.visit_status_id)
    complaints = list(
        db.execute(
            select(ChiefComplaint.chief_complaint_id, ChiefComplaint.name)
            .join(VisitComplaint, VisitComplaint.chief_complaint_id == ChiefComplaint.chief_complaint_id)
            .where(VisitComplaint.visit_id == visit.visit_id)
        ).all()
    )
    return {
        "visit_id": visit.visit_id,
        "patient_id": visit.patient_id,
        "patient_name": patient.full_name if patient else None,
        "uhid": patient.uhid if patient else None,
        "appointment_id": visit.appointment_id,
        "branch_id": visit.branch_id,
        "branch": branch.branch_name if branch else None,
        "doctor_id": visit.doctor_id,
        "doctor": doctor.doctor_name if doctor else None,
        "visit_type_id": visit.visit_type_id,
        "visit_type": visit_type.name if visit_type else None,
        "visit_type_code": visit_type.code if visit_type else None,
        "visit_status_id": visit.visit_status_id,
        "status": status.name if status else None,
        "status_code": status.code if status else None,
        "checkin_at": visit.checkin_at,
        "started_at": visit.started_at,
        "completed_at": visit.completed_at,
        "followup_at": visit.followup_at,
        "complaints": [{"id": x[0], "name": x[1]} for x in complaints],
        "row_version": visit.row_version,
    }


@router.get("")
def list_visits(
    on_date: date | None = Query(default=None),
    patient_id: uuid.UUID | None = None,
    branch_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=250),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PATIENT_VIEW")),
):
    stmt = select(Visit).join(Patient, Patient.patient_id == Visit.patient_id).where(Patient.organization_id == user.organization_id)
    if on_date:
        start, end = _local_bounds(on_date)
        stmt = stmt.where(Visit.checkin_at.between(start, end))
    if patient_id:
        stmt = stmt.where(Visit.patient_id == patient_id)
    allowed = allowed_branch_ids(db, user)
    if branch_id:
        ensure_branch_access(db, user, branch_id)
        stmt = stmt.where(Visit.branch_id == branch_id)
    elif allowed is not None:
        stmt = stmt.where(Visit.branch_id.in_(allowed))
    rows = list(db.scalars(stmt.order_by(Visit.checkin_at.desc()).limit(limit)).all())
    return [_serialize(db, x) for x in rows]


@router.post("", response_model=VisitOut)
def create(
    payload: VisitCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("VISIT_CREATE")),
):
    if not payload.identity_confirmed:
        raise HTTPException(409, "Confirm Name + Age/Gender + UHID before creating the Visit")
    patient = db.get(Patient, payload.patient_id)
    if not patient or patient.organization_id != user.organization_id:
        raise HTTPException(400, "Patient not found")
    ensure_branch_access(db, user, payload.branch_id)
    if payload.doctor_id:
        doctor = db.get(Doctor, payload.doctor_id)
        if not doctor or doctor.organization_id != user.organization_id:
            raise HTTPException(400, "Doctor not found")
    if not db.get(VisitType, payload.visit_type_id):
        raise HTTPException(400, "Visit Type not found")
    if not db.get(VisitStatus, payload.visit_status_id):
        raise HTTPException(400, "Visit Status not found")
    if payload.appointment_id:
        appointment = db.get(Appointment, payload.appointment_id)
        if not appointment or appointment.organization_id != user.organization_id:
            raise HTTPException(400, "Appointment not found")
        if appointment.patient_id and appointment.patient_id != payload.patient_id:
            raise HTTPException(409, "Appointment belongs to another Patient")
        appointment.patient_id = payload.patient_id
        checked_in = db.scalar(select(AppointmentStatus).where(AppointmentStatus.code == "CHECKED_IN"))
        if checked_in:
            appointment.appointment_status_id = checked_in.appointment_status_id
            appointment.row_version += 1
    for complaint_id in payload.chief_complaint_ids:
        if not db.get(ChiefComplaint, complaint_id):
            raise HTTPException(400, "Chief Complaint not found")
    data = payload.model_dump(exclude={"chief_complaint_ids", "identity_confirmed"})
    visit = Visit(**data, created_by=user.user_id, updated_by=user.user_id)
    db.add(visit)
    db.flush()
    for complaint_id in payload.chief_complaint_ids:
        db.add(VisitComplaint(visit_id=visit.visit_id, chief_complaint_id=complaint_id))
    db.commit()
    db.refresh(visit)
    return visit


@router.get("/{visit_id}")
def detail(
    visit_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PATIENT_VIEW")),
):
    visit = db.get(Visit, visit_id)
    if not visit:
        raise HTTPException(404, "Visit not found")
    patient = db.get(Patient, visit.patient_id)
    if not patient or patient.organization_id != user.organization_id:
        raise HTTPException(404, "Visit not found")
    ensure_branch_access(db, user, visit.branch_id)
    return _serialize(db, visit)


@router.post("/{visit_id}/procedure-orders")
def create_procedure_order(
    visit_id: uuid.UUID,
    payload: ProcedureOrderFromVisitRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PROCEDURE_ORDER_CREATE")),
):
    order = procedure_service.create_order(
        db, user=user, visit_id=visit_id, service_id=payload.service_id, notes=payload.notes
    )
    return {"procedure_order_id": order.procedure_order_id}
