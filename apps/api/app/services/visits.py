"""Transactional encounter creation. Patient identity and money stay separate."""
import hashlib
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import select
from app.core.access import ensure_branch_access
from app.models.core import User, Doctor
from app.models.patient import Patient
from app.models.clinical import Visit, VisitType, VisitStatus, ChiefComplaint, VisitComplaint
from app.models.scheduling import Appointment, AppointmentStatus
from app.services.audit import log_audit

IST = ZoneInfo("Asia/Kolkata")


def now():
    return datetime.now(timezone.utc)


def create_visit(db, *, user, payload):
    if not payload.identity_confirmed:
        raise HTTPException(409, "Confirm Name + Age/Gender + UHID before creating the Visit")
    ensure_branch_access(db, user, payload.branch_id)
    # Per-actor retry serialization, also protecting changed-payload retries.
    db.scalar(select(User).where(User.user_id == user.user_id).with_for_update())
    values = payload.model_dump(mode="json", exclude={"creation_request_id"})
    values["chief_complaint_ids"] = sorted(set(values["chief_complaint_ids"]))
    fingerprint = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
    saved = db.scalar(select(Visit).where(Visit.created_by == user.user_id, Visit.creation_request_id == payload.creation_request_id))
    if saved:
        if saved.creation_request_hash != fingerprint:
            raise HTTPException(409, "This Visit request was already saved with different details. Review Visit history")
        ensure_branch_access(db, user, saved.branch_id)
        return saved

    stamp = now()
    appointment = None
    if payload.appointment_id:
        appointment = db.scalar(select(Appointment).where(Appointment.appointment_id == payload.appointment_id).with_for_update().execution_options(populate_existing=True))
        if not appointment or appointment.organization_id != user.organization_id:
            raise HTTPException(404, "Appointment not found")
        ensure_branch_access(db, user, appointment.branch_id)
        if appointment.patient_id != payload.patient_id:
            raise HTTPException(409, "Appointment must already be linked to this verified Patient. Complete Patient registration first")
        if appointment.branch_id != payload.branch_id or appointment.doctor_id != payload.doctor_id:
            raise HTTPException(409, "Visit branch and doctor must match the selected appointment")
        if db.scalar(select(Visit.visit_id).where(Visit.appointment_id == appointment.appointment_id).limit(1)):
            raise HTTPException(409, "This appointment already has a Visit. Open Patient Visit history")
        if payload.appointment_row_version != appointment.row_version:
            raise HTTPException(409, "Appointment changed. Reopen New Visit and review the latest appointment")
        status = db.get(AppointmentStatus, appointment.appointment_status_id)
        if not status or status.code not in {"SCHEDULED", "CONFIRMED", "RESCHEDULED", "CHECKED_IN", "COMPLETED"}:
            raise HTTPException(409, "Cancelled, no-show or waitlisted appointments cannot create a Visit")
        start = appointment.scheduled_start
        if start.tzinfo is None: start = start.replace(tzinfo=timezone.utc)
        if start.astimezone(IST).date() != stamp.astimezone(IST).date():
            raise HTTPException(409, "Select today's appointment or create a walk-in Visit")

    patient = db.scalar(select(Patient).where(Patient.patient_id == payload.patient_id).with_for_update().execution_options(populate_existing=True))
    if not patient or patient.organization_id != user.organization_id:
        raise HTTPException(404, "Patient not found")
    if patient.row_version != payload.patient_row_version:
        raise HTTPException(409, "Patient details changed. Reopen New Visit and verify Name + Age/Gender + UHID again")
    if payload.doctor_id:
        doctor = db.scalar(select(Doctor).where(Doctor.doctor_id == payload.doctor_id).with_for_update().execution_options(populate_existing=True))
        if not doctor or doctor.organization_id != user.organization_id or not doctor.active:
            raise HTTPException(400, "Active Doctor not found")
        from app.services.clinical_team import ensure_doctor_branch
        ensure_doctor_branch(db, doctor, payload.branch_id)
    kind = db.get(VisitType, payload.visit_type_id)
    if not kind or not kind.active:
        raise HTTPException(400, "Active Visit Type not found")
    waiting = db.scalar(select(VisitStatus).where(VisitStatus.code == "WAITING"))
    if not waiting:
        raise HTTPException(503, "Waiting Visit status is not configured")
    for cid in set(payload.chief_complaint_ids):
        complaint = db.get(ChiefComplaint, cid)
        if not complaint or not complaint.active or complaint.merged_into_complaint_id or complaint.approval_status not in {"APPROVED", "PENDING"}:
            raise HTTPException(409, "A Chief Complaint changed or is unavailable. Reopen New Visit and choose the current complaint")
    visit = Visit(patient_id=patient.patient_id, appointment_id=payload.appointment_id,
                  branch_id=payload.branch_id, doctor_id=payload.doctor_id, visit_type_id=payload.visit_type_id,
                  visit_status_id=waiting.visit_status_id, checkin_at=stamp, created_by=user.user_id, updated_by=user.user_id,
                  creation_request_id=payload.creation_request_id, creation_request_hash=fingerprint,
                  identity_confirmed_at=stamp, identity_patient_version=patient.row_version)
    db.add(visit); db.flush()
    for cid in set(payload.chief_complaint_ids):
        db.add(VisitComplaint(visit_id=visit.visit_id, chief_complaint_id=cid))
    # Attendance belongs to Module 3. Creating an encounter must never rewind a
    # Completed appointment or change its Lead history without attendance action.
    log_audit(db, organization_id=user.organization_id, entity_type="VISIT", entity_id=visit.visit_id,
              action="VISIT_CREATED", actor_user_id=user.user_id,
              after_data={**values, "checkin_at":stamp.isoformat(), "status":"WAITING"})
    db.commit(); db.refresh(visit)
    return visit
