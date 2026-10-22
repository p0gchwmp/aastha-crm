import uuid
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.access import ensure_branch_access, allowed_branch_ids
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
    registration_retry, request_hash, validate_address_hierarchy,
)
from app.services.utils import normalize_mobile
from app.models.patient import PatientAddress, PatientContact
from app.services.audit import log_audit

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
    existing=registration_retry(db,payload=payload,user=user)
    if existing:
        return existing
    if payload.profile_status != "COMPLETE" or payload.legacy_patient_id:
        raise HTTPException(422,"Use staged legacy import for legacy Patient records")
    candidates = search_patient_matches(
        db,
        organization_id=user.organization_id,
        name=payload.full_name,
        mobile=payload.mobile,
        dob=payload.dob,
        gender=payload.gender,
        age_years=payload.age_years,locality_id=payload.locality_id,address_line=payload.address_line,
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
    patient.registration_request_id=payload.registration_request_id
    patient.registration_request_hash=request_hash(payload)
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
    age_years: int | None = Query(default=None,ge=0,le=130),
    locality_id: uuid.UUID | None = None,
    address_line: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PATIENT_VIEW")),
):
    return search_patient_matches(
        db,
        organization_id=user.organization_id,
        name=name,
        mobile=mobile,
        dob=dob,
        gender=gender,age_years=age_years,locality_id=locality_id,address_line=address_line,
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
    allowed = allowed_branch_ids(db, user)
    stmt = select(Visit).where(Visit.patient_id == patient_id)
    if allowed is not None:
        stmt = stmt.where(Visit.branch_id.in_(allowed))
    visits = list(db.scalars(stmt.order_by(Visit.checkin_at.desc(), Visit.visit_id).limit(limit)).all())
    from app.api.routes.visits import _serialize
    return [_serialize(db, v) for v in visits]



@router.patch("/{patient_id}", response_model=PatientDetailOut)
def update_patient(
    patient_id: uuid.UUID,
    payload: PatientUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PATIENT_EDIT")),
):
    patient = db.scalar(select(Patient).where(Patient.patient_id==patient_id).with_for_update().execution_options(populate_existing=True))
    if not patient or patient.organization_id != user.organization_id:
        raise HTTPException(404, "Patient not found")
    if not payload.reason.strip(): raise HTTPException(422,"A correction reason is required")
    if patient.row_version != payload.row_version:
        raise HTTPException(409, "Patient was updated by another user. Review the latest record.")

    before=get_patient_detail(db,patient=patient)
    from pydantic import ValidationError
    try:
        current=PatientCreate(organization_id=patient.organization_id,registration_branch_id=patient.registration_branch_id,
        full_name=payload.full_name if payload.full_name is not None else patient.full_name,
        gender=payload.gender if "gender" in payload.model_fields_set else patient.gender,
        dob=payload.dob if "dob" in payload.model_fields_set else patient.dob,
        age_years=payload.age_years if "age_years" in payload.model_fields_set else patient.age_years,
        mobile=payload.mobile,alternate_mobile=payload.alternate_mobile)
    except ValidationError as exc:
        raise HTTPException(422,"Invalid Patient details: " + "; ".join(e["msg"] for e in exc.errors()))
    patient.full_name=current.full_name
    patient.dob=current.dob;patient.age_years=current.age_years
    if "age_years" in payload.model_fields_set:
        from datetime import datetime
        from app.services.patients import IST
        patient.age_recorded_on=datetime.now(IST).date() if current.age_years is not None else None
    if payload.profile_status is not None and payload.profile_status not in {"COMPLETE","LEGACY_INCOMPLETE"}:
        raise HTTPException(422,"Invalid profile status")
    patient.gender=current.gender
    for field in ["dob_is_estimated", "profile_status"]:
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

    if any(x in payload.model_fields_set for x in ["region_id", "district_id", "locality_id", "address_line"]):
        address = db.scalar(select(PatientAddress).where(PatientAddress.patient_id == patient_id, PatientAddress.is_primary.is_(True)).limit(1))
        if not address:
            address = PatientAddress(patient_id=patient_id, is_primary=True)
            db.add(address)
        validate_address_hierarchy(db,
            region_id=payload.region_id if "region_id" in payload.model_fields_set else address.region_id,
            district_id=payload.district_id if "district_id" in payload.model_fields_set else address.district_id,
            locality_id=payload.locality_id if "locality_id" in payload.model_fields_set else address.locality_id)
        if "region_id" in payload.model_fields_set:
            address.region_id = payload.region_id
        if "district_id" in payload.model_fields_set:
            address.district_id = payload.district_id
        if "locality_id" in payload.model_fields_set:
            address.locality_id = payload.locality_id
        if "address_line" in payload.model_fields_set:
            address.address_line = payload.address_line

    patient.updated_by = user.user_id
    patient.row_version += 1
    db.flush()
    from fastapi.encoders import jsonable_encoder
    log_audit(db,organization_id=user.organization_id,entity_type="PATIENT",entity_id=patient.patient_id,
        action="PATIENT_UPDATED",actor_user_id=user.user_id,before_data=jsonable_encoder(before),
        after_data=jsonable_encoder(get_patient_detail(db,patient=patient)),reason=payload.reason.strip())
    db.commit(); db.refresh(patient)
    return get_patient_detail(db, patient=patient)
