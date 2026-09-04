import uuid
from pydantic import BaseModel


class LookupItem(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class NamedItem(BaseModel):
    id: uuid.UUID
    name: str


class DistrictItem(NamedItem):
    region_id: uuid.UUID


class LocalityItem(NamedItem):
    district_id: uuid.UUID
    approval_status: str


class BranchItem(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class DoctorItem(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class BootstrapOut(BaseModel):
    organization_id: uuid.UUID
    branches: list[BranchItem]
    doctors: list[DoctorItem]
    lead_sources: list[LookupItem]
    lead_statuses: list[LookupItem]
    lost_reasons: list[LookupItem]
    appointment_statuses: list[LookupItem]
    services: list[LookupItem]
    visit_types: list[LookupItem]
    visit_statuses: list[LookupItem]
    chief_complaints: list[NamedItem]
    regions: list[NamedItem]
    districts: list[DistrictItem]
    localities: list[LocalityItem]
