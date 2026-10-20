import uuid
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, AwareDatetime, ConfigDict
from app.schemas.common import ORMModel


class LeadFields(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    @field_validator("mobile", check_fields=False)
    @classmethod
    def mobile_valid(cls, value):
        if value is None:
            return value
        import re
        digits = re.sub(r"\D", "", value)
        if not (len(digits) == 10 or (len(digits) == 12 and digits.startswith("91"))):
            raise ValueError("Enter a 10-digit mobile number, optionally with +91")
        return value


class LeadCreate(LeadFields):
    organization_id: uuid.UUID
    lead_name: str = Field(min_length=1, max_length=150)
    mobile: str
    age: int | None = Field(default=None, ge=0, le=130)
    gender: str | None = Field(default=None, max_length=30)
    concern_text: str | None = Field(default=None, max_length=5000)
    interested_service_id: uuid.UUID | None = None
    lead_source_id: uuid.UUID
    campaign_id: uuid.UUID | None = None
    preferred_branch_id: uuid.UUID | None = None
    lead_owner_user_id: uuid.UUID | None = None
    lead_status_id: uuid.UUID
    next_followup_at: AwareDatetime | None = None


class LeadUpdate(LeadFields):
    lead_name: str | None = Field(default=None, min_length=1, max_length=150)
    mobile: str | None = None
    lead_source_id: uuid.UUID | None = None
    lead_status_id: uuid.UUID | None = None
    lost_reason_id: uuid.UUID | None = None
    age: int | None = Field(default=None, ge=0, le=130)
    gender: str | None = Field(default=None, max_length=30)
    concern_text: str | None = Field(default=None, max_length=5000)
    preferred_branch_id: uuid.UUID | None = None
    lead_owner_user_id: uuid.UUID | None = None
    next_followup_at: AwareDatetime | None = None
    row_version: int = Field(ge=1)


class LeadInteractionCreate(LeadFields):
    row_version: int = Field(ge=1)
    interaction_type: str = Field(min_length=1, max_length=60)
    channel: str | None = Field(default=None, max_length=60)
    summary: str | None = Field(default=None, max_length=5000)
    outcome: str | None = Field(default=None, max_length=80)
    next_followup_at: AwareDatetime | None = None


class LeadVersion(BaseModel):
    row_version: int = Field(ge=1)


class DncChange(LeadVersion):
    dnc: bool
    reason: str | None = Field(default=None, max_length=500)


class LeadOut(ORMModel):
    lead_id: uuid.UUID
    lead_name: str
    concern_text: str | None
    dnc: bool
    next_followup_at: datetime | None
    row_version: int


class ThirdPartyAssignmentCreate(BaseModel):
    partner_id: uuid.UUID
    valid_until: datetime | None = None
