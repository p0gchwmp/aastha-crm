import uuid
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from app.models.clinical import (
    ProcedureExecution,
    ProcedureExecutionStatus,
    ProcedureFinancialStatus,
    ProcedureOrder,
    ProcedureOrderStatus,
    Visit,
    VisitStatus,
)
from app.models.core import Branch, Doctor, Service, User
from app.models.integration import InboxEvent, OutboxEvent
from app.models.patient import Patient
from app.services.audit import log_audit

FINANCIAL_STATUSES = {
    "NOT_BILLED",
    "PAYMENT_PENDING",
    "PARTIALLY_PAID",
    "CLEARED",
    "COMPLIMENTARY",
    "FINANCIAL_HOLD",
    "CANCELLED",
}
PROCEDURE_READY_FINANCIAL_STATUSES = {"CLEARED", "COMPLIMENTARY"}


def _patient_for_org(db: Session, patient_id: uuid.UUID, organization_id: uuid.UUID) -> Patient:
    patient = db.get(Patient, patient_id)
    if not patient or patient.organization_id != organization_id:
        raise HTTPException(404, "Patient not found")
    return patient


def _order_for_org(db: Session, order_id: uuid.UUID, organization_id: uuid.UUID, *, lock: bool = False) -> ProcedureOrder:
    stmt = (
        select(ProcedureOrder)
        .join(Patient, Patient.patient_id == ProcedureOrder.patient_id)
        .where(ProcedureOrder.procedure_order_id == order_id, Patient.organization_id == organization_id)
    )
    if lock:
        stmt = stmt.with_for_update()
    order = db.scalar(stmt)
    if not order:
        raise HTTPException(404, "Procedure Order not found")
    return order


def _status(db: Session, model, code: str):
    item = db.scalar(select(model).where(model.code == code))
    if not item:
        raise HTTPException(503, f"Missing seeded status: {code}")
    return item


def _doctor_for_user(db: Session, user: User) -> Doctor:
    doctor = db.scalar(
        select(Doctor).where(
            Doctor.user_id == user.user_id,
            Doctor.organization_id == user.organization_id,
            Doctor.active.is_(True),
        )
    )
    if not doctor:
        raise HTTPException(403, "Current user is not linked to an active Doctor profile")
    return doctor


def create_order(
    db: Session,
    *,
    user: User,
    visit_id: uuid.UUID,
    service_id: uuid.UUID,
    notes: str | None,
) -> ProcedureOrder:
    doctor = _doctor_for_user(db, user)
    visit = db.get(Visit, visit_id)
    if not visit:
        raise HTTPException(404, "Visit not found")
    patient = _patient_for_org(db, visit.patient_id, user.organization_id)
    service = db.get(Service, service_id)
    if not service or service.organization_id != user.organization_id or not service.active:
        raise HTTPException(400, "Procedure service not found")
    if (service.clinical_type or "").upper() == "CONSULTATION":
        raise HTTPException(409, "Consultation service cannot be used as a Procedure Order")
    branch = db.get(Branch, visit.branch_id)
    if not branch or branch.organization_id != user.organization_id:
        raise HTTPException(400, "Visit branch not found")
    ordered = _status(db, ProcedureOrderStatus, "ORDERED")
    order = ProcedureOrder(
        patient_id=patient.patient_id,
        ordered_from_visit_id=visit.visit_id,
        service_id=service.service_id,
        ordered_by_doctor_id=doctor.doctor_id,
        ordering_branch_id=visit.branch_id,
        order_status_id=ordered.procedure_order_status_id,
        ordered_at=datetime.now(timezone.utc),
        notes=notes,
    )
    db.add(order)
    db.flush()
    db.add(
        ProcedureFinancialStatus(
            procedure_order_id=order.procedure_order_id,
            financial_status="NOT_BILLED",
            source_system="AASTHA_CRM",
            last_synced_at=datetime.now(timezone.utc),
        )
    )
    db.add(
        OutboxEvent(
            organization_id=user.organization_id,
            target_client_type="PROCEDURE_FINANCE",
            event_type="PROCEDURE_ORDER_CREATED",
            entity_type="PROCEDURE_ORDER",
            entity_id=order.procedure_order_id,
            payload={
                "procedure_order_id": str(order.procedure_order_id),
                "patient_id": str(patient.patient_id),
                "uhid": patient.uhid,
                "service_id": str(service.service_id),
                "service_code": service.service_code,
                "ordering_branch_id": str(visit.branch_id),
                "ordered_by_doctor_id": str(doctor.doctor_id),
                "ordered_at": order.ordered_at.isoformat(),
            },
            status="PENDING",
            attempt_count=0,
            created_at=datetime.now(timezone.utc),
        )
    )
    log_audit(
        db,
        organization_id=user.organization_id,
        entity_type="PROCEDURE_ORDER",
        entity_id=order.procedure_order_id,
        action="PROCEDURE_ORDER_CREATED",
        actor_user_id=user.user_id,
        after_data={"service_id": str(service_id), "financial_status": "NOT_BILLED"},
    )
    db.commit()
    db.refresh(order)
    return order


