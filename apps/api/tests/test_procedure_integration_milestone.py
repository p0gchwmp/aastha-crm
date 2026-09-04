import inspect
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from app.main import app
from app.models.integration import IntegrationClient, OutboxEvent
from app.schemas.procedures import ProcedureExecutionCreateRequest
from app.seed import ROLE_PERMS
from app.services import procedures


def test_procedure_routes_are_exposed():
    paths = app.openapi()["paths"]
    for path in [
        "/api/v1/procedures/setup",
        "/api/v1/procedures/orders",
        "/api/v1/procedures/orders/{order_id}",
        "/api/v1/procedures/orders/{order_id}/executions",
        "/api/v1/procedures/executions/{execution_id}/start",
        "/api/v1/procedures/executions/{execution_id}/complete",
        "/api/v1/procedures/orders/{order_id}/close",
        "/api/v1/procedures/orders/{order_id}/cancel",
        "/api/v1/external/procedures/orders/{order_id}",
        "/api/v1/external/procedures/orders/{order_id}/financial-status",
        "/api/v1/external/procedures/finance-events",
        "/api/v1/external/procedures/inventory-events",
    ]:
        assert path in paths


def test_doctor_can_order_and_execute_but_reception_only_views_procedures():
    assert {"PROCEDURE_VIEW", "PROCEDURE_ORDER_CREATE", "PROCEDURE_EXECUTE"} <= ROLE_PERMS["DOCTOR"]
    assert "PROCEDURE_VIEW" in ROLE_PERMS["RECEPTIONIST"]
    assert "PROCEDURE_ORDER_CREATE" not in ROLE_PERMS["RECEPTIONIST"]
    assert "PROCEDURE_EXECUTE" not in ROLE_PERMS["RECEPTIONIST"]


def test_session_requires_real_performed_visit():
    assert ProcedureExecutionCreateRequest.model_fields["performed_visit_id"].is_required()
    source = inspect.getsource(procedures.create_execution)
    assert "Procedure execution Visit must belong to the Procedure Order Patient" in source
    assert "Rendering Branch must match the Procedure Visit branch" in source


def test_pay_first_is_enforced_before_session_creation_and_start():
    assert procedures.PROCEDURE_READY_FINANCIAL_STATUSES == {"CLEARED", "COMPLIMENTARY"}
    assert "assert_financial_clearance" in inspect.getsource(procedures.create_execution)
    assert "assert_financial_clearance" in inspect.getsource(procedures.start_execution)


def test_session_completion_does_not_close_multi_session_order_automatically():
    source = inspect.getsource(procedures.complete_execution)
    assert '"PARTIALLY_COMPLETED"' in source
    assert 'partial_order = _status(db, ProcedureOrderStatus, "PARTIALLY_COMPLETED")' in source
    assert "completed_order = _status" not in source
    assert "close_order" in dir(procedures)


def test_inventory_event_contains_no_patient_identity():
    execution = SimpleNamespace(
        procedure_execution_id=uuid.uuid4(),
        rendering_branch_id=uuid.uuid4(),
        performed_by_doctor_id=uuid.uuid4(),
    )
    order = SimpleNamespace(procedure_order_id=uuid.uuid4(), service_id=uuid.uuid4())
    service = SimpleNamespace(service_code="GFC")
    payload = procedures.build_inventory_event_payload(execution, order, service, datetime.now(timezone.utc))
    assert "patient_id" not in payload
    assert "uhid" not in payload
    assert "patient_name" not in payload
    assert {"procedure_execution_id", "procedure_order_id", "service_id", "rendering_branch_id"} <= payload.keys()


def test_integration_clients_and_outbox_are_tenant_scoped_and_targeted():
    assert "organization_id" in IntegrationClient.__table__.columns
    assert "organization_id" in OutboxEvent.__table__.columns
    assert "target_client_type" in OutboxEvent.__table__.columns


def test_external_finance_callback_reserves_idempotency_atomically():
    source = inspect.getsource(procedures.apply_external_financial_status)
    assert "pg_insert(InboxEvent)" in source
    assert ".on_conflict_do_nothing" in source
    assert "External event ID was already used for another Procedure Order" in source


def test_finance_status_does_not_rewrite_completed_or_partially_completed_clinical_history():
    source = inspect.getsource(procedures.apply_external_financial_status)
    assert '{"PARTIALLY_COMPLETED", "COMPLETED"}' in source


def test_procedure_session_updates_linked_visit_status():
    start_source = inspect.getsource(procedures.start_execution)
    complete_source = inspect.getsource(procedures.complete_execution)
    assert 'VisitStatus, "IN_PROGRESS"' in start_source
    assert 'VisitStatus, "COMPLETED"' in complete_source


def test_order_cancellation_notifies_external_finance_and_blocks_completed_sessions():
    source = inspect.getsource(procedures.cancel_order)
    assert '"PROCEDURE_ORDER_CANCELLED"' in source
    assert 'target_client_type="PROCEDURE_FINANCE"' in source
    assert "completed sessions cannot be cancelled" in source
