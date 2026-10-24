"""Assigned Doctor consultations. Clinical content never enters Reception serializers."""
import hashlib
import uuid
from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.access import allowed_branch_ids, ensure_branch_access
from app.core.permissions import require_permission
from app.models.core import Doctor, User
from app.models.patient import Patient
from app.models.clinical import Visit, VisitType, VisitStatus, ConsultationNote, ConsultationNoteRevision
from app.api.routes.visits import _serialize, _local_bounds
from app.services.diagnoses import visit_diagnoses, set_visit_diagnoses

router = APIRouter(prefix="/doctor-consultations", tags=["doctor-consultations"])
FIELDS = ("history", "examination", "assessment", "plan", "followup_advice", "followup_date")


class DiagnosisSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    diagnosis_id: uuid.UUID
    is_primary: bool = False


class NoteAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    diagnoses: list[DiagnosisSelection] | None = Field(default=None, max_length=20)
    request_id: uuid.UUID
    row_version: int = Field(ge=1)
    identity_confirmed: bool = False
    patient_version: int | None = None
    history: str | None = Field(default=None, max_length=20000)
    examination: str | None = Field(default=None, max_length=20000)
    assessment: str | None = Field(default=None, max_length=20000)
    plan: str | None = Field(default=None, max_length=20000)
    followup_advice: str | None = Field(default=None, max_length=20000)
    followup_date: date | None = None


def doctor_for(db, user):
    rows = db.scalars(select(Doctor).where(Doctor.user_id == user.user_id, Doctor.organization_id == user.organization_id, Doctor.active.is_(True))).all()
    if len(rows) != 1:
        raise HTTPException(403, "One active linked Doctor profile is required")
    return rows[0]


def context(db, user, visit_id, lock=False):
    initial = db.get(Visit, visit_id)
    if not initial:
        raise HTTPException(404, "Visit not found")
    patient = db.scalar(select(Patient).where(Patient.patient_id == initial.patient_id).execution_options(populate_existing=True).with_for_update() if lock else select(Patient).where(Patient.patient_id == initial.patient_id))
    if not patient or patient.organization_id != user.organization_id:
        raise HTTPException(404, "Visit not found")
    ensure_branch_access(db, user, initial.branch_id)
    doctor = doctor_for(db, user)
    stmt = select(Visit).where(Visit.visit_id == visit_id).execution_options(populate_existing=True)
    visit = db.scalar(stmt.with_for_update() if lock else stmt)
    if visit.doctor_id != doctor.doctor_id:
        raise HTTPException(403, "This Visit is assigned to another Doctor")
    if db.get(VisitType, visit.visit_type_id).code == "PROCEDURE":
        raise HTTPException(409, "Use the Procedure Session workflow for this Visit")
    return visit, patient, doctor


def note_data(note):
    if not note:
        return None
    return {**{key: getattr(note, key) for key in FIELDS}, "row_version": note.row_version, "updated_at": note.updated_at}


def detail_data(db, visit, patient):
    return {"diagnoses": visit_diagnoses(db, visit.visit_id), "visit": _serialize(db, visit), "patient": {"full_name": patient.full_name, "uhid": patient.uhid, "gender": patient.gender, "dob": patient.dob, "age_years": patient.age_years, "row_version": patient.row_version}, "note": note_data(db.scalar(select(ConsultationNote).where(ConsultationNote.visit_id == visit.visit_id)))}


@router.get("")
def queue(on_date: date, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_permission("CONSULTATION_CLINICAL"))):
    doctor = doctor_for(db, user)
    start, end = _local_bounds(on_date)
    stmt = select(Visit).join(Patient).join(VisitType).where(Patient.organization_id == user.organization_id, Visit.doctor_id == doctor.doctor_id, Visit.checkin_at.between(start, end), VisitType.code != "PROCEDURE")
    allowed = allowed_branch_ids(db, user)
    if allowed is not None:
        stmt = stmt.where(Visit.branch_id.in_(allowed))
    return [_serialize(db, v) for v in db.scalars(stmt.order_by(Visit.checkin_at, Visit.visit_id).offset(offset).limit(limit)).all()]


@router.get("/{visit_id}")
def detail(visit_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_permission("CONSULTATION_CLINICAL"))):
    visit, patient, _ = context(db, user, visit_id)
    result = detail_data(db, visit, patient)
    stmt = select(Visit).join(Patient).where(Visit.patient_id == patient.patient_id, Patient.organization_id == user.organization_id, Visit.visit_id != visit_id)
    allowed = allowed_branch_ids(db, user)
    if allowed is not None:
        stmt = stmt.where(Visit.branch_id.in_(allowed))
    from app.api.routes.clinical_preparations import get_preparation, snapshot
    preparation = get_preparation(db, visit_id)
    result["preparation"] = snapshot(db, preparation)
    from app.models.preparation import PreparationRevision
    result["preparation_revisions"] = [{"action":r.action,"occurred_at":r.occurred_at,"snapshot":r.snapshot} for r in db.scalars(select(PreparationRevision).where(PreparationRevision.preparation_id==preparation.preparation_id).order_by(PreparationRevision.occurred_at)).all()] if preparation else []
    result["previous_visits"] = [{"visit": _serialize(db, v), "note": note_data(db.scalar(select(ConsultationNote).where(ConsultationNote.visit_id == v.visit_id))), "diagnoses": visit_diagnoses(db, v.visit_id)} for v in db.scalars(stmt.order_by(Visit.checkin_at.desc()).limit(100)).all()]
    note = db.scalar(select(ConsultationNote).where(ConsultationNote.visit_id == visit_id))
    result["revisions"] = [{"action": r.action, "occurred_at": r.occurred_at, "snapshot": r.snapshot} for r in db.scalars(select(ConsultationNoteRevision).where(ConsultationNoteRevision.note_id == note.note_id).order_by(ConsultationNoteRevision.occurred_at)).all()] if note else []
    return result




