import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"
    __table_args__ = {"schema": "core"}
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_code: Mapped[str] = mapped_column(String(30), unique=True)
    organization_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")


class Branch(Base, TimestampMixin):
    __tablename__ = "branches"
    __table_args__ = (UniqueConstraint("organization_id", "branch_code"), {"schema": "core"})
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.organizations.organization_id"))
    branch_code: Mapped[str] = mapped_column(String(30))
    branch_name: Mapped[str] = mapped_column(String(150))
    address: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(40))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("organization_id", "username"), {"schema": "core"})
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.organizations.organization_id"))
    name: Mapped[str] = mapped_column(String(150))
    username: Mapped[str] = mapped_column(String(100))
    mobile: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    session_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = {"schema": "core"}
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(120))


class Permission(Base):
    __tablename__ = "permissions"
    __table_args__ = {"schema": "core"}
    permission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(180))


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_id"), {"schema": "core"})
    role_permission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.roles.role_id"))
    permission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.permissions.permission_id"))


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = {"schema": "core"}
    user_role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.users.user_id"))
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.roles.role_id"))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.branches.branch_id"))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)


class Doctor(Base, TimestampMixin):
    __tablename__ = "doctors"
    __table_args__ = (UniqueConstraint("organization_id", "doctor_code"), {"schema": "core"})
    doctor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.organizations.organization_id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.users.user_id"))
    doctor_code: Mapped[str] = mapped_column(String(40))
    doctor_name: Mapped[str] = mapped_column(String(150))
    speciality: Mapped[str | None] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ServiceCategory(Base):
    __tablename__ = "service_categories"
    __table_args__ = {"schema": "core"}
    service_category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(120))


class Service(Base, TimestampMixin):
    __tablename__ = "services"
    __table_args__ = (UniqueConstraint("organization_id", "service_code"), {"schema": "core"})
    service_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.organizations.organization_id"))
    service_code: Mapped[str] = mapped_column(String(60))
    service_name: Mapped[str] = mapped_column(String(180))
    service_category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.service_categories.service_category_id"))
    clinical_type: Mapped[str | None] = mapped_column(String(80))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class NumberSeries(Base, TimestampMixin):
    __tablename__ = "number_series"
    __table_args__ = (UniqueConstraint("organization_id", "series_code", "branch_id", "fiscal_year"),
        Index("uq_active_global_uhid", "organization_id", unique=True, postgresql_where=text("series_code = 'UHID' AND active"), sqlite_where=text("series_code = 'UHID' AND active")), {"schema": "core"})
    number_series_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.organizations.organization_id"))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.branches.branch_id"))
    series_code: Mapped[str] = mapped_column(String(60))
    prefix_template: Mapped[str] = mapped_column(String(150))
    current_number: Mapped[int] = mapped_column(Integer, default=0)
    reset_rule: Mapped[str] = mapped_column(String(40), default="FISCAL_YEAR")
    fiscal_year: Mapped[str | None] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
