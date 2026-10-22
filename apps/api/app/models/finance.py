import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin


class ConsultationPolicyVersion(Base, TimestampMixin):
    __tablename__ = "policy_versions"
    __table_args__ = {"schema": "consultation_finance"}
    policy_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.organizations.organization_id"))
    name: Mapped[str] = mapped_column(String(120))
    free_followup_window_days: Mapped[int] = mapped_column(Integer, default=10)
    max_free_followups: Mapped[int] = mapped_column(Integer, default=1)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_until: Mapped[date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ConsultationFeeVersion(Base, TimestampMixin):
    __tablename__ = "fee_versions"
    __table_args__ = {"schema": "consultation_finance"}
    fee_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.services.service_id"))
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.doctors.doctor_id"))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.branches.branch_id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_until: Mapped[date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class FollowupEntitlement(Base, TimestampMixin):
    __tablename__ = "entitlements"
    __table_args__ = {"schema": "consultation_finance"}
    entitlement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.patients.patient_id"))
    source_visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical.visits.visit_id"))
    source_bill_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("consultation_finance.consultation_bills.consultation_bill_id"), unique=True)
    policy_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("consultation_finance.policy_versions.policy_version_id"))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(40), default="ACTIVE")


class EntitlementUsage(Base):
    __tablename__ = "entitlement_usages"
    __table_args__ = (UniqueConstraint("entitlement_id", "visit_id"), {"schema": "consultation_finance"})
    usage_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entitlement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("consultation_finance.entitlements.entitlement_id"))
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical.visits.visit_id"))
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConsultationBill(Base, TimestampMixin):
    __tablename__ = "consultation_bills"
    __table_args__ = (
        UniqueConstraint("bill_number"),
        UniqueConstraint("visit_id"),
        {"schema": "consultation_finance"},
    )
    consultation_bill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bill_number: Mapped[str | None] = mapped_column(String(120))
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.patients.patient_id"))
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical.visits.visit_id"))
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.doctors.doctor_id"))
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.branches.branch_id"))
    fee_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("consultation_finance.fee_versions.fee_version_id"))
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    bill_status: Mapped[str] = mapped_column(String(40), default="DRAFT")
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.users.user_id"))


class PaymentMode(Base):
    __tablename__ = "payment_modes"
    __table_args__ = {"schema": "consultation_finance"}
    payment_mode_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ConsultationPayment(Base, TimestampMixin):
    __tablename__ = "payments"
    __table_args__ = (
        Index("uq_consultation_payment_request", "received_by", "payment_request_id", unique=True),
        Index("uq_consultation_receipt_number", "receipt_number", unique=True),
        {"schema": "consultation_finance"},
    )
    payment_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payment_request_hash: Mapped[str | None] = mapped_column(String(64))
    receipt_number: Mapped[str | None] = mapped_column(String(120))

    payment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    consultation_bill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("consultation_finance.consultation_bills.consultation_bill_id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    payment_mode_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("consultation_finance.payment_modes.payment_mode_id"))
    received_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.users.user_id"))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.branches.branch_id"))
    payment_status: Mapped[str] = mapped_column(String(40), default="COMPLETED")


class ComplimentaryAuthorization(Base, TimestampMixin):
    __tablename__ = "complimentary_authorizations"
    __table_args__ = (UniqueConstraint("visit_id"), {"schema": "consultation_finance"})
    authorization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical.visits.visit_id"))
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.patients.patient_id"))
    doctor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.doctors.doctor_id"))
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), default="ACTIVE")


class ConsultationClearance(Base, TimestampMixin):
    __tablename__ = "consultation_clearances"
    __table_args__ = (UniqueConstraint("visit_id"), {"schema": "consultation_finance"})
    clearance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    visit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinical.visits.visit_id"))
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.patients.patient_id"))
    clearance_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), default="CLEARED")
    bill_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("consultation_finance.consultation_bills.consultation_bill_id"))
    entitlement_usage_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("consultation_finance.entitlement_usages.usage_id"))
    complimentary_authorization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("consultation_finance.complimentary_authorizations.authorization_id"))
    cleared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FinancialChangeRequest(Base, TimestampMixin):
    __tablename__ = "change_requests"
    __table_args__ = {"schema": "consultation_finance"}
    change_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.organizations.organization_id"))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    requested_change: Mapped[dict] = mapped_column(default=dict)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.users.user_id"))
    status: Mapped[str] = mapped_column(String(40), default="PENDING")
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.users.user_id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
