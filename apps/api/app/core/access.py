from __future__ import annotations
import uuid
from datetime import date
from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from app.models.core import Branch, Role, User, UserRole


def active_user_roles(db: Session, user_id: uuid.UUID, *, today: date | None = None) -> list[UserRole]:
    today = today or date.today()
    stmt = (
        select(UserRole)
        .where(
            UserRole.user_id == user_id,
            or_(UserRole.valid_from.is_(None), UserRole.valid_from <= today),
            or_(UserRole.valid_until.is_(None), UserRole.valid_until >= today),
        )
    )
    return list(db.scalars(stmt).all())


def active_role_codes(db: Session, user_id: uuid.UUID) -> list[str]:
    today = date.today()
    stmt = (
        select(Role.code)
        .join(UserRole, UserRole.role_id == Role.role_id)
        .where(
            UserRole.user_id == user_id,
            or_(UserRole.valid_from.is_(None), UserRole.valid_from <= today),
            or_(UserRole.valid_until.is_(None), UserRole.valid_until >= today),
        )
        .distinct()
        .order_by(Role.code)
    )
    return list(db.scalars(stmt).all())


def allowed_branch_ids(db: Session, user: User) -> set[uuid.UUID] | None:
    """None means organization-wide branch access; a set means branch-restricted."""
    roles = active_user_roles(db, user.user_id)
    if not roles:
        return set()
    if any(role.branch_id is None for role in roles):
        return None
    return {role.branch_id for role in roles if role.branch_id is not None}


def ensure_branch_access(db: Session, user: User, branch_id: uuid.UUID) -> Branch:
    branch = db.get(Branch, branch_id)
    if not branch or branch.organization_id != user.organization_id or not branch.active:
        raise HTTPException(status_code=404, detail="Branch not found")
    allowed = allowed_branch_ids(db, user)
    if allowed is not None and branch_id not in allowed:
        raise HTTPException(status_code=403, detail="User is not authorized for this branch")
    return branch
