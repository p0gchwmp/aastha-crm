import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin


class VisitType(Base):
    __tablename__ = "visit_types"
    __table_args__ = {"schema": "clinical"}
    visit_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class VisitStatus(Base):
    __tablename__ = "visit_statuses"
    __table_args__ = {"schema": "clinical"}
    visit_status_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(120))


class Visit(Base, TimestampMixin):
    __tablename__ = "visits"
    __table_args__ = {"schema": "clinical"}
    visit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.patients.patient_id"))
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("scheduling.appointments.appointment_id"))
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.branches.branch_id"))
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.doctors.doctor_id"))
    visit_type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical.visit_types.visit_type_id"))
    visit_status_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical.visit_statuses.visit_status_id"))
    checkin_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.users.user_id"))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.users.user_id"))
    extension_attributes: Mapped[dict] = mapped_column(default=dict)


class ChiefComplaint(Base, TimestampMixin):
    __tablename__ = "chief_complaints"
    __table_args__ = {"schema": "clinical"}
    chief_complaint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160))
    approval_status: Mapped[str] = mapped_column(String(40), default="APPROVED")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.users.user_id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.users.user_id"))
    merged_into_complaint_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clinical.chief_complaints.chief_complaint_id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class VisitComplaint(Base):
    __tablename__ = "visit_complaints"
    __table_args__ = (UniqueConstraint("visit_id", "chief_complaint_id"), {"schema": "clinical"})
    visit_complaint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical.visits.visit_id"))
    chief_complaint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical.chief_complaints.chief_complaint_id"))


class ProcedureOrderStatus(Base):
    __tablename__ = "procedure_order_statuses"
    __table_args__ = {"schema": "clinical"}
    procedure_order_status_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(120))


class ProcedureOrder(Base, TimestampMixin):
    __tablename__ = "procedure_orders"
    __table_args__ = {"schema": "clinical"}
    procedure_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.patients.patient_id"))
    ordered_from_visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical.visits.visit_id"))
    service_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.services.service_id"))
    ordered_by_doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.doctors.doctor_id"))
    ordering_branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.branches.branch_id"))
    order_status_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical.procedure_order_statuses.procedure_order_status_id"))
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    extension_attributes: Mapped[dict] = mapped_column(default=dict)


class ProcedureExecutionStatus(Base):
    __tablename__ = "procedure_execution_statuses"
    __table_args__ = {"schema": "clinical"}
    procedure_execution_status_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(120))


class ProcedureExecution(Base, TimestampMixin):
    __tablename__ = "procedure_executions"
    __table_args__ = {"schema": "clinical"}
    procedure_execution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    procedure_order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical.procedure_orders.procedure_order_id"))
    performed_visit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clinical.visits.visit_id"))
    rendering_branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.branches.branch_id"))
    performed_by_doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.doctors.doctor_id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_status_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical.procedure_execution_statuses.procedure_execution_status_id"))
    clinical_notes: Mapped[str | None] = mapped_column(Text)
    extension_attributes: Mapped[dict] = mapped_column(default=dict)


class ProcedureFinancialStatus(Base, TimestampMixin):
    __tablename__ = "procedure_financial_status"
    __table_args__ = (UniqueConstraint("procedure_order_id"), {"schema": "clinical"})
    procedure_financial_status_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    procedure_order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical.procedure_orders.procedure_order_id"))
    financial_status: Mapped[str] = mapped_column(String(50), default="NOT_BILLED")
    source_system: Mapped[str | None] = mapped_column(String(80))
    external_reference: Mapped[str | None] = mapped_column(String(160))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
