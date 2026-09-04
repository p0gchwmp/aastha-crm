from app.models.clinical import ProcedureExecution, ProcedureOrder
from app.models.finance import ConsultationBill, ConsultationPayment, EntitlementUsage, FollowupEntitlement
from app.models.patient import Patient, PatientContact


def test_procedure_order_and_execution_are_separate_entities():
    assert ProcedureOrder.__tablename__ != ProcedureExecution.__tablename__


def test_bill_and_payment_are_separate_entities():
    assert ConsultationBill.__tablename__ != ConsultationPayment.__tablename__


def test_entitlement_usage_is_separate_for_future_multiple_uses():
    assert FollowupEntitlement.__tablename__ != EntitlementUsage.__tablename__


def test_mobile_lives_in_contact_table_not_patient_identity():
    assert "mobile" not in Patient.__table__.columns
    assert "normalized_value" in PatientContact.__table__.columns
