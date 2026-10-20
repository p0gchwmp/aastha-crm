import uuid
import hashlib
import json
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.orm import Session
from app.models.clinical import Visit
from app.models.core import Branch, User, NumberSeries
from app.models.crm import Lead, LeadContact, LeadPatientLink, LeadStatus, LeadStatusHistory
from app.models.patient import District, Locality, Patient, PatientAddress, PatientContact, Region
from app.models.scheduling import Appointment
from app.services.number_series import allocate_number
from app.services.utils import normalize_mobile
from app.services.audit import log_audit

IST = ZoneInfo("Asia/Kolkata")


def current_fiscal_year(today: date | None = None) -> str:
    today = today or datetime.now(IST).date()
    start = today.year if today.month >= 4 else today.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def calculate_age(dob: date | None, on_date: date | None = None) -> int | None:
    if not dob:
        return None
    on_date = on_date or datetime.now(IST).date()
    return on_date.year - dob.year - ((on_date.month, on_date.day) < (dob.month, dob.day))


def _primary_contact(db: Session, patient_id: uuid.UUID, contact_type: str = "MOBILE") -> PatientContact | None:
    return db.scalar(
        select(PatientContact)
        .where(PatientContact.patient_id == patient_id, PatientContact.contact_type == contact_type)
        .order_by(PatientContact.is_primary.desc())
        .limit(1)
    )


def _primary_address(db: Session, patient_id: uuid.UUID) -> PatientAddress | None:
    return db.scalar(
        select(PatientAddress)
        .where(PatientAddress.patient_id == patient_id)
        .order_by(PatientAddress.is_primary.desc(), PatientAddress.created_at.desc())
        .limit(1)
    )


def _last_visit_at(db: Session, patient_id: uuid.UUID):
    return db.scalar(select(func.max(Visit.checkin_at)).where(Visit.patient_id == patient_id))


def _patient_summary(db: Session, patient: Patient, *, match_reasons: list[str] | None = None) -> dict:
    mobile = _primary_contact(db, patient.patient_id, "MOBILE")
    address = _primary_address(db, patient.patient_id)
    locality = db.get(Locality, address.locality_id) if address and address.locality_id else None
    district = db.get(District, address.district_id) if address and address.district_id else None
    area = locality.locality_name if locality else (district.name if district else None)
    return {
        "patient_id": patient.patient_id,
        "uhid": patient.uhid,
        "full_name": patient.full_name,
        "gender": patient.gender,
        "dob": patient.dob,
        "age": calculate_age(patient.dob) if patient.dob else patient.age_years,
        "dob_is_estimated": patient.dob_is_estimated,
        "age_is_estimated": patient.dob_is_estimated or (patient.dob is None and patient.age_years is not None),
        "age_recorded_on": patient.age_recorded_on,
        "primary_mobile": mobile.contact_value if mobile else None,
        "area": area,
        "last_visit_at": _last_visit_at(db, patient.patient_id),
        "registration_branch_id": patient.registration_branch_id,
        "profile_status": patient.profile_status,
        "row_version": patient.row_version,
        "match_reasons": match_reasons or [],
    }


def validate_address_hierarchy(
    db: Session,
    *,
    region_id: uuid.UUID | None,
    district_id: uuid.UUID | None,
    locality_id: uuid.UUID | None,
) -> None:
    region = db.get(Region, region_id) if region_id else None
    if region_id and (not region or region.status != "ACTIVE"):
        raise HTTPException(422, "Region not found or inactive")
    if district_id and not region_id:
        raise HTTPException(422, "Select Region before District")
    if locality_id and not district_id:
        raise HTTPException(422, "Select District before Locality")
    district = db.get(District, district_id) if district_id else None
    locality = db.get(Locality, locality_id) if locality_id else None
    if district_id and (not district or district.status != "ACTIVE"):
        raise HTTPException(400, "District not found")
    if locality_id and (not locality or locality.approval_status not in {"APPROVED", "PENDING"}):
        raise HTTPException(400, "Locality not found")
    if region_id and district and district.region_id != region_id:
        raise HTTPException(400, "District does not belong to selected Region")
    if district_id and locality and locality.district_id != district_id:
        raise HTTPException(400, "Locality does not belong to selected District")


