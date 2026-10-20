import uuid
from datetime import date, time, datetime
from typing import Literal
from pydantic import BaseModel, Field, AwareDatetime, ConfigDict, model_validator
from app.schemas.common import ORMModel

class SlotFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    branch_id: uuid.UUID
    doctor_id: uuid.UUID
    scheduled_start: AwareDatetime
    scheduled_end: AwareDatetime

    @model_validator(mode="after")
    def valid_window(self):
        if self.scheduled_end <= self.scheduled_start:
            raise ValueError("End must be after start")
        return self

class AppointmentCreate(SlotFields):
    organization_id: uuid.UUID
    lead_id: uuid.UUID | None = None
    patient_id: uuid.UUID | None = None
    appointment_status_id: uuid.UUID
    service_id: uuid.UUID | None = None
    booked_via: str = Field(default="RECEPTION", min_length=1, max_length=60)
    booking_request_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_party(self):
        if bool(self.lead_id) == bool(self.patient_id):
            raise ValueError("Select exactly one Lead or Patient; mobile alone cannot identify a Patient")
        return self

class AppointmentReschedule(SlotFields):
    row_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)

class AppointmentAttendance(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    status_code: Literal["CONFIRMED","CHECKED_IN","NO_SHOW","CANCELLED","COMPLETED"]
    row_version: int = Field(ge=1)
    reason: str | None = Field(default=None,max_length=500)


class VersionReason(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    row_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)

class ScheduleFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    doctor_id: uuid.UUID
    branch_id: uuid.UUID
    day_of_week: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
    slot_duration_minutes: int = Field(ge=5, le=120)
    effective_from: date
    effective_until: date | None = None
    active: bool = True
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.start_time.tzinfo or self.end_time.tzinfo or self.end_time <= self.start_time:
            raise ValueError("Use a same-day start/end window in India Standard Time")
        if self.start_time.second or self.end_time.second or self.start_time.microsecond or self.end_time.microsecond:
            raise ValueError("Use whole minutes")
        if self.effective_until and self.effective_until < self.effective_from:
            raise ValueError("Effective Until must be on or after From")
        if (datetime.combine(date.min,self.end_time)-datetime.combine(date.min,self.start_time)).total_seconds() < self.slot_duration_minutes*60:
            raise ValueError("Schedule must contain at least one full slot")
        return self

class ScheduleUpdate(ScheduleFields):
    row_version: int = Field(ge=1)

class ExceptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    doctor_id: uuid.UUID
    branch_id: uuid.UUID
    date: date
    start_time: time | None = None
    end_time: time | None = None
    exception_type: Literal["LEAVE","HOLIDAY","CLOSED","BREAK","ADDITIONAL"]
    slot_duration_minutes: int = Field(default=15, ge=5, le=120)
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def valid_exception(self):
        if bool(self.start_time) != bool(self.end_time):
            raise ValueError("Provide both start and end, or neither for a full-day closure")
        if self.exception_type in {"BREAK","ADDITIONAL"} and self.start_time is None:
            raise ValueError("This exception requires start and end times")
        if self.start_time is not None:
            if self.start_time.tzinfo or self.end_time.tzinfo or self.end_time <= self.start_time:
                raise ValueError("Use a same-day window in India Standard Time")
            if self.start_time.second or self.end_time.second or self.start_time.microsecond or self.end_time.microsecond:
                raise ValueError("Use whole minutes")
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
