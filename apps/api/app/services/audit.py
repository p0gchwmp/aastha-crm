import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.integration import AuditEvent


def log_audit(
    db: Session,
    *,
    organization_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    actor_user_id: uuid.UUID | None,
    before_data: dict | None = None,
    after_data: dict | None = None,
    reason: str | None = None,
    integration_client_id: uuid.UUID | None = None,
) -> AuditEvent:
    event = AuditEvent(
        organization_id=organization_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_user_id=actor_user_id,
        integration_client_id=integration_client_id,
        before_data=before_data,
        after_data=after_data,
        reason=reason,
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(event)
    db.flush()
    return event