def create_patient(
    db: Session,
    *,
    payload,
    actor_user_id: uuid.UUID | None,
    fiscal_year: str,
    branch_code: str,
) -> Patient:
    validate_address_hierarchy(
        db,
        region_id=payload.region_id,
        district_id=payload.district_id,
        locality_id=payload.locality_id,
    )
    uhid = allocate_number(
        db,
        organization_id=payload.organization_id,
        series_code="UHID",
        branch_id=None,
        fiscal_year=None,
        variables={"BRANCH": branch_code},
    )
    patient = Patient(
        organization_id=payload.organization_id,
        uhid=uhid,
        full_name=payload.full_name.strip(),
        gender=payload.gender,
        dob=payload.dob,
        dob_is_estimated=payload.dob_is_estimated,
        profile_status=payload.profile_status,
        registration_branch_id=payload.registration_branch_id,
        legacy_patient_id=payload.legacy_patient_id,
        age_years=getattr(payload,"age_years",None),
        age_recorded_on=datetime.now(IST).date() if getattr(payload,"age_years",None) is not None else None,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    db.add(patient)
    db.flush()
    if payload.mobile:
        db.add(
            PatientContact(
                patient_id=patient.patient_id,
                contact_type="MOBILE",
                contact_value=payload.mobile,
                normalized_value=normalize_mobile(payload.mobile),
                is_primary=True,
            )
        )
    if payload.alternate_mobile:
        db.add(
            PatientContact(
                patient_id=patient.patient_id,
                contact_type="ALTERNATE_MOBILE",
                contact_value=payload.alternate_mobile,
                normalized_value=normalize_mobile(payload.alternate_mobile),
                is_primary=False,
            )
        )
    if any([payload.region_id, payload.district_id, payload.locality_id, payload.address_line]):
        db.add(
            PatientAddress(
                patient_id=patient.patient_id,
                region_id=payload.region_id,
                district_id=payload.district_id,
                locality_id=payload.locality_id,
                address_line=payload.address_line,
                is_primary=True,
            )
        )
    log_audit(db, organization_id=patient.organization_id, entity_type="PATIENT", entity_id=patient.patient_id,
              action="PATIENT_REGISTERED", actor_user_id=actor_user_id,
              after_data={"uhid":patient.uhid,"full_name":patient.full_name,"registration_branch_id":str(patient.registration_branch_id),"duplicate_override_confirmed":getattr(payload,"duplicate_override_confirmed",False)})
    return patient


def request_hash(payload):
    data=payload.model_dump(mode="json")
    data.pop("registration_request_id",None)
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def registration_retry(db, *, payload, user):
    if not payload.identity_verified:
        raise HTTPException(422,"Confirm that registration details were verified")
    if not payload.registration_request_id:
        raise HTTPException(422,"Registration request ID is required for safe retries")
    # Serialize this user's retries before reading the saved response, including
    # concurrent requests that start before the original transaction commits.
    db.scalar(select(User).where(User.user_id==user.user_id).with_for_update())
    existing=db.scalar(select(Patient).where(Patient.organization_id==user.organization_id,Patient.created_by==user.user_id,Patient.registration_request_id==payload.registration_request_id))
    if existing and existing.registration_request_hash!=request_hash(payload):
        raise HTTPException(409,"This registration request was already used with different details. Reload the saved Patient.")
    return existing


def search_patient_matches(
    db: Session,
    *,
    organization_id: uuid.UUID,
    name: str | None = None,
    mobile: str | None = None,
    dob: date | None = None,
    gender: str | None = None,
    age_years: int | None = None,
    locality_id: uuid.UUID | None = None,
    address_line: str | None = None,
    limit: int = 20,
) -> list[dict]:
    normalized = normalize_mobile(mobile) if mobile else None
    same_mobile=select(PatientContact.patient_contact_id).where(PatientContact.patient_id==Patient.patient_id,PatientContact.normalized_value==normalized).exists()
    stmt = select(Patient).where(Patient.organization_id == organization_id)
    predicates = []
    if name and name.strip(): predicates.append(Patient.full_name.ilike(f"%{name.strip()}%"))
    if normalized: predicates.append(same_mobile)
    if dob: predicates.append(Patient.dob==dob)
    if address_line and address_line.strip():
        predicates.append(select(PatientAddress.patient_address_id).where(PatientAddress.patient_id==Patient.patient_id,func.lower(PatientAddress.address_line)==address_line.strip().lower()).exists())
    if not predicates: return []
    # Strong identity hints must not disappear behind recent broad name matches.
    stmt=stmt.where(or_(*predicates)).order_by(
        case((same_mobile,1),else_=0).desc(),
        case((func.lower(Patient.full_name)==(name or "").strip().lower(),1),else_=0).desc(),
        Patient.updated_at.desc()).limit(limit)
    rows=list(db.scalars(stmt).all())
    results = []
    for patient in rows:
        reasons: list[str] = []
        if name and patient.full_name.strip().casefold() == name.strip().casefold():
            reasons.append("Exact name")
        elif name and name.strip().casefold() in patient.full_name.strip().casefold():
            reasons.append("Similar name")
        if normalized:
            contacts = list(db.scalars(select(PatientContact).where(PatientContact.patient_id == patient.patient_id)).all())
            if any(c.normalized_value == normalized for c in contacts):
                reasons.append("Same mobile")
        if dob and patient.dob == dob:
            reasons.append("Same DOB")
        if age_years is not None and (calculate_age(patient.dob) if patient.dob else patient.age_years) == age_years:
            reasons.append("Same age")
        address=_primary_address(db,patient.patient_id)
        if address and locality_id and address.locality_id==locality_id:
            reasons.append("Same locality")
        if address and address_line and address.address_line and address_line.strip().casefold()==address.address_line.strip().casefold():
            reasons.append("Same address")
        if gender and patient.gender and patient.gender.casefold() == gender.casefold():
            reasons.append("Same gender")
        results.append(_patient_summary(db, patient, match_reasons=reasons))
    return results


def search_patients(db: Session, *, organization_id: uuid.UUID, q: str) -> list[dict]:
    normalized = normalize_mobile(q)
    stmt = (
        select(Patient)
        .distinct()
        .outerjoin(PatientContact, PatientContact.patient_id == Patient.patient_id)
        .where(
            Patient.organization_id == organization_id,
            or_(
                Patient.uhid.ilike(f"%{q}%"),
                Patient.full_name.ilike(f"%{q}%"),
                PatientContact.normalized_value == normalized,
            ),
        )
        .order_by(Patient.updated_at.desc())
        .limit(30)
    )
    return [_patient_summary(db, p) for p in db.scalars(stmt).all()]


def get_patient_detail(db: Session, *, patient: Patient) -> dict:
    data = _patient_summary(db, patient)
    alt = _primary_contact(db, patient.patient_id, "ALTERNATE_MOBILE")
    address = _primary_address(db, patient.patient_id)
    address_out = None
    if address:
        region = db.get(Region, address.region_id) if address.region_id else None
        district = db.get(District, address.district_id) if address.district_id else None
        locality = db.get(Locality, address.locality_id) if address.locality_id else None
        address_out = {
            "region_id": address.region_id,
            "region": region.name if region else None,
            "district_id": address.district_id,
            "district": district.name if district else None,
            "locality_id": address.locality_id,
            "locality": locality.locality_name if locality else None,
            "address_line": address.address_line,
        }
    lead_ids = list(
        db.scalars(select(LeadPatientLink.lead_id).where(LeadPatientLink.patient_id == patient.patient_id)).all()
    )
    return {**data, "alternate_mobile": alt.contact_value if alt else None, "address": address_out, "lead_ids": lead_ids}


def conversion_preview(db: Session, *, lead: Lead) -> dict:
    mobile = db.scalar(
        select(LeadContact.contact_value)
        .where(LeadContact.lead_id == lead.lead_id, LeadContact.contact_type == "MOBILE")
        .order_by(LeadContact.is_primary.desc())
        .limit(1)
    )
    existing_link = db.scalar(select(LeadPatientLink).where(LeadPatientLink.lead_id == lead.lead_id))
    candidates = search_patient_matches(
        db,
        organization_id=lead.organization_id,
        name=lead.lead_name,
        mobile=mobile,
        gender=lead.gender,
    )
    return {
        "lead_id": lead.lead_id,
        "lead_name": lead.lead_name,
        "lead_row_version": lead.row_version,
        "mobile": mobile,
        "age": lead.age,
        "gender": lead.gender,
        "concern_text": lead.concern_text,
        "preferred_branch_id": lead.preferred_branch_id,
        "already_converted_patient_id": existing_link.patient_id if existing_link else None,
        "candidates": candidates,
    }


def convert_lead_to_patient(
    db: Session,
    *,
    lead_id: uuid.UUID,
    payload,
    actor_user_id: uuid.UUID,
    fiscal_year: str,
) -> tuple[Patient, bool]:
    # Lock the Lead row so concurrent convert clicks serialize on one identity.
    lead = db.scalar(select(Lead).where(Lead.lead_id == lead_id).with_for_update().execution_options(populate_existing=True))
    if not lead:
        raise HTTPException(404, "Lead not found")
    if payload.organization_id != lead.organization_id:
        raise HTTPException(403, "Lead and Patient organization must match")

    if not payload.identity_verified:
        raise HTTPException(422,"Confirm Name, Age/Gender and registration details before saving")
    existing_link = db.scalar(select(LeadPatientLink).where(LeadPatientLink.lead_id == lead_id))
    if existing_link:
        existing = db.get(Patient, existing_link.patient_id)
        if not existing:
            raise HTTPException(409, "Lead conversion link points to a missing Patient")
        if payload.existing_patient_id and payload.existing_patient_id!=existing.patient_id:
            raise HTTPException(409,"This Lead is already linked to a different Patient. Refresh the registration.")
        return existing, False
    if lead.row_version != payload.lead_row_version:
        raise HTTPException(409,"Lead changed. Reopen registration and verify the latest details.")

    if payload.existing_patient_id:
        patient = db.scalar(select(Patient).where(Patient.patient_id==payload.existing_patient_id).with_for_update())
        if not patient or patient.organization_id != lead.organization_id:
            raise HTTPException(400, "Selected existing Patient not found")
        if payload.existing_patient_row_version!=patient.row_version:
            raise HTTPException(409,"Selected Patient changed. Review Name, Age/Gender and UHID again.")
        created_new = False
    else:
        if payload.profile_status != "COMPLETE" or payload.legacy_patient_id:
            raise HTTPException(422,"Use staged legacy import for legacy Patient records")
        candidates = search_patient_matches(
            db,
            organization_id=lead.organization_id,
            name=payload.full_name,
            mobile=payload.mobile,
            dob=payload.dob,
            gender=payload.gender,
            age_years=payload.age_years,locality_id=payload.locality_id,address_line=payload.address_line,
        )
        if candidates and not payload.duplicate_override_confirmed:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "POSSIBLE_DUPLICATE_PATIENT",
                    "message": "Possible existing Patient found. Select the existing Patient or explicitly confirm creation of a separate Patient.",
                    "candidates": [{"patient_id": str(x["patient_id"]), "uhid": x["uhid"], "full_name": x["full_name"]} for x in candidates[:10]],
                },
            )
        branch = db.get(Branch, payload.registration_branch_id)
        if not branch or branch.organization_id != lead.organization_id:
            raise HTTPException(400, "Registration Branch not found")
        patient = create_patient(
            db,
            payload=payload,
            actor_user_id=actor_user_id,
            fiscal_year=fiscal_year,
            branch_code=branch.branch_code,
        )
        created_new = True

    db.add(
        LeadPatientLink(
            lead_id=lead.lead_id,
            patient_id=patient.patient_id,
            link_type="CONVERTED" if created_new else "EXISTING_PATIENT_MATCH",
            linked_at=datetime.now(timezone.utc),
            linked_by=actor_user_id,
        )
    )
    converted = db.scalar(select(LeadStatus).where(LeadStatus.code == "CONVERTED"))
    if not converted:
        raise HTTPException(503, "CONVERTED Lead status is not configured")
    old_status = lead.lead_status_id
    lead.lead_status_id = converted.lead_status_id
    lead.next_followup_at = None
    lead.updated_by = actor_user_id
    lead.row_version += 1
    db.add(
        LeadStatusHistory(
            lead_id=lead.lead_id,
            old_status_id=old_status,
            new_status_id=converted.lead_status_id,
            changed_by=actor_user_id,
            changed_at=datetime.now(timezone.utc),
            reason=f"Lead linked to Patient {patient.uhid}",
        )
    )
    # Preserve source Lead on appointments while attaching the verified Patient identity.
    db.execute(
        update(Appointment)
        .where(Appointment.lead_id == lead.lead_id, Appointment.patient_id.is_(None))
        .values(patient_id=patient.patient_id, row_version=Appointment.row_version + 1)
    )
    log_audit(db, organization_id=lead.organization_id,entity_type="LEAD",entity_id=lead.lead_id,
              action="LEAD_CONVERTED",actor_user_id=actor_user_id,
              before_data={"lead_status_id":str(old_status)},after_data={"patient_id":str(patient.patient_id),"uhid":patient.uhid,"created_new":created_new})
    db.flush()
    return patient, created_new
