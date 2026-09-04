import uuid
from typing import Literal
from pydantic import BaseModel, Field


class LocalityProposalCreate(BaseModel):
    district_id: uuid.UUID
    name: str = Field(min_length=2, max_length=140)


class ComplaintProposalCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)


class MasterResolve(BaseModel):
    action: Literal["APPROVE", "CORRECT", "MERGE", "REJECT"]
    corrected_name: str | None = Field(default=None, min_length=2, max_length=160)
    merge_into_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=500)


class PendingMasterItem(BaseModel):
    master_type: str
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None = None
    created_by: uuid.UUID | None = None
    created_by_name: str | None = None
    created_at: str | None = None
    usage_count: int = 0
