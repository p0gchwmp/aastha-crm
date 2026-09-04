import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.permissions import require_permission
from app.models.clinical import (
    ProcedureExecution,
    ProcedureExecutionStatus,
    ProcedureFinancialStatus,
    ProcedureOrder,
    ProcedureOrderStatus,
    Visit,
)
from app.models.core import Branch, Doctor, Service, User
from app.models.patient import Patient
from app.schemas.procedures import (
    ProcedureExecutionCompleteRequest,
    ProcedureExecutionCreateRequest,
    ProcedureOrderCreateRequest,
    ProcedureOrderCancelRequest,
)
from app.services import procedures as service

router = APIRouter(prefix="/procedures", tags=["procedures"])


def _serialize_order(db: Session, order: ProcedureOrder) -> dict:
    patient = db.get(Patient, order.patient_id)
    procedure_service = db.get(Service, order.service_id)
    doctor = db.get(Doctor, order.ordered_by_doctor_id)
    branch = db.get(Branch, order.ordering_branch_id)
    order_status = db.get(ProcedureOrderStatus, order.order_status_id)
    financial = db.scalar(select(ProcedureFinancialStatus).where(ProcedureFinancialStatus.procedure_order_id == order.procedure_order_id))
    executions = list(db.scalars(select(ProcedureExecution).where(ProcedureExecution.procedure_order_id == order.procedure_order_id).order_by(ProcedureExecution.created_at)).all())
    return {
        "procedure_order_id": order.procedure_order_id,
        "patient_id": order.patient_id,
        "patient_name": patient.full_name if patient else None,
        "uhid": patient.uhid if patient else None,
        "ordered_from_visit_id": order.ordered_from_visit_id,
        "service_id": order.service_id,
        "service_code": procedure_service.service_code if procedure_service else None,
        "service_name": procedure_service.service_name if procedure_service else None,
        "doctor_id": order.ordered_by_doctor_id,
        "doctor": doctor.doctor_name if doctor else None,
        "ordering_branch_id": order.ordering_branch_id,
        "ordering_branch": branch.branch_name if branch else None,
        "order_status": order_status.code if order_status else None,
        "financial_status": financial.financial_status if financial else "NOT_BILLED",
        "external_reference": financial.external_reference if financial else None,
        "ordered_at": order.ordered_at,
        "notes": order.notes,
        "row_version": order.row_version,
        "executions": [_serialize_execution(db, x) for x in executions],
    }


def _serialize_execution(db: Session, execution: ProcedureExecution) -> dict:
    status = db.get(ProcedureExecutionStatus, execution.execution_status_id)
    branch = db.get(Branch, execution.rendering_branch_id)
    doctor = db.get(Doctor, execution.performed_by_doctor_id)
    return {
        "procedure_execution_id": execution.procedure_execution_id,
        "procedure_order_id": execution.procedure_order_id,
        "performed_visit_id": execution.performed_visit_id,
        "rendering_branch_id": execution.rendering_branch_id,
        "rendering_branch": branch.branch_name if branch else None,
        "performed_by_doctor_id": execution.performed_by_doctor_id,
        "doctor": doctor.doctor_name if doctor else None,
        "status": status.code if status else None,
        "started_at": execution.started_at,
        "completed_at": execution.completed_at,
        "clinical_notes": execution.clinical_notes,
        "row_version": execution.row_version,
    }


@router.get("/setup")
def setup(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PROCEDURE_VIEW")),
):
    services = list(db.scalars(select(Service).where(Service.organization_id == user.organization_id, Service.active.is_(True), Service.clinical_type != "CONSULTATION").order_by(Service.service_name)).all())
    return {
        "services": [{"id": x.service_id, "code": x.service_code, "name": x.service_name} for x in services],
        "financial_statuses": sorted(service.FINANCIAL_STATUSES),
        "ready_financial_statuses": sorted(service.PROCEDURE_READY_FINANCIAL_STATUSES),
    }


@router.get("/orders")
def list_orders(
    patient_id: uuid.UUID | None = None,
    financial_status: str | None = None,
    limit: int = Query(100, ge=1, le=250),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PROCEDURE_VIEW")),
):
    stmt = select(ProcedureOrder).join(Patient, Patient.patient_id == ProcedureOrder.patient_id).where(Patient.organization_id == user.organization_id)
    if patient_id:
        stmt = stmt.where(ProcedureOrder.patient_id == patient_id)
    if financial_status:
        stmt = stmt.join(ProcedureFinancialStatus, ProcedureFinancialStatus.procedure_order_id == ProcedureOrder.procedure_order_id).where(ProcedureFinancialStatus.financial_status == financial_status)
    rows = list(db.scalars(stmt.order_by(ProcedureOrder.ordered_at.desc()).limit(limit)).all())
    return [_serialize_order(db, x) for x in rows]


@router.post("/orders")
def create_order(
    payload: ProcedureOrderCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PROCEDURE_ORDER_CREATE")),
):
    order = service.create_order(db, user=user, visit_id=payload.visit_id, service_id=payload.service_id, notes=payload.notes)
    return _serialize_order(db, order)


@router.get("/orders/{order_id}")
def order_detail(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PROCEDURE_VIEW")),
):
    order = service._order_for_org(db, order_id, user.organization_id)
    return _serialize_order(db, order)


@router.post("/orders/{order_id}/cancel")
def cancel_order(
    order_id: uuid.UUID,
    payload: ProcedureOrderCancelRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PROCEDURE_ORDER_CREATE")),
):
    order = service.cancel_order(db, user=user, order_id=order_id, row_version=payload.row_version, reason=payload.reason)
    return _serialize_order(db, order)


@router.post("/orders/{order_id}/close")
def close_order(
    order_id: uuid.UUID,
    row_version: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PROCEDURE_EXECUTE")),
):
    order = service.close_order(db, user=user, order_id=order_id, row_version=row_version)
    return _serialize_order(db, order)


@router.post("/orders/{order_id}/executions")
def create_execution(
    order_id: uuid.UUID,
    payload: ProcedureExecutionCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PROCEDURE_EXECUTE")),
):
    execution = service.create_execution(
        db,
        user=user,
        order_id=order_id,
        rendering_branch_id=payload.rendering_branch_id,
        performed_visit_id=payload.performed_visit_id,
        clinical_notes=payload.clinical_notes,
    )
    return _serialize_execution(db, execution)


@router.post("/executions/{execution_id}/start")
def start_execution(
    execution_id: uuid.UUID,
    row_version: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PROCEDURE_EXECUTE")),
):
    execution = service.start_execution(db, user=user, execution_id=execution_id, row_version=row_version)
    return _serialize_execution(db, execution)


@router.post("/executions/{execution_id}/complete")
def complete_execution(
    execution_id: uuid.UUID,
    payload: ProcedureExecutionCompleteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PROCEDURE_EXECUTE")),
):
    execution = service.complete_execution(db, user=user, execution_id=execution_id, row_version=payload.row_version, clinical_notes=payload.clinical_notes)
    return _serialize_execution(db, execution)