def financial_status(db: Session, order_id: uuid.UUID) -> ProcedureFinancialStatus:
    status = db.scalar(select(ProcedureFinancialStatus).where(ProcedureFinancialStatus.procedure_order_id == order_id))
    if not status:
        raise HTTPException(503, "Procedure financial-status projection missing")
    return status


def assert_financial_clearance(db: Session, order_id: uuid.UUID) -> ProcedureFinancialStatus:
    status = financial_status(db, order_id)
    if status.financial_status not in PROCEDURE_READY_FINANCIAL_STATUSES:
        raise HTTPException(409, f"Procedure cannot proceed: financial status is {status.financial_status}")
    return status


def build_inventory_event_payload(execution: ProcedureExecution, order: ProcedureOrder, service: Service | None, performed_at: datetime) -> dict:
    """Inventory receives stock-consumption context only; no Patient/PHI fields."""
    return {
        "procedure_execution_id": str(execution.procedure_execution_id),
        "procedure_order_id": str(order.procedure_order_id),
        "service_id": str(order.service_id),
        "service_code": service.service_code if service else None,
        "rendering_branch_id": str(execution.rendering_branch_id),
        "performed_by_doctor_id": str(execution.performed_by_doctor_id),
        "performed_at": performed_at.isoformat(),
    }


def create_execution(
    db: Session,
    *,
    user: User,
    order_id: uuid.UUID,
    rendering_branch_id: uuid.UUID,
    performed_visit_id: uuid.UUID,
    clinical_notes: str | None,
) -> ProcedureExecution:
    order = _order_for_org(db, order_id, user.organization_id, lock=True)
    assert_financial_clearance(db, order.procedure_order_id)
    doctor = _doctor_for_user(db, user)
    current_order_status = db.get(ProcedureOrderStatus, order.order_status_id)
    if current_order_status and current_order_status.code in {"COMPLETED", "CANCELLED"}:
        raise HTTPException(409, f"Cannot add a session to a {current_order_status.code.lower()} Procedure Order")
    branch = db.get(Branch, rendering_branch_id)
    if not branch or branch.organization_id != user.organization_id:
        raise HTTPException(400, "Rendering branch not found")
    visit = db.get(Visit, performed_visit_id)
    if not visit or visit.patient_id != order.patient_id:
        raise HTTPException(409, "Procedure execution Visit must belong to the Procedure Order Patient")
    if visit.branch_id != rendering_branch_id:
        raise HTTPException(409, "Rendering Branch must match the Procedure Visit branch")
    if visit.doctor_id and visit.doctor_id != doctor.doctor_id:
        raise HTTPException(409, "Procedure Visit is assigned to another Doctor")
    planned = _status(db, ProcedureExecutionStatus, "PLANNED")
    execution = ProcedureExecution(
        procedure_order_id=order.procedure_order_id,
        performed_visit_id=performed_visit_id,
        rendering_branch_id=rendering_branch_id,
        performed_by_doctor_id=doctor.doctor_id,
        execution_status_id=planned.procedure_execution_status_id,
        clinical_notes=clinical_notes,
    )
    db.add(execution)
    if not current_order_status or current_order_status.code not in {"PARTIALLY_COMPLETED", "COMPLETED"}:
        ready = _status(db, ProcedureOrderStatus, "READY")
        order.order_status_id = ready.procedure_order_status_id
        order.row_version += 1
    db.flush()
    log_audit(
        db,
        organization_id=user.organization_id,
        entity_type="PROCEDURE_EXECUTION",
        entity_id=execution.procedure_execution_id,
        action="PROCEDURE_EXECUTION_PLANNED",
        actor_user_id=user.user_id,
        after_data={"procedure_order_id": str(order_id), "rendering_branch_id": str(rendering_branch_id)},
    )
    db.commit()
    db.refresh(execution)
    return execution


