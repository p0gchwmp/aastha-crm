import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.models.clinical import ProcedureExecution, ProcedureFinancialStatus, ProcedureOrder
from app.models.core import Branch, Doctor, Service
from app.models.integration import IntegrationClient, OutboxEvent
from app.models.patient import Patient
from app.schemas.procedures import EventAckRequest, FinancialStatusCallback
from app.services.integration_auth import require_integration_scope
from app.services import procedures as procedure_service

router = APIRouter(prefix="/external/procedures", tags=["procedure-integrations"])


@router.get("/orders/{order_id}")
def external_order(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    client: IntegrationClient = Depends(require_integration_scope("procedure_order.read")),
):
    order = procedure_service._order_for_org(db, order_id, client.organization_id)
    patient = db.get(Patient, order.patient_id)
    service = db.get(Service, order.service_id)
    doctor = db.get(Doctor, order.ordered_by_doctor_id)
    branch = db.get(Branch, order.ordering_branch_id)
    projection = procedure_service.financial_status(db, order.procedure_order_id)
    # Finance receives only identifiers/demographics needed for billing, not clinical notes/history.
    return {
        "procedure_order_id": order.procedure_order_id,
        "patient": {"patient_id": patient.patient_id, "uhid": patient.uhid, "name": patient.full_name},
        "service": {"service_id": service.service_id, "code": service.service_code, "name": service.service_name},
        "doctor": {"doctor_id": doctor.doctor_id, "name": doctor.doctor_name},
        "ordering_branch": {"branch_id": branch.branch_id, "name": branch.branch_name},
        "ordered_at": order.ordered_at,
        "financial_status": projection.financial_status,
        "external_reference": projection.external_reference,
    }


@router.post("/orders/{order_id}/financial-status")
def financial_status_callback(
    order_id: uuid.UUID,
    payload: FinancialStatusCallback,
    db: Session = Depends(get_db),
    client: IntegrationClient = Depends(require_integration_scope("procedure_financial_status.write")),
):
    projection = procedure_service.apply_external_financial_status(
        db,
        integration_client_id=client.integration_client_id,
        organization_id=client.organization_id,
        order_id=order_id,
        external_event_id=payload.external_event_id,
        new_status=payload.financial_status,
        external_reference=payload.external_reference,
        payload={**payload.model_dump(mode="json"), "procedure_order_id": str(order_id)},
    )
    return {
        "procedure_order_id": order_id,
        "financial_status": projection.financial_status,
        "external_reference": projection.external_reference,
        "last_synced_at": projection.last_synced_at,
    }


@router.get("/finance-events")
def finance_events(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    client: IntegrationClient = Depends(require_integration_scope("procedure_order_event.read")),
):
    rows = list(db.scalars(
        select(OutboxEvent).where(
            OutboxEvent.organization_id == client.organization_id,
            OutboxEvent.target_client_type == client.client_type,
            OutboxEvent.event_type.in_(["PROCEDURE_ORDER_CREATED", "PROCEDURE_ORDER_CANCELLED"]),
            OutboxEvent.status == "PENDING",
        ).order_by(OutboxEvent.created_at).limit(limit)
    ).all())
    return [{"event_id": x.event_id, "event_type": x.event_type, "payload": x.payload, "created_at": x.created_at} for x in rows]


@router.post("/finance-events/{event_id}/ack")
def acknowledge_finance_event(
    event_id: uuid.UUID,
    payload: EventAckRequest,
    db: Session = Depends(get_db),
    client: IntegrationClient = Depends(require_integration_scope("procedure_order_event.ack")),
):
    event = db.scalar(
        select(OutboxEvent).where(
            OutboxEvent.event_id == event_id,
            OutboxEvent.organization_id == client.organization_id,
            OutboxEvent.target_client_type == client.client_type,
            OutboxEvent.event_type.in_(["PROCEDURE_ORDER_CREATED", "PROCEDURE_ORDER_CANCELLED"]),
        ).with_for_update()
    )
    if not event:
        raise HTTPException(404, "Procedure Finance event not found")
    if event.status == "SENT":
        return {"event_id": event.event_id, "status": event.status, "external_event_id": payload.external_event_id}
    event.status = "SENT"
    event.sent_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    event.attempt_count += 1
    db.commit()
    return {"event_id": event.event_id, "status": event.status, "external_event_id": payload.external_event_id}


@router.get("/inventory-events")
def inventory_events(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    client: IntegrationClient = Depends(require_integration_scope("inventory_event.read")),
):
    # Inventory sees only procedure-completion payloads. Patient identity is intentionally absent.
    rows = list(db.scalars(
        select(OutboxEvent).where(
            OutboxEvent.organization_id == client.organization_id,
            OutboxEvent.target_client_type == client.client_type,
            OutboxEvent.event_type == "PROCEDURE_COMPLETED",
            OutboxEvent.status == "PENDING",
        ).order_by(OutboxEvent.created_at).limit(limit)
    ).all())
    return [
        {"event_id": x.event_id, "event_type": x.event_type, "payload": x.payload, "created_at": x.created_at}
        for x in rows
    ]


@router.post("/inventory-events/{event_id}/ack")
def acknowledge_inventory_event(
    event_id: uuid.UUID,
    payload: EventAckRequest,
    db: Session = Depends(get_db),
    client: IntegrationClient = Depends(require_integration_scope("inventory_event.ack")),
):
    event = db.scalar(
        select(OutboxEvent).where(
            OutboxEvent.event_id == event_id,
            OutboxEvent.organization_id == client.organization_id,
            OutboxEvent.target_client_type == client.client_type,
            OutboxEvent.event_type == "PROCEDURE_COMPLETED",
        ).with_for_update()
    )
    if not event:
        raise HTTPException(404, "Inventory event not found")
    if event.status == "SENT":
        return {"event_id": event.event_id, "status": event.status, "external_event_id": payload.external_event_id}
    event.status = "SENT"
    event.sent_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    event.attempt_count += 1
    db.commit()
    return {"event_id": event.event_id, "status": event.status, "external_event_id": payload.external_event_id}
