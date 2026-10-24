"""Shared clinical-team grants and Doctor branch enforcement."""
from fastapi import HTTPException
from sqlalchemy import select
from app.core.access import allowed_branch_ids
from app.models.core import Permission, Role, RolePermission, User

GRANTS = {
    "ADMIN": {"CLINICAL_TEAM_MANAGE", "CLINICAL_ASSIGN"},
    "SUPER_ADMIN": {"CLINICAL_TEAM_MANAGE", "CLINICAL_ASSIGN"},
    "DOCTOR": {"CLINICAL_ASSIGN"},
    "CLINICAL_ASSISTANT": {"CLINICAL_PREPARATION"},
}


def configure_permissions(db):
    for role_code, codes in GRANTS.items():
        role = db.scalar(select(Role).where(Role.code == role_code))
        if not role:
            role = Role(code=role_code, name=role_code.replace("_", " ").title())
            db.add(role); db.flush()
        for code in codes:
            permission = db.scalar(select(Permission).where(Permission.code == code))
            if not permission:
                permission = Permission(code=code, name=code.replace("_", " ").title())
                db.add(permission); db.flush()
            if not db.scalar(select(RolePermission).where(RolePermission.role_id == role.role_id, RolePermission.permission_id == permission.permission_id)):
                db.add(RolePermission(role_id=role.role_id, permission_id=permission.permission_id)); db.flush()


def ensure_doctor_branch(db, doctor, branch_id):
    # Existing operational profiles without a login keep their historical behavior.
    if not doctor.user_id:
        return
    user = db.get(User, doctor.user_id)
    if not user or user.organization_id != doctor.organization_id or user.status != "ACTIVE":
        raise HTTPException(409, "Doctor login is inactive or unavailable")
    allowed = allowed_branch_ids(db, user)
    if allowed is not None and branch_id not in allowed:
        raise HTTPException(409, "Doctor is not authorized for this branch")
