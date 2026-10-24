"""Reviewed medicine products and permanent, archived prescription lines."""
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin


class Medicine(Base, TimestampMixin):
    __tablename__ = "medicines"
    __table_args__ = (UniqueConstraint("organization_id", "product_key"), UniqueConstraint("organization_id", "source_key"), Index("ix_medicine_search", "organization_id", "search_name"), {"schema":"clinical"})
    medicine_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.organizations.organization_id", ondelete="RESTRICT"))
    brand: Mapped[str] = mapped_column(String(240), default="")
    generic: Mapped[str] = mapped_column(String(300), default="")
    strength: Mapped[str] = mapped_column(String(240), default="")
    form: Mapped[str] = mapped_column(String(120), default="")
    route: Mapped[str] = mapped_column(String(120), default="")
    pack_size: Mapped[str] = mapped_column(String(120), default="")
    manufacturer: Mapped[str] = mapped_column(String(240), default="")
    product_key: Mapped[str] = mapped_column(String(64))
    search_name: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=True)
    verified_by_doctor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.doctors.doctor_id", ondelete="RESTRICT"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_key: Mapped[str | None] = mapped_column(String(100))
    source_row: Mapped[int | None] = mapped_column(Integer)
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    source_verification: Mapped[str | None] = mapped_column(String(240))
    source_url: Mapped[str | None] = mapped_column(Text)


class PrescriptionLine(Base, TimestampMixin):
    __tablename__ = "prescription_lines"
    __table_args__ = (Index("ix_prescription_visit", "visit_id", "active", "display_order"), {"schema":"clinical"})
    line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical.visits.visit_id", ondelete="RESTRICT"))
    medicine_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical.medicines.medicine_id", ondelete="RESTRICT"))
    brand_snapshot: Mapped[str] = mapped_column(String(240))
    generic_snapshot: Mapped[str] = mapped_column(String(300))
    strength_snapshot: Mapped[str] = mapped_column(String(240))
    form_snapshot: Mapped[str] = mapped_column(String(120))
    medicine_version: Mapped[int] = mapped_column(Integer)
    dose: Mapped[str] = mapped_column(String(240))
    frequency: Mapped[str] = mapped_column(String(120))
    duration: Mapped[str] = mapped_column(String(120))
    quantity: Mapped[str] = mapped_column(String(120), default="")
    route: Mapped[str] = mapped_column(String(120))
    site: Mapped[str] = mapped_column(String(240), default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    display_order: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    recorded_by_doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.doctors.doctor_id", ondelete="RESTRICT"))