def start_execution(db: Session, *, user: User, execution_id: uuid.UUID, row_version: int) -> ProcedureExecution:
    stmt = (
        select(ProcedureExecution)
        .join(ProcedureOrder, ProcedureOrder.procedure_order_id == ProcedureExecution.procedure_order_id)
        .join(Patient, Patient.patient_id == ProcedureOrder.patient_id)
        .where(ProcedureExecution.procedure_execution_id == execution_id, Patient.organization_id == user.organization_id)
        .with_for_update()
    )
    execution = db.scalar(stmt)
    if not execution:
        raise HTTPException(404, "Procedure Execution not found")
    if execution.row_version != row_version:
        raise HTTPException(409, "Procedure Execution was updated by another user")
    assert_financial_clearance(db, execution.procedure_order_id)
    if execution.completed_at:
        raise HTTPException(409, "Completed Procedure Execution cannot be restarted")
    in_progress = _status(db, ProcedureExecutionStatus, "IN_PROGRESS")
    execution.execution_status_id = in_progress.procedure_execution_status_id
    execution.started_at = execution.started_at or datetime.now(timezone.utc)
    execution.row_version += 1
    visit = db.get(Visit, execution.performed_visit_id) if execution.performed_visit_id else None
    if visit:
        visit_in_progress = _status(db, VisitStatus, "IN_PROGRESS")
        visit.visit_status_id = visit_in_progress.visit_status_id
        visit.started_at = visit.started_at or execution.started_at
        visit.row_version += 1
    db.commit(); db.refresh(execution)
    return execution


def complete_execution(
    db: Session,
    *,
    user: User,
    execution_id: uuid.UUID,
    row_version: int,
    clinical_notes: str | None,
) -> ProcedureExecution:
    stmt = (
        select(ProcedureExecution)
        .join(ProcedureOrder, ProcedureOrder.procedure_order_id == ProcedureExecution.procedure_order_id)
        .join(Patient, Patient.patient_id == ProcedureOrder.patient_id)
        .where(ProcedureExecution.procedure_execution_id == execution_id, Patient.organization_id == user.organization_id)
        .with_for_update()
    )
    execution = db.scalar(stmt)
    if not execution:
        raise HTTPException(404, "Procedure Execution not found")
    if execution.row_version != row_version:
        raise HTTPException(409, "Procedure Execution was updated by another user")
    assert_financial_clearance(db, execution.procedure_order_id)
    if execution.completed_at:
        raise HTTPException(409, "Procedure Execution is already completed")
    completed_status = _status(db, ProcedureExecutionStatus, "COMPLETED")
    now = datetime.now(timezone.utc)
    execution.execution_status_id = completed_status.procedure_execution_status_id
    execution.started_at = execution.started_at or now
    execution.completed_at = now
    if clinical_notes is not None:
        execution.clinical_notes = clinical_notes
    execution.row_version += 1
    visit = db.get(Visit, execution.performed_visit_id) if execution.performed_visit_id else None
    if visit:
        visit_completed = _status(db, VisitStatus, "COMPLETED")
        visit.visit_status_id = visit_completed.visit_status_id
        visit.started_at = visit.started_at or execution.started_at
        visit.completed_at = now
        visit.row_version += 1
    order = _order_for_org(db, execution.procedure_order_id, user.organization_id, lock=True)
    partial_order = _status(db, ProcedureOrderStatus, "PARTIALLY_COMPLETED")
    current_order_status = db.get(ProcedureOrderStatus, order.order_status_id)
    if not current_order_status or current_order_status.code != "COMPLETED":
        order.order_status_id = partial_order.procedure_order_status_id
        order.row_version += 1
    service = db.get(Service, order.service_id)
    db.add(
        OutboxEvent(
            organization_id=user.organization_id,
            target_client_type="INVENTORY",
            event_type="PROCEDURE_COMPLETED",
            entity_type="PROCEDURE_EXECUTION",
            entity_id=execution.procedure_execution_id,
            payload=build_inventory_event_payload(execution, order, service, now),
            status="PENDING",
            attempt_count=0,
            created_at=now,
        )
    )
    log_audit(
        db,
        organization_id=user.organization_id,
        entity_type="PROCEDURE_EXECUTION",
        entity_id=execution.procedure_execution_id,
        action="PROCEDURE_COMPLETED",
        actor_user_id=user.user_id,
        after_data={
            "procedure_order_id": str(order.procedure_order_id),
            "rendering_branch_id": str(execution.rendering_branch_id),
        },
    )
    db.commit(); db.refresh(execution)
    return execution


