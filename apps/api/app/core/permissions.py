from datetime import date
from fastapi import Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.security import current_user
from app.models.core import Permission, RolePermission, User, UserRole


def require_permission(permission_code: str):
    def dependency(user: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
        today = date.today()
        stmt = (
            select(Permission.permission_id)
            .join(RolePermission, RolePermission.permission_id == Permission.permission_id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(
                UserRole.user_id == user.user_id,
                Permission.code == permission_code,
                or_(UserRole.valid_from.is_(None), UserRole.valid_from <= today),
                or_(UserRole.valid_until.is_(None), UserRole.valid_until >= today),
            )
            .limit(1)
        )
        if db.scalar(stmt) is None:
            raise HTTPException(status_code=403, detail=f"Missing permission: {permission_code}")
        return user
    return dependency
