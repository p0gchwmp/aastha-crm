import uuid
from pydantic import BaseModel, Field


class ImportRowAction(BaseModel):
    action: str = Field(pattern="^(CREATE|CREATE_SEPARATE|LINK_EXISTING|SKIP)$")
    matched_patient_id: uuid.UUID | None = None


class ImportCommitRequest(BaseModel):
    registration_branch_id: uuid.UUID


class ImportBatchOut(BaseModel):
    import_batch_id: uuid.UUID
    file_name: str
    status: str
    total_rows: int
    imported_rows: int
    error_rows: int
    duplicate_rows: int
