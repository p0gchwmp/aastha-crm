import inspect
from app.main import app
from app.models.crm import LeadPatientLink
from app.schemas.clinical import VisitCreate
from app.services.patients import calculate_age, convert_lead_to_patient, current_fiscal_year
from datetime import date


def test_patient_conversion_and_visit_routes_are_exposed():
    paths = app.openapi()["paths"]
    for path in [
        "/api/v1/leads/{lead_id}/conversion-preview",
        "/api/v1/leads/{lead_id}/convert",
        "/api/v1/patients/search",
        "/api/v1/patients/match",
        "/api/v1/patients/{patient_id}",
        "/api/v1/patients/{patient_id}/visits",
        "/api/v1/visits",
    ]:
        assert path in paths


def test_lead_patient_link_has_real_patient_fk():
    fks = {fk.target_fullname for fk in LeadPatientLink.__table__.c.patient_id.foreign_keys}
    assert "patient.patients.patient_id" in fks


def test_conversion_serializes_on_lead_row_lock():
    source = inspect.getsource(convert_lead_to_patient)
    assert ".with_for_update()" in source
    assert "LeadPatientLink" in source


def test_visit_creation_requires_explicit_identity_confirmation():
    assert VisitCreate.model_fields["identity_confirmed"].default is False


def test_age_and_fiscal_year_helpers_are_deterministic():
    assert calculate_age(date(2000, 9, 4), date(2026, 9, 3)) == 25
    assert calculate_age(date(2000, 9, 3), date(2026, 9, 3)) == 26
    assert current_fiscal_year(date(2026, 9, 3)) == "2026-27"
    assert current_fiscal_year(date(2027, 2, 1)) == "2026-27"
