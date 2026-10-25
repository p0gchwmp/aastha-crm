"""Visit-specific safety assessment; history is not an active medication list."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin

class SafetyAssessment(Base, TimestampMixin):
    __tablename__ = "safety_assessments"
    __table_args__ = (UniqueConstraint("visit_id"), {"schema":"clinical"})
    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical.visits.visit_id", ondelete="RESTRICT"))
    allergy_status: Mapped[str] = mapped_column(String(30), default="NOT_ASSESSED")
    medicine_status: Mapped[str] = mapped_column(String(30), default="NOT_ASSESSED")
    condition_status: Mapped[str] = mapped_column(String(30), default="NOT_ASSESSED")
    pregnancy_status: Mapped[str] = mapped_column(String(30), default="NOT_ASSESSED")
    breastfeeding_status: Mapped[str] = mapped_column(String(30), default="NOT_ASSESSED")
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(6,2))
    weight_date: Mapped[date | None] = mapped_column(Date)
    reviewed_by_doctor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.doctors.doctor_id", ondelete="RESTRICT"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.users.user_id", ondelete="RESTRICT"))

class SafetyEntry(Base, TimestampMixin):
    __tablename__ = "safety_entries"
    __table_args__ = (Index("ix_safety_entry_assessment", "assessment_id", "kind", "active"), {"schema":"clinical"})
    entry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    assessment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical.safety_assessments.assessment_id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(300))
    reaction: Mapped[str] = mapped_column(String(500), default="")
    severity: Mapped[str] = mapped_column(String(30), default="UNKNOWN")
    strength: Mapped[str] = mapped_column(String(240), default="")
    regimen: Mapped[str] = mapped_column(String(500), default="")
    exposure_status: Mapped[str] = mapped_column(String(30), default="CURRENT")
    source: Mapped[str] = mapped_column(String(240), default="")
    value: Mapped[str] = mapped_column(String(120), default="")
    unit: Mapped[str] = mapped_column(String(80), default="")
    observed_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str] = mapped_column(String(1000), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class SafetyRevision(Base):
    __tablename__ = "safety_revisions"
    __table_args__ = (UniqueConstraint("actor_user_id", "request_id"), Index("ix_safety_revision_parent", "assessment_id", "occurred_at"), {"schema":"clinical"})
    revision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assessment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical.safety_assessments.assessment_id", ondelete="RESTRICT"))
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.users.user_id", ondelete="RESTRICT"))
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    request_hash: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    snapshot: Mapped[dict]
