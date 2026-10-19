"""Administration of reception accounts; privileged/Doctor accounts are out of scope."""
import uuid
from datetime import date
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.access import active_role_codes
from app.core.db import get_db
from app.core.permissions import require_permission
from app.core.security import hash_password, verify_password
from app.models.core import Branch, Role, User, UserRole
from app.services.audit import log_audit

router = APIRouter(prefix="/admin/staff", tags=["staff"])
RECEPTION_ROLES = {"RECEPTIONIST", "SUPER_RECEPTIONIST"}
manager = require_permission("STAFF_MANAGE")


class StaffFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=150)
    role: Literal["RECEPTIONIST", "SUPER_RECEPTIONIST"] = "RECEPTIONIST"
    branch_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)

    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("branch_ids")
    @classmethod
    def unique_branches(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Choose each branch only once")
        return value


class StaffCreate(StaffFields):
    username: str = Field(min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
    # Keep password whitespace as entered; do not inherit text normalization.
    temporary_password: str = Field(min_length=12, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value):
        return value.strip().lower()


class StaffUpdate(StaffFields):
    row_version: int = Field(ge=1)
    status: Literal["ACTIVE", "INACTIVE"]
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def clean_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


class StaffReset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_version: int = Field(ge=1)
    temporary_password: str = Field(min_length=12, max_length=128)
    reason: str = Field(min_length=3, max_length=500)


def validate_password(value):
    if any(word in value.lower() for word in ("password", "changeme", "change-me", "replace")):
        raise HTTPException(422, "Choose a non-placeholder password of at least 12 characters")


def validate_branches(db, actor, branch_ids):
    branches = list(db.scalars(select(Branch).where(
        Branch.organization_id == actor.organization_id,
        Branch.branch_id.in_(branch_ids), Branch.active.is_(True),
    )).all())
    if len(branches) != len(branch_ids):
        raise HTTPException(422, "Select active branches belonging to this clinic")


def staff_data(db, user):
    today = date.today()
    assignments = db.execute(select(UserRole, Role.code).join(Role, Role.role_id == UserRole.role_id).where(
        UserRole.user_id == user.user_id,
    )).all()
    active = [(a, code) for a, code in assignments
              if (a.valid_from is None or a.valid_from <= today)
              and (a.valid_until is None or a.valid_until >= today)]
    return {
        "user_id": str(user.user_id), "name": user.name, "username": user.username,
        "status": user.status, "row_version": user.row_version,
        "roles": sorted({code for _, code in active}),
        "branch_ids": sorted({str(a.branch_id) for a, _ in active if a.branch_id}),
        "must_change_password": user.must_change_password,
    }


def get_target(db, actor, user_id, row_version):
    target = db.scalar(select(User).where(User.user_id == user_id,
        User.organization_id == actor.organization_id).with_for_update())
    if not target:
        raise HTTPException(404, "Staff user not found")
    codes = set(active_role_codes(db, target.user_id))
    if target.user_id == actor.user_id or not codes or not codes <= RECEPTION_ROLES:
        raise HTTPException(403, "This screen manages reception accounts only")
    if target.row_version != row_version:
        raise HTTPException(409, "This account changed. Refresh before saving")
    return target


def save(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Username already exists")


def audit(db, actor, target, action, before=None, reason=None):
    log_audit(db, organization_id=actor.organization_id, entity_type="STAFF_USER",
              entity_id=target.user_id, action=action, actor_user_id=actor.user_id,
              before_data=before, after_data=staff_data(db, target), reason=reason)


@router.get("")
def list_staff(db: Session = Depends(get_db), actor: User = Depends(manager)):
    users = db.scalars(select(User).where(User.organization_id == actor.organization_id).order_by(User.name)).all()
    # Filter privileged accounts server-side. Never send hashes or session versions.
    rows = [staff_data(db, user) for user in users]
    branches = db.scalars(select(Branch).where(Branch.organization_id == actor.organization_id,
        Branch.active.is_(True)).order_by(Branch.branch_name)).all()
    return {"users": [r for r in rows if r["roles"] and set(r["roles"]) <= RECEPTION_ROLES],
            "branches": [{"id": str(b.branch_id), "name": b.branch_name} for b in branches]}


@router.post("", status_code=201)
def create_staff(payload: StaffCreate, db: Session = Depends(get_db), actor: User = Depends(manager)):
    validate_password(payload.temporary_password)
    validate_branches(db, actor, payload.branch_ids)
    if db.scalar(select(User.user_id).where(func.lower(User.username) == payload.username)):
        raise HTTPException(409, "Username already exists")
    role = db.scalar(select(Role).where(Role.code == payload.role))
    if not role:
        raise HTTPException(503, "Reception roles are not configured")
    target = User(organization_id=actor.organization_id, name=payload.name, username=payload.username,
                  password_hash=hash_password(payload.temporary_password), status="ACTIVE", must_change_password=True)
    try:
        db.add(target)
        db.flush()
        for branch_id in payload.branch_ids:
            db.add(UserRole(user_id=target.user_id, role_id=role.role_id, branch_id=branch_id))
        db.flush()
        audit(db, actor, target, "STAFF_CREATED")
        save(db)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Username already exists")
    return staff_data(db, target)


@router.patch("/{user_id}")
def update_staff(user_id: uuid.UUID, payload: StaffUpdate, db: Session = Depends(get_db), actor: User = Depends(manager)):
    target = get_target(db, actor, user_id, payload.row_version)
    validate_branches(db, actor, payload.branch_ids)
    role = db.scalar(select(Role).where(Role.code == payload.role))
    if not role:
        raise HTTPException(503, "Reception roles are not configured")
    before = staff_data(db, target)
    # Assignment history remains in audit; role links are replaceable access configuration.
    for assignment in db.scalars(select(UserRole).where(UserRole.user_id == target.user_id)).all():
        db.delete(assignment)
    for branch_id in payload.branch_ids:
        db.add(UserRole(user_id=target.user_id, role_id=role.role_id, branch_id=branch_id))
    target.name = payload.name
    target.status = payload.status
    target.row_version += 1
    target.session_version += 1
    db.flush()
    audit(db, actor, target, "STAFF_UPDATED", before, payload.reason)
    save(db)
    return staff_data(db, target)


@router.post("/{user_id}/reset-password")
def reset_staff_password(user_id: uuid.UUID, payload: StaffReset, db: Session = Depends(get_db), actor: User = Depends(manager)):
    if not payload.reason.strip():
        raise HTTPException(422, "A reason is required")
    validate_password(payload.temporary_password)
    target = get_target(db, actor, user_id, payload.row_version)
    if verify_password(payload.temporary_password, target.password_hash):
        raise HTTPException(422, "Choose a different temporary password")
    before = staff_data(db, target)
    target.password_hash = hash_password(payload.temporary_password)
    target.must_change_password = True
    target.row_version += 1
    target.session_version += 1
    db.flush()
    audit(db, actor, target, "STAFF_PASSWORD_RESET", before, payload.reason.strip())
    save(db)
    return staff_data(db, target)
