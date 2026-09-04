import uuid
from datetime import date, datetime
from pydantic import BaseModel, Field, model_validator
from app.schemas.common import ORMModel


class PatientCreate(BaseModel):
    organization_id: uuid.UUID
    full_name: str = Field(min_length=1, max_length=180)
    mobile: str | None = None
    alternate_mobile: str | None = None
    gender: str | None = None
    dob: date | None = None
    dob_is_estimated: bool = False
    registration_branch_id: uuid.UUID
    legacy_patient_id: str | None = None
    profile_status: str = "COMPLETE"
    region_id: uuid.UUID | None = None
    district_id: uuid.UUID | None = None
    locality_id: uuid.UUID | None = None
    address_line: str | None = None
    duplicate_override_confirmed: bool = False


class LeadPatientConversionCreate(PatientCreate):
    existing_patient_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_existing_patient_mode(self):
        if self.existing_patient_id:
            # Registration payload can remain prefilled for UI convenience, but existing identity wins.
            self.duplicate_override_confirmed = True
        return self


class PatientUpdate(BaseModel):
    row_version: int
    full_name: str | None = Field(default=None, min_length=1, max_length=180)
    gender: str | None = None
    dob: date | None = None
    dob_is_estimated: bool | None = None
    profile_status: str | None = None
    mobile: str | None = None
    alternate_mobile: str | None = None
    region_id: uuid.UUID | None = None
    district_id: uuid.UUID | None = None
    locality_id: uuid.UUID | None = None
    address_line: str | None = None


class PatientOut(ORMModel):
    patient_id: uuid.UUID
    uhid: str
    full_name: str
    gender: str | None
    dob: date | None
    dob_is_estimated: bool
    profile_status: str
    registration_branch_id: uuid.UUID
    row_version: int


class PatientSearchOut(BaseModel):
    patient_id: uuid.UUID
    uhid: str
    full_name: str
    gender: str | None
    dob: date | None
    age: int | None
    primary_mobile: str | None
    area: str | None
    last_visit_at: datetime | None
    registration_branch_id: uuid.UUID
    profile_status: str
    row_version: int
    match_reasons: list[str] = []


class PatientAddressOut(BaseModel):
    region_id: uuid.UUID | None
    region: str | None
    district_id: uuid.UUID | None
    district: str | None
    locality_id: uuid.UUID | None
    locality: str | None
    address_line: str | None


class PatientDetailOut(PatientSearchOut):
    alternate_mobile: str | None = None
    address: PatientAddressOut | None = None
    lead_ids: list[uuid.UUID] = []


class ConversionPreviewOut(BaseModel):
    lead_id: uuid.UUID
    lead_name: str
    mobile: str | None
    age: int | None
    gender: str | None
    concern_text: str | None
    preferred_branch_id: uuid.UUID | None
    already_converted_patient_id: uuid.UUID | None = None
    candidates: list[PatientSearchOut] = []
