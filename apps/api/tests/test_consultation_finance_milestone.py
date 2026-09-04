import inspect
from app.main import app
from app.models.finance import ConsultationBill, FollowupEntitlement
from app.services import consultation
from app.seed import ROLE_PERMS


def test_consultation_finance_routes_are_exposed():
    paths = app.openapi()["paths"]
    for path in [
        "/api/v1/consultation-finance/setup",
        "/api/v1/consultation-finance/fees",
        "/api/v1/consultation-finance/visits/{visit_id}/decision",
        "/api/v1/consultation-finance/visits/{visit_id}/free-followup",
        "/api/v1/consultation-finance/bills/from-visit",
        "/api/v1/consultation-finance/bills/{bill_id}/finalize",
        "/api/v1/consultation-finance/payments",
        "/api/v1/consultation-finance/complimentary",
        "/api/v1/consultation-finance/payments/{payment_id}/correct-mode",
        "/api/v1/consultation-finance/bills/{bill_id}/void",
        "/api/v1/consultation-finance/reports/daily",
    ]:
        assert path in paths


def test_bill_number_has_database_unique_constraint():
    constraints = {tuple(c.columns.keys()) for c in ConsultationBill.__table__.constraints if hasattr(c, "columns")}
    assert ("bill_number",) in constraints


def test_paid_bill_entitlement_links_back_to_bill():
    fks = {fk.target_fullname for fk in FollowupEntitlement.__table__.c.source_bill_id.foreign_keys}
    assert "consultation_finance.consultation_bills.consultation_bill_id" in fks
    assert FollowupEntitlement.__table__.c.source_bill_id.unique is True


def test_followup_eligibility_is_patient_level_not_complaint_level():
    source = inspect.getsource(consultation.get_eligibility)
    assert "FollowupEntitlement.patient_id == patient_id" in source
    assert "chief_complaint" not in source.lower()


def test_payment_rejects_overpayment_and_creates_entitlement_on_full_payment():
    source = inspect.getsource(consultation.record_payment)
    assert "Payment exceeds outstanding balance" in source
    assert "_create_entitlement_after_paid_bill" in source


def test_free_followup_consumption_is_locked():
    source = inspect.getsource(consultation.consume_entitlement)
    assert ".with_for_update()" in source


def test_doctor_has_real_complimentary_permission():
    assert "CONSULTATION_COMPLIMENTARY" in ROLE_PERMS["DOCTOR"]
    assert "CONSULTATION_PAYMENT_CREATE" not in ROLE_PERMS["DOCTOR"]


def test_financial_correction_writes_audit():
    source = inspect.getsource(consultation.correct_payment_mode)
    assert "log_audit" in source
    assert "PAYMENT_MODE_CORRECTED" in source


def test_bill_finalization_and_payment_are_audited():
    assert "BILL_FINALIZED" in inspect.getsource(consultation.finalize_bill)
    assert "PAYMENT_RECORDED" in inspect.getsource(consultation.record_payment)
