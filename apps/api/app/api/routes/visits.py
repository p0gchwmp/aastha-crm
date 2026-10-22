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
from app.schemas.clinical import VisitCreate, VisitOut, VisitDoctorAssign
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
        "identity_confirmed_at": visit.identity_confirmed_at,
    }


@router.get("")
def list_visits(
    on_date: date | None = Query(default=None),
    patient_id: uuid.UUID | None = None,
    branch_id: uuid.UUID | None = None,
    doctor_id: uuid.UUID | None = None,
    visit_type_id: uuid.UUID | None = None,
    status_id: uuid.UUID | None = None,
    offset: int = Query(default=0, ge=0),
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
    if doctor_id: stmt = stmt.where(Visit.doctor_id == doctor_id)
    if visit_type_id: stmt = stmt.where(Visit.visit_type_id == visit_type_id)
    if status_id: stmt = stmt.where(Visit.visit_status_id == status_id)
    allowed = allowed_branch_ids(db, user)
    if branch_id:
        ensure_branch_access(db, user, branch_id)
        stmt = stmt.where(Visit.branch_id == branch_id)
    elif allowed is not None:
        stmt = stmt.where(Visit.branch_id.in_(allowed))
    rows = list(db.scalars(stmt.order_by(Visit.checkin_at.desc(), Visit.visit_id).offset(offset).limit(limit)).all())
    return [_serialize(db, x) for x in rows]


@router.post("", response_model=VisitOut)
def create(
    payload: VisitCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("VISIT_CREATE")),
):
    from app.services.visits import create_visit
    return create_visit(db, user=user, payload=payload)


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


@router.patch("/{visit_id}/doctor")
def assign_doctor(visit_id: uuid.UUID, payload: VisitDoctorAssign,
                  db: Session = Depends(get_db), user: User = Depends(require_permission("VISIT_EDIT"))):
    from app.services.consultation import lock_context
    from app.models.finance import ConsultationBill, ConsultationClearance
    from app.services.audit import log_audit
    try:
        visit,patient=lock_context(db,visit_id=visit_id)
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from exc
    if patient.organization_id!=user.organization_id: raise HTTPException(404,"Visit not found")
    ensure_branch_access(db,user,visit.branch_id)
    if visit.row_version!=payload.row_version: raise HTTPException(409,"Visit changed. Refresh before assigning Doctor")
    if not payload.reason.strip(): raise HTTPException(422,"An assignment reason is required")
    doctor=db.get(Doctor,payload.doctor_id)
    if not doctor or doctor.organization_id!=user.organization_id or not doctor.active: raise HTTPException(400,"Active Doctor not found")
    if db.scalar(select(ConsultationBill).where(ConsultationBill.visit_id==visit_id)) or db.scalar(select(ConsultationClearance).where(ConsultationClearance.visit_id==visit_id)):
        raise HTTPException(409,"Doctor cannot change after consultation finance has started")
    if visit.appointment_id:
        appointment=db.get(Appointment,visit.appointment_id)
        if appointment and appointment.doctor_id!=payload.doctor_id: raise HTTPException(409,"Doctor must match the linked appointment")
    before=str(visit.doctor_id) if visit.doctor_id else None
    visit.doctor_id=payload.doctor_id;visit.updated_by=user.user_id;visit.row_version+=1
    log_audit(db,organization_id=user.organization_id,entity_type="VISIT",entity_id=visit_id,action="VISIT_DOCTOR_ASSIGNED",actor_user_id=user.user_id,before_data={"doctor_id":before},after_data={"doctor_id":str(payload.doctor_id)},reason=payload.reason.strip())
    db.commit();return _serialize(db,visit)