def apply_external_financial_status(
    db: Session,
    *,
    integration_client_id: uuid.UUID,
    organization_id: uuid.UUID,
    order_id: uuid.UUID,
    external_event_id: str,
    new_status: str,
    external_reference: str | None,
    payload: dict,
) -> ProcedureFinancialStatus:
    if new_status not in FINANCIAL_STATUSES:
        raise HTTPException(400, "Unsupported procedure financial status")
    reserve = (
        pg_insert(InboxEvent)
        .values(
            integration_client_id=integration_client_id,
            external_event_id=external_event_id,
            event_type="PROCEDURE_FINANCIAL_STATUS_CHANGED",
            payload=payload,
            received_at=datetime.now(timezone.utc),
            processing_status="PROCESSING",
        )
        .on_conflict_do_nothing(index_elements=["integration_client_id", "external_event_id"])
        .returning(InboxEvent.inbox_event_id)
    )
    reserved_id = db.scalar(reserve)
    if reserved_id is None:
        existing_event = db.scalar(
            select(InboxEvent).where(
                InboxEvent.integration_client_id == integration_client_id,
                InboxEvent.external_event_id == external_event_id,
            )
        )
        existing_order = (existing_event.payload or {}).get("procedure_order_id") if existing_event else None
        if existing_order and existing_order != str(order_id):
            raise HTTPException(409, "External event ID was already used for another Procedure Order")
        return financial_status(db, order_id)
    order = _order_for_org(db, order_id, organization_id, lock=True)
    projection = db.scalar(
        select(ProcedureFinancialStatus)
        .where(ProcedureFinancialStatus.procedure_order_id == order.procedure_order_id)
        .with_for_update()
    )
    if not projection:
        projection = ProcedureFinancialStatus(procedure_order_id=order.procedure_order_id)
        db.add(projection); db.flush()
    before = projection.financial_status
    projection.financial_status = new_status
    projection.source_system = "EXTERNAL_PROCEDURE_FINANCE"
    projection.external_reference = external_reference
    projection.last_synced_at = datetime.now(timezone.utc)
    current_order_status = db.get(ProcedureOrderStatus, order.order_status_id)
    # Finance may change after treatment, but it must never rewrite completed clinical history.
    if not current_order_status or current_order_status.code not in {"PARTIALLY_COMPLETED", "COMPLETED"}:
        if new_status in PROCEDURE_READY_FINANCIAL_STATUSES:
            ready = _status(db, ProcedureOrderStatus, "READY")
            order.order_status_id = ready.procedure_order_status_id
        elif new_status in {"PAYMENT_PENDING", "PARTIALLY_PAID", "FINANCIAL_HOLD", "NOT_BILLED"}:
            hold = _status(db, ProcedureOrderStatus, "FINANCIAL_HOLD")
            order.order_status_id = hold.procedure_order_status_id
        elif new_status == "CANCELLED":
            cancelled = _status(db, ProcedureOrderStatus, "CANCELLED")
            order.order_status_id = cancelled.procedure_order_status_id
        order.row_version += 1
    now = datetime.now(timezone.utc)
    reserved = db.get(InboxEvent, reserved_id)
    reserved.processed_at = now
    reserved.processing_status = "PROCESSED"
    log_audit(
        db,
        organization_id=organization_id,
        entity_type="PROCEDURE_ORDER",
        entity_id=order.procedure_order_id,
        action="PROCEDURE_FINANCIAL_STATUS_SYNCED",
        actor_user_id=None,
        integration_client_id=integration_client_id,
        before_data={"financial_status": before},
        after_data={"financial_status": new_status, "external_reference": external_reference},
    )
    db.commit(); db.refresh(projection)
    return projection


