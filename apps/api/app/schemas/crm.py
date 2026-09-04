import uuid
from datetime import datetime
from pydantic import BaseModel, Field
from app.schemas.common import ORMModel


class LeadCreate(BaseModel):
    organization_id: uuid.UUID
    lead_name: str = Field(min_length=1, max_length=150)
    mobile: str
    age: int | None = None
    gender: str | None = None
    concern_text: str | None = None
    interested_service_id: uuid.UUID | None = None
    lead_source_id: uuid.UUID
    campaign_id: uuid.UUID | None = None
    preferred_branch_id: uuid.UUID | None = None
    lead_owner_user_id: uuid.UUID | None = None
    lead_status_id: uuid.UUID
    next_followup_at: datetime | None = None


class LeadUpdate(BaseModel):
    lead_name: str | None = None
    age: int | None = None
    gender: str | None = None
    concern_text: str | None = None
    preferred_branch_id: uuid.UUID | None = None
    lead_owner_user_id: uuid.UUID | None = None
    next_followup_at: datetime | None = None
    row_version: int


class LeadInteractionCreate(BaseModel):
    interaction_type: str
    channel: str | None = None
    summary: str | None = None
    outcome: str | None = None
    next_followup_at: datetime | None = None


class DncChange(BaseModel):
    dnc: bool
    reason: str | None = None


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
