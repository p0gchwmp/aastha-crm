import uuid
from datetime import date, datetime, time
from sqlalchemy import UniqueConstraint, Index, Boolean, Date, DateTime, ForeignKey, Integer, String, Time
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin


class AppointmentStatus(Base):
    __tablename__ = "appointment_statuses"
    __table_args__ = {"schema": "scheduling"}
    appointment_status_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(120))


class Appointment(Base, TimestampMixin):
    __tablename__ = "appointments"
    __table_args__ = (Index("uq_appointment_request", "organization_id", "created_by", "booking_request_id", unique=True), Index("ix_appointment_doctor_window", "doctor_id", "scheduled_start", "scheduled_end"), {"schema": "scheduling"})
    booking_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    booking_request_hash: Mapped[str | None] = mapped_column(String(64))
    appointment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.organizations.organization_id"))
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.branches.branch_id"))
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.doctors.doctor_id"))
    lead_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crm.leads.lead_id"))
    patient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("patient.patients.patient_id"))
    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scheduled_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    appointment_status_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scheduling.appointment_statuses.appointment_status_id"))
    service_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.services.service_id"))
    booked_via: Mapped[str] = mapped_column(String(60), default="RECEPTION")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.users.user_id"))
    integration_client_id: Mapped[uuid.UUID | None]
    extension_attributes: Mapped[dict] = mapped_column(default=dict)


class DoctorSchedule(Base, TimestampMixin):
    __tablename__ = "doctor_schedules"
    __table_args__ = {"schema": "scheduling"}
    schedule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.doctors.doctor_id"))
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.branches.branch_id"))
    day_of_week: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    slot_duration_minutes: Mapped[int] = mapped_column(Integer, default=15)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_until: Mapped[date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ScheduleException(Base, TimestampMixin):
    __tablename__ = "schedule_exceptions"
    __table_args__ = {"schema": "scheduling"}
    exception_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.doctors.doctor_id"))
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.branches.branch_id"))
    date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[time | None] = mapped_column(Time)
    end_time: Mapped[time | None] = mapped_column(Time)
    exception_type: Mapped[str] = mapped_column(String(60))
    slot_duration_minutes: Mapped[int] = mapped_column(Integer, default=15)
    note: Mapped[str | None] = mapped_column(String(500))
