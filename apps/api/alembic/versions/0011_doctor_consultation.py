"""Add protected consultation notes and append-only revisions."""
from alembic import op
from app.models.clinical import ConsultationNote, ConsultationNoteRevision
revision = "0011_doctor_consultation"
down_revision = "0010_consultation_payments"
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    ConsultationNote.__table__.create(bind, checkfirst=True)
    ConsultationNoteRevision.__table__.create(bind, checkfirst=True)
    from sqlalchemy.orm import Session
    from sqlalchemy import select
    from app.models.core import Permission, Role, RolePermission
    db = Session(bind=bind)
    permission = db.scalar(select(Permission).where(Permission.code == "CONSULTATION_CLINICAL"))
    if not permission:
        permission = Permission(code="CONSULTATION_CLINICAL", name="Doctor Consultations")
        db.add(permission)
        db.flush()
    role = db.scalar(select(Role).where(Role.code == "DOCTOR"))
    if role and not db.scalar(select(RolePermission).where(RolePermission.role_id == role.role_id, RolePermission.permission_id == permission.permission_id)):
        db.add(RolePermission(role_id=role.role_id, permission_id=permission.permission_id))
    db.flush()


def downgrade():
    ConsultationNoteRevision.__table__.drop(op.get_bind(), checkfirst=True)
    ConsultationNote.__table__.drop(op.get_bind(), checkfirst=True)
