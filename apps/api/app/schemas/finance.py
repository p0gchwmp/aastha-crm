import uuid
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field
from app.schemas.common import ORMModel


class ConsultationFeeCreate(BaseModel):
    service_id: uuid.UUID
    doctor_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    amount: Decimal = Field(gt=0)
    effective_from: date
    effective_until: date | None = None


class ConsultationFeeOut(ORMModel):
    fee_version_id: uuid.UUID
    service_id: uuid.UUID
    doctor_id: uuid.UUID | None
    branch_id: uuid.UUID | None
    amount: Decimal
    effective_from: date
    effective_until: date | None
    active: bool


class ConsultationBillDraftCreate(BaseModel):
    patient_id: uuid.UUID
    visit_id: uuid.UUID
    doctor_id: uuid.UUID
    branch_id: uuid.UUID
    fee_version_id: uuid.UUID


class ConsultationBillFromVisitCreate(BaseModel):
    visit_id: uuid.UUID


class ConsultationPaymentCreate(BaseModel):
    consultation_bill_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    payment_mode_id: uuid.UUID
    branch_id: uuid.UUID
    received_at: datetime


class ConsultationEligibilityOut(BaseModel):
    status: str
    entitlement_id: uuid.UUID | None = None
    valid_until: datetime | None = None


class ConsultationDecisionOut(BaseModel):
    visit_id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str
    uhid: str
    status: str
    entitlement_id: uuid.UUID | None = None
    valid_until: datetime | None = None
    bill_id: uuid.UUID | None = None
    bill_number: str | None = None
    bill_status: str | None = None
    clearance_type: str | None = None
    clearance_status: str | None = None
    fee_version_id: uuid.UUID | None = None
    amount: Decimal | None = None
    paid_amount: Decimal = Decimal("0")
    balance: Decimal | None = None


class BillOut(ORMModel):
    consultation_bill_id: uuid.UUID
    bill_number: str | None
    patient_id: uuid.UUID
    visit_id: uuid.UUID
    doctor_id: uuid.UUID
    branch_id: uuid.UUID
    fee_version_id: uuid.UUID
    gross_amount: Decimal
    discount_amount: Decimal
    net_amount: Decimal
    bill_status: str
    finalized_at: datetime | None
    row_version: int


class PaymentOut(ORMModel):
    payment_id: uuid.UUID
    consultation_bill_id: uuid.UUID
    amount: Decimal
    payment_mode_id: uuid.UUID
    received_by: uuid.UUID
    received_at: datetime
    branch_id: uuid.UUID
    payment_status: str
    row_version: int


class PaymentModeCorrection(BaseModel):
    payment_mode_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=500)
    expected_row_version: int


class BillVoidRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    expected_row_version: int


class ComplimentaryCreate(BaseModel):
    visit_id: uuid.UUID


class ChangeRequestCreate(BaseModel):
    entity_type: str
    entity_id: uuid.UUID
    requested_change: dict


class ChangeRequestResolve(BaseModel):
    approve: bool
    reason: str | None = None


class FinanceSetupOut(BaseModel):
    payment_modes: list[dict]
    active_policy: dict | None
    fee_versions: list[dict]


class DailyFinanceReportOut(BaseModel):
    report_date: date
    branch_id: uuid.UUID | None = None
    doctor_id: uuid.UUID | None = None
    total_consultation_visits: int
    paid_consultations: int
    free_followups: int
    complimentary_consultations: int
    total_collection: Decimal
    cash: Decimal
    upi: Decimal
    card: Decimal
    other: Decimal
