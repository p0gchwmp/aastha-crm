import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin


class LeadSource(Base):
    __tablename__ = "lead_sources"
    __table_args__ = {"schema": "crm"}
    lead_source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class LeadStatus(Base):
    __tablename__ = "lead_statuses"
    __table_args__ = {"schema": "crm"}
    lead_status_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    terminal: Mapped[bool] = mapped_column(Boolean, default=False)


class LostReason(Base):
    __tablename__ = "lost_reasons"
    __table_args__ = {"schema": "crm"}
    lost_reason_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Campaign(Base, TimestampMixin):
    __tablename__ = "campaigns"
    __table_args__ = {"schema": "crm"}
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_name: Mapped[str] = mapped_column(String(150))
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crm.lead_sources.lead_source_id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Lead(Base, TimestampMixin):
    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_crm_leads_name", "lead_name"),
        Index("ix_crm_leads_next_followup", "next_followup_at"),
        {"schema": "crm"},
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.organizations.organization_id"))
    lead_name: Mapped[str] = mapped_column(String(150))
    age: Mapped[int | None]
    gender: Mapped[str | None] = mapped_column(String(30))
    concern_text: Mapped[str | None] = mapped_column(Text)
    interested_service_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.services.service_id"))
    lead_source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crm.lead_sources.lead_source_id"))
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crm.campaigns.campaign_id"))
    preferred_branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.branches.branch_id"))
    lead_owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.users.user_id"))
    lead_status_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crm.lead_statuses.lead_status_id"))
    lost_reason_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crm.lost_reasons.lost_reason_id"))
    dnc: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    next_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_interaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.users.user_id"))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.users.user_id"))
    extension_attributes: Mapped[dict] = mapped_column(default=dict)


class LeadContact(Base):
    __tablename__ = "lead_contacts"
    __table_args__ = (
        Index("ix_crm_lead_contacts_normalized", "normalized_value"),
        {"schema": "crm"},
    )
    lead_contact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crm.leads.lead_id"))
    contact_type: Mapped[str] = mapped_column(String(40))
    contact_value: Mapped[str] = mapped_column(String(200))
    normalized_value: Mapped[str] = mapped_column(String(200))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)


class LeadInteraction(Base):
    __tablename__ = "lead_interactions"
    __table_args__ = {"schema": "crm"}
    interaction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crm.leads.lead_id"))
    interaction_type: Mapped[str] = mapped_column(String(60))
    channel: Mapped[str | None] = mapped_column(String(60))
    interaction_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    performed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.users.user_id"))
    integration_client_id: Mapped[uuid.UUID | None]
    external_partner_id: Mapped[uuid.UUID | None]
    summary: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(String(80))
    next_followup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict] = mapped_column(default=dict)


class LeadStatusHistory(Base):
    __tablename__ = "lead_status_history"
    __table_args__ = {"schema": "crm"}
    history_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crm.leads.lead_id"))
    old_status_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crm.lead_statuses.lead_status_id"))
    new_status_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crm.lead_statuses.lead_status_id"))
    changed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.users.user_id"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)


class LeadDncHistory(Base):
    __tablename__ = "lead_dnc_history"
    __table_args__ = {"schema": "crm"}
    history_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crm.leads.lead_id"))
    old_dnc: Mapped[bool] = mapped_column(Boolean)
    new_dnc: Mapped[bool] = mapped_column(Boolean)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.users.user_id"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)


class LeadPatientLink(Base):
    __tablename__ = "lead_patient_links"
    __table_args__ = (UniqueConstraint("lead_id"), {"schema": "crm"})
    lead_patient_link_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crm.leads.lead_id"))
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.patients.patient_id"))
    link_type: Mapped[str] = mapped_column(String(60))
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    linked_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.users.user_id"))


class ExternalPartner(Base, TimestampMixin):
    __tablename__ = "external_partners"
    __table_args__ = {"schema": "crm"}
    partner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    partner_name: Mapped[str] = mapped_column(String(160))
    partner_type: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    allowed_data_scope: Mapped[dict] = mapped_column(default=dict)


class LeadExternalAssignment(Base, TimestampMixin):
    __tablename__ = "lead_external_assignments"
    __table_args__ = {"schema": "crm"}
    assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crm.leads.lead_id"))
    partner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crm.external_partners.partner_id"))
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.users.user_id"))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), default="ACTIVE")


class LeadExportJob(Base, TimestampMixin):
    __tablename__ = "lead_export_jobs"
    __table_args__ = {"schema": "crm"}
    export_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    partner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crm.external_partners.partner_id"))
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.users.user_id"))
    export_purpose: Mapped[str] = mapped_column(String(80))
    filters_json: Mapped[dict] = mapped_column(default=dict)
    record_count: Mapped[int] = mapped_column(default=0)
    format: Mapped[str] = mapped_column(String(20))
    purpose_note: Mapped[str | None] = mapped_column(Text)


class LeadExportItem(Base):
    __tablename__ = "lead_export_items"
    __table_args__ = (UniqueConstraint("export_id", "lead_id"), {"schema": "crm"})
    export_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    export_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crm.lead_export_jobs.export_id"))
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crm.leads.lead_id"))
