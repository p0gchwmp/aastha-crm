import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo
import re
from pydantic import BaseModel, Field, model_validator
from app.schemas.common import ORMModel


class PatientCreate(BaseModel):
    organization_id: uuid.UUID
    full_name: str = Field(min_length=1, max_length=180)
    mobile: str | None = Field(default=None,max_length=30)
    alternate_mobile: str | None = Field(default=None,max_length=30)
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
    registration_request_id: uuid.UUID | None = None
    identity_verified: bool = False
    age_years: int | None = Field(default=None, ge=0, le=130)

    @model_validator(mode="after")
    def validate_demographics(self):
        self.full_name = self.full_name.strip()
        if not self.full_name:
            raise ValueError("Patient name is required")
        for field in ("mobile", "alternate_mobile"):
            value = getattr(self, field)
            if value:
                digits = re.sub(r"\D", "", value)
                if not re.fullmatch(r"[+()\d\s-]+",value) or len(digits) not in (10, 12) or (len(digits) == 12 and not digits.startswith("91")):
                    raise ValueError("Use a 10-digit mobile number, optionally prefixed with +91")
        if self.gender not in (None, "", "Female", "Male", "Other", "Unknown"):
            raise ValueError("Select a supported gender")
        if self.dob and self.dob > datetime.now(ZoneInfo("Asia/Kolkata")).date():
            raise ValueError("DOB cannot be in the future")
        if self.dob and self.age_years is not None:
            raise ValueError("Enter DOB or approximate age, not both")
        return self



class LeadPatientConversionCreate(PatientCreate):
    existing_patient_id: uuid.UUID | None = None
    lead_row_version: int = Field(ge=1)
    existing_patient_row_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_existing_patient_mode(self):
        if self.existing_patient_id:
            # Registration payload can remain prefilled for UI convenience, but existing identity wins.
            self.duplicate_override_confirmed = True
        return self


class PatientUpdate(BaseModel):
    row_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)
    age_years: int | None = Field(default=None, ge=0, le=130)
    full_name: str | None = Field(default=None, min_length=1, max_length=180)
    gender: str | None = None
    dob: date | None = None
    dob_is_estimated: bool | None = None
    profile_status: str | None = None
    mobile: str | None = Field(default=None,max_length=30)
    alternate_mobile: str | None = Field(default=None,max_length=30)
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
    dob_is_estimated: bool = False
    age_is_estimated: bool = False
    age_recorded_on: date | None = None
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
    lead_row_version: int
    mobile: str | None
    age: int | None
    gender: str | None
    concern_text: str | None
    preferred_branch_id: uuid.UUID | None
    already_converted_patient_id: uuid.UUID | None = None
    candidates: list[PatientSearchOut] = []
