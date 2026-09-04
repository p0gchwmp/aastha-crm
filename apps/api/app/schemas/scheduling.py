import uuid
from datetime import datetime
from pydantic import BaseModel, model_validator
from app.schemas.common import ORMModel


class AppointmentCreate(BaseModel):
    organization_id: uuid.UUID
    branch_id: uuid.UUID
    doctor_id: uuid.UUID | None = None
    lead_id: uuid.UUID | None = None
    patient_id: uuid.UUID | None = None
    scheduled_start: datetime
    scheduled_end: datetime
    appointment_status_id: uuid.UUID
    service_id: uuid.UUID | None = None
    booked_via: str = "RECEPTION"

    @model_validator(mode="after")
    def validate_party(self):
        if not self.lead_id and not self.patient_id:
            raise ValueError("Appointment requires lead_id or patient_id")
        if self.scheduled_end <= self.scheduled_start:
            raise ValueError("scheduled_end must be after scheduled_start")
        return self


class AppointmentOut(ORMModel):
    appointment_id: uuid.UUID
    branch_id: uuid.UUID
    doctor_id: uuid.UUID | None
    lead_id: uuid.UUID | None
    patient_id: uuid.UUID | None
    scheduled_start: datetime
    scheduled_end: datetime
    booked_via: str
    row_version: int
