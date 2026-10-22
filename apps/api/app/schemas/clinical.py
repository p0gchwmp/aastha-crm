import uuid
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from app.schemas.common import ORMModel


class VisitCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patient_id: uuid.UUID
    patient_row_version: int = Field(ge=1)
    creation_request_id: uuid.UUID
    appointment_id: uuid.UUID | None = None
    appointment_row_version: int | None = Field(default=None, ge=1)
    branch_id: uuid.UUID
    doctor_id: uuid.UUID | None = None
    visit_type_id: uuid.UUID
    chief_complaint_ids: list[uuid.UUID] = Field(default_factory=list, max_length=30)
    identity_confirmed: bool = False


class VisitOut(ORMModel):
    visit_id: uuid.UUID
    patient_id: uuid.UUID
    branch_id: uuid.UUID
    doctor_id: uuid.UUID | None
    checkin_at: datetime
    row_version: int


class ProcedureOrderCreate(BaseModel):
    patient_id: uuid.UUID
    ordered_from_visit_id: uuid.UUID
    service_id: uuid.UUID
    ordered_by_doctor_id: uuid.UUID
    ordering_branch_id: uuid.UUID
    order_status_id: uuid.UUID
    ordered_at: datetime
    notes: str | None = None
