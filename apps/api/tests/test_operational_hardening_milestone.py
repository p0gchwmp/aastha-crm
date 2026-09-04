import inspect
from app.main import app
from app.models.patient import ImportBatch
from app.seed import ROLE_PERMS
from app.services import legacy_import


def test_operational_hardening_routes_are_exposed():
    paths=app.openapi()["paths"]
    for path in [
        "/api/v1/masters/localities",
        "/api/v1/masters/chief-complaints",
        "/api/v1/masters/pending",
        "/api/v1/masters/localities/{locality_id}/resolve",
        "/api/v1/masters/chief-complaints/{complaint_id}/resolve",
        "/api/v1/imports/patients/upload",
        "/api/v1/imports/patients/{batch_id}/preview",
        "/api/v1/imports/patients/{batch_id}/commit",
        "/api/v1/admin/audit",
        "/api/v1/consultation-finance/bills/{bill_id}/document",
        "/api/v1/consultation-finance/payments/{payment_id}/document",
    ]:
        assert path in paths


def test_master_checker_stays_with_super_reception_and_above():
    assert "MASTER_APPROVE" in ROLE_PERMS["SUPER_RECEPTIONIST"]
    assert "MASTER_APPROVE" not in ROLE_PERMS["RECEPTIONIST"]


def test_legacy_import_is_admin_only_and_scoped():
    assert "PATIENT_IMPORT" not in ROLE_PERMS["RECEPTIONIST"]
    assert "PATIENT_IMPORT" not in ROLE_PERMS["SUPER_RECEPTIONIST"]
    assert "PATIENT_IMPORT" in ROLE_PERMS["ADMIN"]
    assert "organization_id" in ImportBatch.__table__.columns


def test_legacy_import_strips_financial_columns_before_staging():
    assert legacy_import._is_financial_header("Outstanding Balance")
    assert legacy_import._is_financial_header("GST Amount")
    source=inspect.getsource(legacy_import.stage_import)
    assert "if not _is_financial_header(k)" in source


def test_xlsx_and_csv_supported():
    source=inspect.getsource(legacy_import.read_uploaded_rows)
    assert '.endswith(".csv")' in source
    assert '.endswith(".xlsx")' in source