def close_order(db: Session, *, user: User, order_id: uuid.UUID, row_version: int) -> ProcedureOrder:
    order = _order_for_org(db, order_id, user.organization_id, lock=True)
    _doctor_for_user(db, user)
    if order.row_version != row_version:
        raise HTTPException(409, "Procedure Order was updated by another user")
    completed_sessions = db.scalar(
        select(func.count(ProcedureExecution.procedure_execution_id))
        .join(ProcedureExecutionStatus, ProcedureExecutionStatus.procedure_execution_status_id == ProcedureExecution.execution_status_id)
        .where(ProcedureExecution.procedure_order_id == order_id, ProcedureExecutionStatus.code == "COMPLETED")
    ) or 0
    if completed_sessions < 1:
        raise HTTPException(409, "Complete at least one Procedure session before closing the order")
    completed = _status(db, ProcedureOrderStatus, "COMPLETED")
    order.order_status_id = completed.procedure_order_status_id
    order.row_version += 1
    log_audit(
        db, organization_id=user.organization_id, entity_type="PROCEDURE_ORDER", entity_id=order_id,
        action="PROCEDURE_ORDER_CLOSED", actor_user_id=user.user_id,
        after_data={"completed_sessions": completed_sessions},
    )
    db.commit(); db.refresh(order)
    return order


def cancel_order(db: Session, *, user: User, order_id: uuid.UUID, row_version: int, reason: str) -> ProcedureOrder:
    order = _order_for_org(db, order_id, user.organization_id, lock=True)
    _doctor_for_user(db, user)
    if order.row_version != row_version:
        raise HTTPException(409, "Procedure Order was updated by another user")
    completed_sessions = db.scalar(
        select(func.count(ProcedureExecution.procedure_execution_id))
        .join(ProcedureExecutionStatus, ProcedureExecutionStatus.procedure_execution_status_id == ProcedureExecution.execution_status_id)
        .where(ProcedureExecution.procedure_order_id == order_id, ProcedureExecutionStatus.code == "COMPLETED")
    ) or 0
    if completed_sessions:
        raise HTTPException(409, "Procedure Order with completed sessions cannot be cancelled; close the order instead")
    cancelled = _status(db, ProcedureOrderStatus, "CANCELLED")
    order.order_status_id = cancelled.procedure_order_status_id
    order.row_version += 1
    db.add(
        OutboxEvent(
            organization_id=user.organization_id, target_client_type="PROCEDURE_FINANCE",
            event_type="PROCEDURE_ORDER_CANCELLED", entity_type="PROCEDURE_ORDER", entity_id=order_id,
            payload={"procedure_order_id": str(order_id), "reason": reason},
            status="PENDING", attempt_count=0, created_at=datetime.now(timezone.utc),
        )
    )
    log_audit(
        db, organization_id=user.organization_id, entity_type="PROCEDURE_ORDER", entity_id=order_id,
        action="PROCEDURE_ORDER_CANCELLED", actor_user_id=user.user_id, reason=reason,
    )
    db.commit(); db.refresh(order)
    return order
