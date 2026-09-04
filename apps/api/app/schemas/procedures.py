import uuid
from datetime import datetime
from pydantic import BaseModel, Field


class ProcedureOrderCreateRequest(BaseModel):
    visit_id: uuid.UUID
    service_id: uuid.UUID
    notes: str | None = None


class ProcedureOrderFromVisitRequest(BaseModel):
    service_id: uuid.UUID
    notes: str | None = None


class ProcedureExecutionCreateRequest(BaseModel):
    rendering_branch_id: uuid.UUID
    performed_visit_id: uuid.UUID
    clinical_notes: str | None = None


class ProcedureExecutionCompleteRequest(BaseModel):
    clinical_notes: str | None = None
    row_version: int = Field(ge=1)


class FinancialStatusCallback(BaseModel):
    external_event_id: str = Field(min_length=1, max_length=180)
    financial_status: str
    external_reference: str | None = Field(default=None, max_length=160)
    occurred_at: datetime | None = None


class EventAckRequest(BaseModel):
    external_event_id: str = Field(min_length=1, max_length=180)


class ProcedureOrderCancelRequest(BaseModel):
    row_version: int = Field(ge=1)
    reason: str = Field(min_length=2, max_length=500)
