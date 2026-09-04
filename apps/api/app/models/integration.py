import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, TimestampMixin


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = {"schema": "audit"}
    audit_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.organizations.organization_id"))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(80))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("core.users.user_id"))
    integration_client_id: Mapped[uuid.UUID | None]
    before_data: Mapped[dict | None]
    after_data: Mapped[dict | None]
    reason: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IntegrationClient(Base, TimestampMixin):
    __tablename__ = "clients"
    __table_args__ = {"schema": "integration"}
    integration_client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.organizations.organization_id"))
    client_name: Mapped[str] = mapped_column(String(160))
    client_type: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default="ACTIVE")
    allowed_scopes: Mapped[dict] = mapped_column(default=dict)
    credential_hash: Mapped[str] = mapped_column(String(255))


class ExternalReference(Base):
    __tablename__ = "external_references"
    __table_args__ = (
        UniqueConstraint("integration_client_id", "entity_type", "external_id"),
        {"schema": "integration"},
    )
    external_reference_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    integration_client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("integration.clients.integration_client_id"))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    external_id: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = {"schema": "integration"}
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.organizations.organization_id"))
    target_client_type: Mapped[str | None] = mapped_column(String(80))
    event_type: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    payload: Mapped[dict] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(40), default="PENDING")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InboxEvent(Base):
    __tablename__ = "inbox_events"
    __table_args__ = (
        UniqueConstraint("integration_client_id", "external_event_id"),
        {"schema": "integration"},
    )
    inbox_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    integration_client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("integration.clients.integration_client_id"))
    external_event_id: Mapped[str] = mapped_column(String(180))
    event_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(default=dict)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_status: Mapped[str] = mapped_column(String(40), default="RECEIVED")


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("integration_client_id", "idempotency_key"),
        {"schema": "integration"},
    )
    idempotency_key_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    integration_client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("integration.clients.integration_client_id"))
    idempotency_key: Mapped[str] = mapped_column(String(180))
    request_hash: Mapped[str] = mapped_column(String(128))
    response_reference: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
