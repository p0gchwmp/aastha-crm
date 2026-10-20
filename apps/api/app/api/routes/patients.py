import uuid
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.access import ensure_branch_access
from app.core.permissions import require_permission
from app.models.clinical import Visit, VisitStatus, VisitType
from app.models.core import Branch, Doctor, User
from app.models.patient import Patient
from app.schemas.patient import PatientCreate, PatientDetailOut, PatientOut, PatientSearchOut, PatientUpdate
from app.services.patients import (
    create_patient,
    current_fiscal_year,
    get_patient_detail,
    search_patient_matches,
    search_patients,
)
from app.services.utils import normalize_mobile
from app.models.patient import PatientAddress, PatientContact

router = APIRouter(prefix="/patients", tags=["patients"])


def _visit_summary(db: Session, visit: Visit) -> dict:
    visit_type = db.get(VisitType, visit.visit_type_id)
    status = db.get(VisitStatus, visit.visit_status_id)
    doctor = db.get(Doctor, visit.doctor_id) if visit.doctor_id else None
    branch = db.get(Branch, visit.branch_id)
    return {
        "visit_id": visit.visit_id,
        "checkin_at": visit.checkin_at,
        "branch_id": visit.branch_id,
        "branch": branch.branch_name if branch else None,
        "doctor_id": visit.doctor_id,
        "doctor": doctor.doctor_name if doctor else None,
        "visit_type": visit_type.name if visit_type else None,
        "visit_type_code": visit_type.code if visit_type else None,
        "status": status.name if status else None,
        "status_code": status.code if status else None,
        "followup_at": visit.followup_at,
    }


@router.post("", response_model=PatientOut)
def create(
    payload: PatientCreate,
    fiscal_year: str | None = Query(default=None, examples=["2026-27"]),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PATIENT_CREATE")),
):
    if payload.organization_id != user.organization_id:
        raise HTTPException(403, "Cannot register Patient for another organization")
    branch = ensure_branch_access(db, user, payload.registration_branch_id)
    candidates = search_patient_matches(
        db,
        organization_id=user.organization_id,
        name=payload.full_name,
        mobile=payload.mobile,
        dob=payload.dob,
        gender=payload.gender,
    )
    if candidates and not payload.duplicate_override_confirmed:
        raise HTTPException(
            409,
            detail={
                "code": "POSSIBLE_DUPLICATE_PATIENT",
                "message": "Possible existing Patient found. Review matches or explicitly confirm a separate Patient.",
                "candidates": [{"patient_id": str(x["patient_id"]), "uhid": x["uhid"], "full_name": x["full_name"]} for x in candidates[:10]],
            },
        )
    patient = create_patient(
        db,
        payload=payload,
        actor_user_id=user.user_id,
        fiscal_year=fiscal_year or current_fiscal_year(),
        branch_code=branch.branch_code,
    )
    db.commit()
    db.refresh(patient)
    return patient


@router.get("/search", response_model=list[PatientSearchOut])
def search(
    q: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PATIENT_VIEW")),
):
    return search_patients(db, organization_id=user.organization_id, q=q)


@router.get("/match", response_model=list[PatientSearchOut])
def match(
    name: str | None = None,
    mobile: str | None = None,
    dob: date | None = None,
    gender: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PATIENT_VIEW")),
):
    return search_patient_matches(
        db,
        organization_id=user.organization_id,
        name=name,
        mobile=mobile,
        dob=dob,
        gender=gender,
    )


@router.get("/{patient_id}", response_model=PatientDetailOut)
def detail(
    patient_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PATIENT_VIEW")),
):
    patient = db.get(Patient, patient_id)
    if not patient or patient.organization_id != user.organization_id:
        raise HTTPException(404, "Patient not found")
    return get_patient_detail(db, patient=patient)


@router.get("/{patient_id}/visits")
def patient_visits(
    patient_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PATIENT_VIEW")),
):
    patient = db.get(Patient, patient_id)
    if not patient or patient.organization_id != user.organization_id:
        raise HTTPException(404, "Patient not found")
    visits = list(
        db.scalars(
            select(Visit)
            .where(Visit.patient_id == patient_id)
            .order_by(Visit.checkin_at.desc())
            .limit(limit)
        ).all()
    )
    return [_visit_summary(db, v) for v in visits]


@router.patch("/{patient_id}", response_model=PatientDetailOut)
def update_patient(
    patient_id: uuid.UUID,
    payload: PatientUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PATIENT_EDIT")),
):
    patient = db.get(Patient, patient_id)
    if not patient or patient.organization_id != user.organization_id:
        raise HTTPException(404, "Patient not found")
    if patient.row_version != payload.row_version:
        raise HTTPException(409, "Patient was updated by another user. Review the latest record.")

    for field in ["full_name", "gender", "dob", "dob_is_estimated", "profile_status"]:
        value = getattr(payload, field)
        if value is not None:
            setattr(patient, field, value)

    def upsert_contact(contact_type: str, value: str | None, primary: bool):
        if value is None:
            return
        contact = db.scalar(
            select(PatientContact)
            .where(PatientContact.patient_id == patient_id, PatientContact.contact_type == contact_type)
            .order_by(PatientContact.is_primary.desc())
            .limit(1)
        )
        if contact:
            contact.contact_value = value
            contact.normalized_value = normalize_mobile(value)
        else:
            db.add(PatientContact(patient_id=patient_id, contact_type=contact_type, contact_value=value, normalized_value=normalize_mobile(value), is_primary=primary))

    upsert_contact("MOBILE", payload.mobile, True)
    upsert_contact("ALTERNATE_MOBILE", payload.alternate_mobile, False)

    if any(x is not None for x in [payload.region_id, payload.district_id, payload.locality_id, payload.address_line]):
        address = db.scalar(select(PatientAddress).where(PatientAddress.patient_id == patient_id, PatientAddress.is_primary.is_(True)).limit(1))
        if not address:
            address = PatientAddress(patient_id=patient_id, is_primary=True)
            db.add(address)
        if payload.region_id is not None:
            address.region_id = payload.region_id
        if payload.district_id is not None:
            address.district_id = payload.district_id
        if payload.locality_id is not None:
            address.locality_id = payload.locality_id
        if payload.address_line is not None:
            address.address_line = payload.address_line

    patient.updated_by = user.user_id
    patient.row_version += 1
    db.commit(); db.refresh(patient)
    return get_patient_detail(db, patient=patient)
