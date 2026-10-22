import uuid
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field, ConfigDict, field_validator
from app.schemas.common import ORMModel


class ConsultationFeeCreate(BaseModel):
    service_id: uuid.UUID
    doctor_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
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


class FinanceIdentity(BaseModel):
    identity_confirmed: bool = False
    patient_row_version: int = Field(ge=1)


class ConsultationPolicyCreate(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    free_followup_window_days: int = Field(ge=0, le=365)
    max_free_followups: int = Field(ge=0, le=20)
    effective_from: date

    @field_validator("name")
    @classmethod
    def nonempty(cls, value):
        if len(value.strip()) < 3: raise ValueError("Enter a policy name")
        return value.strip()


class FreeFollowupCreate(FinanceIdentity):
    entitlement_id: uuid.UUID


class BillFinalizeCreate(BaseModel):
    expected_row_version: int = Field(ge=1)


class ConsultationBillDraftCreate(FinanceIdentity):
    patient_id: uuid.UUID
    visit_id: uuid.UUID
    doctor_id: uuid.UUID
    branch_id: uuid.UUID
    fee_version_id: uuid.UUID


class ConsultationBillFromVisitCreate(FinanceIdentity):
    visit_id: uuid.UUID


class ConsultationPaymentCreate(FinanceIdentity):
    model_config = ConfigDict(extra="forbid")
    payment_request_id: uuid.UUID
    expected_bill_row_version: int = Field(ge=1)
    consultation_bill_id: uuid.UUID
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    payment_mode_id: uuid.UUID
    branch_id: uuid.UUID


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
    patient_age: int | None = None
    patient_gender: str | None = None
    patient_row_version: int
    bill_row_version: int | None = None
    payments: list[dict] = Field(default_factory=list)
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
    receipt_number: str | None = None
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