from app.api.routes.clinical_preparations import Request as PreparationReviewRequest

@router.post("/{visit_id}/review-preparation")
def review_preparation(visit_id: uuid.UUID, payload: PreparationReviewRequest, db: Session=Depends(get_db), user: User=Depends(require_permission("CONSULTATION_CLINICAL"))):
    from app.api.routes.clinical_preparations import review
    return review(visit_id, payload, db, user)


from app.api.routes.clinical_preparations import ReturnRequest as PreparationReturnRequest

@router.post("/{visit_id}/return-preparation")
def return_preparation(visit_id: uuid.UUID, payload: PreparationReturnRequest, db: Session=Depends(get_db), user: User=Depends(require_permission("CONSULTATION_CLINICAL"))):
    from app.api.routes.clinical_preparations import return_for_changes
    return return_for_changes(visit_id, payload, db, user)


@router.post("/{visit_id}/{action}")
def mutate(visit_id: uuid.UUID, action: str, payload: NoteAction, db: Session = Depends(get_db), user: User = Depends(require_permission("CONSULTATION_CLINICAL"))):
    if action not in {"start", "save", "complete"}:
        raise HTTPException(404, "Unknown consultation action")
    try:
        visit, patient, doctor = context(db, user, visit_id, lock=True)
        digest = hashlib.sha256((str(visit_id) + action + payload.model_dump_json()).encode()).hexdigest()
        old = db.scalar(select(ConsultationNoteRevision).where(ConsultationNoteRevision.actor_user_id == user.user_id, ConsultationNoteRevision.request_id == payload.request_id))
        if old:
            if old.request_hash != digest:
                raise HTTPException(409, "Request identifier was already used for different data")
            result = detail_data(db, visit, patient)
            db.commit()
            return result
        if visit.row_version != payload.row_version:
            raise HTTPException(409, "Visit changed. Refresh before saving")
        status = db.get(VisitStatus, visit.visit_status_id).code
        now = datetime.now(timezone.utc)
        note = db.scalar(select(ConsultationNote).where(ConsultationNote.visit_id == visit_id).with_for_update())
        if action == "start":
            if status not in {"WAITING", "CREATED"} or note:
                raise HTTPException(409, "Consultation has already started or cannot be started")
            if not payload.identity_confirmed or payload.patient_version != patient.row_version:
                raise HTTPException(409, "Confirm current Patient name, age/gender and UHID first")
            note = ConsultationNote(visit_id=visit_id, doctor_id=doctor.doctor_id, identity_patient_version=patient.row_version, identity_confirmed_at=now)
            db.add(note)
            visit.started_at = now
        elif status != "IN_PROGRESS" or not note:
            raise HTTPException(409, "Only an in-progress consultation can be saved or completed")
        else:
            for key in FIELDS:
                setattr(note, key, getattr(payload, key))
            note.row_version += 1
        if action == "start" and payload.diagnoses:
            raise HTTPException(409, "Start the consultation before recording diagnoses")
        if action != "start":
            set_visit_diagnoses(db, visit, doctor, user.organization_id, payload.diagnoses)
        if action == "complete":
            from app.api.routes.clinical_preparations import get_preparation
            preparation = get_preparation(db, visit_id, True)
            if preparation and preparation.state != "REVIEWED":
                raise HTTPException(409, "Review the submitted Assistant preparation before completing this consultation")
        target = "COMPLETED" if action == "complete" else "IN_PROGRESS"
        next_status = db.scalar(select(VisitStatus).where(VisitStatus.code == target))
        if not next_status:
            raise HTTPException(409, "Required Visit status is not configured")
        visit.visit_status_id = next_status.visit_status_id
        if action == "complete":
            visit.completed_at = now
        visit.row_version += 1
        visit.updated_by = user.user_id
        db.flush()
        snapshot = {key: (getattr(note, key).isoformat() if isinstance(getattr(note, key), date) else getattr(note, key)) for key in FIELDS}
        snapshot["diagnoses"] = [{**d, "diagnosis_id": str(d["diagnosis_id"])} for d in visit_diagnoses(db, visit_id)]
        snapshot.update(visit_version=visit.row_version, note_version=note.row_version, status=target)
        db.add(ConsultationNoteRevision(note_id=note.note_id, actor_user_id=user.user_id, request_id=payload.request_id, request_hash=digest, action=action.upper(), occurred_at=now, snapshot=snapshot))
        from app.services.audit import log_audit
        log_audit(db, organization_id=user.organization_id, entity_type="VISIT", entity_id=visit_id, action="CONSULTATION_"+action.upper(), actor_user_id=user.user_id, after_data={"visit_version": visit.row_version, "note_version": note.row_version})
        db.commit()
        return detail_data(db, visit, patient)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Request was already used or the consultation changed. Refresh before saving") from exc
    except Exception:
        db.rollback()
        raise
