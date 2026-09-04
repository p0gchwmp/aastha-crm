import uuid
from datetime import date
from sqlalchemy import Boolean, Date, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin


class Patient(Base, TimestampMixin):
    __tablename__ = "patients"
    __table_args__ = (
        UniqueConstraint("organization_id", "uhid"),
        Index("ix_patient_name", "full_name"),
        {"schema": "patient"},
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.organizations.organization_id"))
    uhid: Mapped[str] = mapped_column(String(80))
    full_name: Mapped[str] = mapped_column(String(180))
    gender: Mapped[str | None] = mapped_column(String(30))
    dob: Mapped[date | None] = mapped_column(Date)
    dob_is_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    profile_status: Mapped[str] = mapped_column(String(40), default="COMPLETE")
    registration_branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.branches.branch_id"))
    legacy_patient_id: Mapped[str | None] = mapped_column(String(100))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.users.user_id"))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.users.user_id"))
    extension_attributes: Mapped[dict] = mapped_column(default=dict)


class PatientContact(Base):
    __tablename__ = "patient_contacts"
    __table_args__ = (
        Index("ix_patient_contact_normalized", "normalized_value"),
        {"schema": "patient"},
    )
    patient_contact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.patients.patient_id"))
    contact_type: Mapped[str] = mapped_column(String(40))
    contact_value: Mapped[str] = mapped_column(String(200))
    normalized_value: Mapped[str] = mapped_column(String(200))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)


class Region(Base):
    __tablename__ = "regions"
    __table_args__ = {"schema": "core"}
    region_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")


class District(Base):
    __tablename__ = "districts"
    __table_args__ = (UniqueConstraint("region_id", "name"), {"schema": "core"})
    district_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    region_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.regions.region_id"))
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")


class Locality(Base, TimestampMixin):
    __tablename__ = "localities"
    __table_args__ = {"schema": "core"}
    locality_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    district_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.districts.district_id"))
    locality_name: Mapped[str] = mapped_column(String(140))
    approval_status: Mapped[str] = mapped_column(String(40), default="APPROVED")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.users.user_id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.users.user_id"))
    merged_into_locality_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.localities.locality_id"))


class PatientAddress(Base, TimestampMixin):
    __tablename__ = "patient_addresses"
    __table_args__ = {"schema": "patient"}
    patient_address_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.patients.patient_id"))
    region_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.regions.region_id"))
    district_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.districts.district_id"))
    locality_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.localities.locality_id"))
    address_line: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)


class ImportBatch(Base, TimestampMixin):
    __tablename__ = "import_batches"
    __table_args__ = {"schema": "patient"}
    import_batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.organizations.organization_id"))
    file_name: Mapped[str] = mapped_column(String(255))
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.users.user_id"))
    status: Mapped[str] = mapped_column(String(40), default="UPLOADED")
    total_rows: Mapped[int] = mapped_column(default=0)
    imported_rows: Mapped[int] = mapped_column(default=0)
    error_rows: Mapped[int] = mapped_column(default=0)
    duplicate_rows: Mapped[int] = mapped_column(default=0)


class ImportStaging(Base):
    __tablename__ = "import_staging"
    __table_args__ = {"schema": "patient"}
    staging_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    import_batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.import_batches.import_batch_id"))
    source_row_number: Mapped[int]
    raw_data: Mapped[dict] = mapped_column(default=dict)
    validation_status: Mapped[str] = mapped_column(String(40))
    matched_patient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("patient.patients.patient_id"))
    import_action: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(Text)
