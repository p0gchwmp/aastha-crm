"""Administration of Doctor and Clinical Assistant accounts only."""
import uuid
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.api.routes.staff import StaffCreate, StaffUpdate, StaffReset, staff_data, validate_branches, validate_password
from app.core.access import allowed_branch_ids
from app.core.db import get_db
from app.core.permissions import require_permission
from app.core.security import hash_password, verify_password
from app.models.core import Branch, Doctor, Role, User, UserRole
from app.models.clinical import Visit, VisitStatus
from app.models.scheduling import Appointment, AppointmentStatus
from app.services.audit import log_audit

router = APIRouter(prefix="/admin/clinical-team", tags=["clinical-team"])
manager = require_permission("CLINICAL_TEAM_MANAGE")
TEAM = {"DOCTOR", "CLINICAL_ASSISTANT"}


class TeamCreate(StaffCreate):
    role: Literal["DOCTOR", "CLINICAL_ASSISTANT"]
    doctor_code: str | None = Field(default=None, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    speciality: str | None = Field(default=None, max_length=120)
    existing_doctor_id: uuid.UUID | None = None


class TeamUpdate(StaffUpdate):
    role: Literal["DOCTOR", "CLINICAL_ASSISTANT"]
    speciality: str | None = Field(default=None, max_length=120)


def all_roles(db, user):
    return set(db.scalars(select(Role.code).join(UserRole).where(UserRole.user_id == user.user_id)).all())


def scope(db, actor, branch_ids):
    validate_branches(db, actor, branch_ids)
    allowed = allowed_branch_ids(db, actor)
    if allowed is not None and not set(branch_ids) <= allowed:
        raise HTTPException(403, "Cannot grant access outside your own branches")


def profile(db, user, lock=False):
    stmt = select(Doctor).where(Doctor.user_id == user.user_id).execution_options(populate_existing=True)
    rows = db.scalars(stmt.with_for_update() if lock else stmt).all()
    if len(rows) > 1 or any(d.organization_id != user.organization_id for d in rows):
        raise HTTPException(409, "Doctor profile mapping needs administrator review")
    return rows[0] if rows else None


def data(db, user):
    result = staff_data(db, user)
    doctor = profile(db, user)
    result["doctor"] = {"doctor_id": str(doctor.doctor_id), "doctor_code": doctor.doctor_code, "speciality": doctor.speciality, "active": doctor.active} if doctor else None
    result["configured_roles"] = sorted(all_roles(db, user))
    result["organization_wide"] = allowed_branch_ids(db, user) is None
    return result


def target_for(db, actor, user_id, version):
    target = db.scalar(select(User).where(User.user_id == user_id, User.organization_id == actor.organization_id).with_for_update().execution_options(populate_existing=True))
    if not target: raise HTTPException(404, "Clinical account not found")
    roles = all_roles(db, target)
    if target.user_id == actor.user_id or len(roles) != 1 or not roles <= TEAM:
        raise HTTPException(403, "This screen manages dedicated Doctor and Assistant accounts only")
    allowed = allowed_branch_ids(db, actor); granted = allowed_branch_ids(db, target)
    if allowed is not None and (granted is None or not granted <= allowed):
        raise HTTPException(403, "Account has access outside your own branches")
    if target.row_version != version: raise HTTPException(409, "Account changed. Refresh before saving")
    return target


def audit(db, actor, target, action, before=None, reason=None):
    log_audit(db, organization_id=actor.organization_id, entity_type="STAFF_USER", entity_id=target.user_id, action=action, actor_user_id=actor.user_id, before_data=before, after_data=data(db, target), reason=reason)


@router.get("")
def directory(db: Session=Depends(get_db), actor: User=Depends(manager)):
    allowed = allowed_branch_ids(db, actor)
    users = []
    for user in db.scalars(select(User).where(User.organization_id == actor.organization_id).order_by(User.name)).all():
        roles = all_roles(db, user)
        if len(roles) != 1 or not roles <= TEAM: continue
        access = allowed_branch_ids(db, user)
        if allowed is not None and (access is None or not access <= allowed): continue
        users.append(data(db, user))
    branches = db.scalars(select(Branch).where(Branch.organization_id == actor.organization_id, Branch.active.is_(True))).all()
    return {"users": users, "branches": [{"id":str(b.branch_id), "name":b.branch_name} for b in branches if allowed is None or b.branch_id in allowed], "unlinked_doctors": [{"id":str(d.doctor_id), "name":d.doctor_name, "code":d.doctor_code} for d in db.scalars(select(Doctor).where(Doctor.organization_id == actor.organization_id, Doctor.user_id.is_(None), Doctor.active.is_(True))).all()] if allowed is None else []}


@router.post("", status_code=201)
def create(payload: TeamCreate, db: Session=Depends(get_db), actor: User=Depends(manager)):
    validate_password(payload.temporary_password); scope(db, actor, payload.branch_ids)
    if payload.role == "CLINICAL_ASSISTANT" and (payload.doctor_code or payload.existing_doctor_id or payload.speciality):
        raise HTTPException(422, "Doctor profile fields do not apply to an Assistant")
    role = db.scalar(select(Role).where(Role.code == payload.role))
    if not role: raise HTTPException(503, "Clinical roles are not configured")
    if db.scalar(select(User.user_id).where(func.lower(User.username) == payload.username)):
        raise HTTPException(409, "Username already exists")
    try:
        # Serialize profile creation/linking and code allocation within a clinic.
        from app.models.core import Organization
        db.scalar(select(Organization).where(Organization.organization_id == actor.organization_id).with_for_update())
        doctor = None
        if payload.role == "DOCTOR":
            if payload.existing_doctor_id:
                if allowed_branch_ids(db, actor) is not None: raise HTTPException(403, "Clinic-wide administrator required to link an existing profile")
                doctor = db.scalar(select(Doctor).where(Doctor.doctor_id == payload.existing_doctor_id, Doctor.organization_id == actor.organization_id).with_for_update().execution_options(populate_existing=True))
                if not doctor or doctor.user_id or not doctor.active: raise HTTPException(409, "Existing Doctor profile cannot be linked")
            else:
                if not payload.doctor_code: raise HTTPException(422, "A Doctor code is required")
                if db.scalar(select(Doctor).where(Doctor.organization_id == actor.organization_id, func.lower(Doctor.doctor_code) == payload.doctor_code.lower())): raise HTTPException(409, "Doctor code already exists")
        user = User(organization_id=actor.organization_id, name=payload.name, username=payload.username, password_hash=hash_password(payload.temporary_password), must_change_password=True, status="ACTIVE")
        db.add(user); db.flush()
        for branch in payload.branch_ids: db.add(UserRole(user_id=user.user_id, role_id=role.role_id, branch_id=branch))
        if payload.role == "DOCTOR":
            if not doctor:
                doctor = Doctor(organization_id=actor.organization_id, doctor_code=payload.doctor_code, doctor_name=payload.name, active=True)
                db.add(doctor)
            doctor.user_id=user.user_id; doctor.doctor_name=payload.name; doctor.speciality=payload.speciality
        db.flush(); audit(db, actor, user, "CLINICAL_ACCOUNT_CREATED"); db.commit()
        return data(db, user)
    except Exception as exc:
        db.rollback()
        if isinstance(exc, IntegrityError): raise HTTPException(409, "Username or Doctor code already exists") from exc
        raise


@router.patch("/{user_id}")
def update(user_id: uuid.UUID, payload: TeamUpdate, db: Session=Depends(get_db), actor: User=Depends(manager)):
    target=target_for(db, actor, user_id, payload.row_version); scope(db, actor, payload.branch_ids)
    if all_roles(db, target) != {payload.role}: raise HTTPException(409, "Clinical roles cannot be changed on an existing account")
    before=data(db, target); doctor=profile(db, target, lock=True)
    if payload.role == "DOCTOR" and not doctor: raise HTTPException(409, "Doctor profile is missing")
    old=allowed_branch_ids(db, target); removed = (old - set(payload.branch_ids)) if old is not None else {b.branch_id for b in db.scalars(select(Branch).where(Branch.organization_id == actor.organization_id)).all()} - set(payload.branch_ids)
    if doctor and removed:
        open_visit=db.scalar(select(Visit.visit_id).join(VisitStatus).where(Visit.doctor_id==doctor.doctor_id, Visit.branch_id.in_(removed), VisitStatus.code.in_(["CREATED","WAITING","IN_PROGRESS"])).limit(1))
        future=db.scalar(select(Appointment.appointment_id).join(AppointmentStatus).where(Appointment.doctor_id==doctor.doctor_id,Appointment.branch_id.in_(removed),Appointment.scheduled_end>datetime.now(timezone.utc),AppointmentStatus.code.not_in(["CANCELLED","NO_SHOW","COMPLETED"])).limit(1))
        if open_visit or future: raise HTTPException(409, "Reassign open Visits and future appointments before removing a Doctor branch")
    for row in db.scalars(select(UserRole).where(UserRole.user_id==target.user_id)).all(): db.delete(row)
    role=db.scalar(select(Role).where(Role.code==payload.role))
    for branch in payload.branch_ids: db.add(UserRole(user_id=target.user_id, role_id=role.role_id, branch_id=branch))
    target.name=payload.name; target.status=payload.status; target.row_version+=1; target.session_version+=1
    if doctor:
        doctor.doctor_name=payload.name; doctor.speciality=payload.speciality; doctor.active=payload.status=="ACTIVE"; doctor.row_version+=1
    db.flush(); audit(db, actor, target, "CLINICAL_ACCOUNT_UPDATED", before, payload.reason); db.commit()
    return data(db, target)


@router.post("/{user_id}/reset-password")
def reset(user_id: uuid.UUID, payload: StaffReset, db: Session=Depends(get_db), actor: User=Depends(manager)):
    if not payload.reason.strip(): raise HTTPException(422, "A reason is required")
    validate_password(payload.temporary_password); target=target_for(db,actor,user_id,payload.row_version)
    if verify_password(payload.temporary_password,target.password_hash): raise HTTPException(422, "Choose a different temporary password")
    before=data(db,target); target.password_hash=hash_password(payload.temporary_password); target.must_change_password=True; target.session_version+=1; target.row_version+=1
    db.flush(); audit(db,actor,target,"CLINICAL_PASSWORD_RESET",before,payload.reason.strip()); db.commit()
    return data(db,target)
