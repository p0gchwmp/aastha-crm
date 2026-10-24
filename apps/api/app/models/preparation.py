"""Assistant preparation is distinct from Doctor-authored consultation notes."""
import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin


class ClinicalPreparation(Base, TimestampMixin):
    __tablename__ = "assistant_preparations"
    __table_args__ = (UniqueConstraint("visit_id"), Index("ix_preparation_assignee", "assistant_user_id"), {"schema":"clinical"})
    preparation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical.visits.visit_id", ondelete="RESTRICT"))
    assistant_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.users.user_id", ondelete="RESTRICT"))
    assigned_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.users.user_id", ondelete="RESTRICT"))
    state: Mapped[str] = mapped_column(String(20), default="ASSIGNED")
    return_note: Mapped[str | None] = mapped_column(Text)
    history: Mapped[str | None] = mapped_column(Text)
    allergy_status: Mapped[str] = mapped_column(String(30), default="UNKNOWN")
    allergies: Mapped[str | None] = mapped_column(Text)
    current_medicines: Mapped[str | None] = mapped_column(Text)
    observations: Mapped[str | None] = mapped_column(Text)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(6,2))
    height_cm: Mapped[Decimal | None] = mapped_column(Numeric(6,2))
    systolic: Mapped[int | None]
    diastolic: Mapped[int | None]
    pulse: Mapped[int | None]
    respiratory_rate: Mapped[int | None]
    spo2: Mapped[Decimal | None] = mapped_column(Numeric(5,2))
    temperature_c: Mapped[Decimal | None] = mapped_column(Numeric(4,1))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_doctor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.doctors.doctor_id", ondelete="RESTRICT"))


class PreparationRevision(Base):
    __tablename__ = "assistant_preparation_revisions"
    __table_args__ = (UniqueConstraint("actor_user_id", "request_id"), Index("ix_preparation_revision_parent", "preparation_id", "occurred_at"), {"schema":"clinical"})
    revision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    preparation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical.assistant_preparations.preparation_id", ondelete="RESTRICT"))
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.users.user_id", ondelete="RESTRICT"))
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    request_hash: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(25))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    snapshot: Mapped[dict]
