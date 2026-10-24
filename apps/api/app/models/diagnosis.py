"""Configurable catalogue and relational Visit diagnoses; historical labels are snapshots."""
import uuid
from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin


class Diagnosis(Base, TimestampMixin):
    __tablename__ = "diagnoses"
    __table_args__ = (UniqueConstraint("organization_id", "normalized_name"), UniqueConstraint("organization_id", "source_key"), Index("ix_diagnoses_search", "organization_id", "normalized_name"), {"schema": "clinical"})
    diagnosis_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.organizations.organization_id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(240))
    normalized_name: Mapped[str] = mapped_column(String(480))
    category: Mapped[str] = mapped_column(String(120))
    history_module: Mapped[str | None] = mapped_column(String(160))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False)
    source_key: Mapped[str | None] = mapped_column(String(100))
    source_row: Mapped[int | None] = mapped_column(Integer)
    source_sha256: Mapped[str | None] = mapped_column(String(64))


class VisitDiagnosis(Base, TimestampMixin):
    __tablename__ = "visit_diagnoses"
    __table_args__ = (UniqueConstraint("visit_id", "diagnosis_id"), {"schema": "clinical"})
    visit_diagnosis_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical.visits.visit_id", ondelete="RESTRICT"), index=True)
    diagnosis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical.diagnoses.diagnosis_id", ondelete="RESTRICT"))
    name_snapshot: Mapped[str] = mapped_column(String(240))
    category_snapshot: Mapped[str] = mapped_column(String(120))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    recorded_by_doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.doctors.doctor_id", ondelete="RESTRICT"))
