from datetime import datetime, timezone, date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from app.core.access import allowed_branch_ids
from app.core.db import get_db
from app.core.security import create_access_token, current_user, hash_password, verify_password
from app.models.core import Permission, Role, RolePermission, User, UserRole

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=128)


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == payload.username, User.status == "ACTIVE"))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    return {"access_token": create_access_token(str(user.user_id)), "token_type": "bearer"}


@router.post("/change-password")
def change_password(payload: ChangePasswordRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="New password must be different")
    lowered = payload.new_password.lower()
    if "password" in lowered or "changeme" in lowered or "replace" in lowered:
        raise HTTPException(status_code=400, detail="Choose a stronger non-placeholder password")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"status": "PASSWORD_CHANGED"}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    today = date.today()
    active_role_filter = (
        UserRole.user_id == user.user_id,
        or_(UserRole.valid_from.is_(None), UserRole.valid_from <= today),
        or_(UserRole.valid_until.is_(None), UserRole.valid_until >= today),
    )
    roles = list(db.scalars(
        select(Role.code).join(UserRole, UserRole.role_id == Role.role_id).where(*active_role_filter).distinct().order_by(Role.code)
    ).all())
    permissions = list(db.scalars(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.permission_id)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(*active_role_filter)
        .distinct()
        .order_by(Permission.code)
    ).all())
    branches = allowed_branch_ids(db, user)
    return {
        "user_id": user.user_id,
        "organization_id": user.organization_id,
        "name": user.name,
        "username": user.username,
        "roles": roles,
        "permissions": permissions,
        "branch_ids": None if branches is None else sorted(str(x) for x in branches),
        "organization_wide_branch_access": branches is None,
    }
