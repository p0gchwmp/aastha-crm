"""Idempotent reference-data bootstrap. Production passwords must come from environment variables."""
import os
from datetime import date
from sqlalchemy import select
from app.core.db import get_session_factory
from app.core.security import hash_password
from app.models.core import (
    Branch,
    NumberSeries,
    Organization,
    Permission,
    Role,
    RolePermission,
    Service,
    ServiceCategory,
    User,
    UserRole,
    Doctor,
)
from app.models.crm import LeadSource, LeadStatus, LostReason
from app.models.clinical import ChiefComplaint, VisitStatus, VisitType, ProcedureOrderStatus, ProcedureExecutionStatus
from app.models.finance import ConsultationPolicyVersion, PaymentMode
from app.models.scheduling import AppointmentStatus, DoctorSchedule
from app.models.patient import District, Locality, Region
from app.models.integration import IntegrationClient
from app.services.integration_auth import hash_integration_key
from app.core.config import get_settings

PERMISSIONS = [
    "LEAD_CREATE", "LEAD_VIEW", "LEAD_EDIT", "LEAD_EXTERNAL_ASSIGN", "LEAD_EXPORT",
    "PATIENT_CREATE", "PATIENT_VIEW", "PATIENT_EDIT", "PATIENT_IMPORT",
    "APPOINTMENT_CREATE", "APPOINTMENT_EDIT", "APPOINTMENT_SCHEDULE_MANAGE",
    "VISIT_CREATE", "VISIT_EDIT", "PROCEDURE_VIEW", "PROCEDURE_ORDER_CREATE", "PROCEDURE_EXECUTE",
    "CONSULTATION_FINANCE_VIEW", "CONSULTATION_BILL_CREATE", "CONSULTATION_PAYMENT_CREATE", "CONSULTATION_COMPLIMENTARY", "FINANCE_CORRECT",
    "MASTER_APPROVE", "REPORT_EXPORT", "AUDIT_VIEW", "STAFF_MANAGE",
]

ROLE_PERMS = {
    "RECEPTIONIST": {
        "LEAD_CREATE", "LEAD_VIEW", "LEAD_EDIT", "PATIENT_CREATE", "PATIENT_VIEW", "PATIENT_EDIT",
        "APPOINTMENT_CREATE", "APPOINTMENT_EDIT", "VISIT_CREATE", "VISIT_EDIT", "PROCEDURE_VIEW",
        "CONSULTATION_FINANCE_VIEW", "CONSULTATION_BILL_CREATE", "CONSULTATION_PAYMENT_CREATE",
    },
    "SUPER_RECEPTIONIST": {
        "LEAD_CREATE", "LEAD_VIEW", "LEAD_EDIT", "PATIENT_CREATE", "PATIENT_VIEW", "PATIENT_EDIT",
        "APPOINTMENT_CREATE", "APPOINTMENT_EDIT", "VISIT_CREATE", "VISIT_EDIT", "PROCEDURE_VIEW",
        "CONSULTATION_FINANCE_VIEW", "CONSULTATION_BILL_CREATE", "CONSULTATION_PAYMENT_CREATE", "MASTER_APPROVE",
    },
    "ADMIN": set(PERMISSIONS) - {"CONSULTATION_COMPLIMENTARY"},
    "SUPER_ADMIN": set(PERMISSIONS),
    "DOCTOR": {"PATIENT_VIEW", "VISIT_EDIT", "PROCEDURE_VIEW", "PROCEDURE_ORDER_CREATE", "PROCEDURE_EXECUTE", "CONSULTATION_FINANCE_VIEW", "CONSULTATION_COMPLIMENTARY"},
}


def get_or_create(db, model, defaults=None, **where):
    item = db.scalar(select(model).filter_by(**where))
    if item:
        return item
    item = model(**where, **(defaults or {}))
    db.add(item)
    db.flush()
    return item



def _bootstrap_password(env_name: str, dev_default: str) -> str:
    settings = get_settings()
    value = os.getenv(env_name)
    if value:
        if len(value) < 12 or "replace" in value.lower() or "change-me" in value.lower():
            raise RuntimeError(f"{env_name} must be a non-placeholder password of at least 12 characters")
        return value
    if settings.is_production:
        raise RuntimeError(f"{env_name} is required for first-time production bootstrap")
    return dev_default


def main():
    db = get_session_factory()()
    try:
        org = get_or_create(db, Organization, organization_code="AASTHA", defaults={"organization_name": "Aastha Skin & Dermato-Cosmetic Centre"})
        pal = get_or_create(db, Branch, organization_id=org.organization_id, branch_code="PAL", defaults={"branch_name": "Paloura"})
        amp = get_or_create(db, Branch, organization_id=org.organization_id, branch_code="AMP", defaults={"branch_name": "Amphalla / Karan Nagar"})

        perms = {code: get_or_create(db, Permission, code=code, defaults={"name": code.replace("_", " ").title()}) for code in PERMISSIONS}
        roles = {code: get_or_create(db, Role, code=code, defaults={"name": code.replace("_", " ").title()}) for code in ROLE_PERMS}
        for role_code, permission_codes in ROLE_PERMS.items():
            for p in permission_codes:
                get_or_create(db, RolePermission, role_id=roles[role_code].role_id, permission_id=perms[p].permission_id)

        admin = db.scalar(select(User).where(User.username == "admin"))
        if not admin:
            admin = User(
                organization_id=org.organization_id,
                name="Aastha Super Admin",
                username="admin",
                password_hash=hash_password(_bootstrap_password("BOOTSTRAP_SUPER_ADMIN_PASSWORD", "ChangeMe123!")),
                status="ACTIVE",
            )
            db.add(admin); db.flush()
            db.add(UserRole(user_id=admin.user_id, role_id=roles["SUPER_ADMIN"].role_id))

        reception = db.scalar(select(User).where(User.username == "reception"))
        if not reception:
            reception = User(
                organization_id=org.organization_id,
                name="Aastha Reception",
                username="reception",
                password_hash=hash_password(_bootstrap_password("BOOTSTRAP_RECEPTION_PASSWORD", "Reception123!")),
                status="ACTIVE",
            )
            db.add(reception); db.flush()
            db.add(UserRole(user_id=reception.user_id, role_id=roles["RECEPTIONIST"].role_id, branch_id=pal.branch_id))

        super_reception = db.scalar(select(User).where(User.username == "superreception"))
        if not super_reception:
            super_reception = User(
                organization_id=org.organization_id,
                name="Aastha Super Reception",
                username="superreception",
                password_hash=hash_password(_bootstrap_password("BOOTSTRAP_SUPER_RECEPTION_PASSWORD", "SuperReception123!")),
                status="ACTIVE",
            )
            db.add(super_reception); db.flush()
            db.add(UserRole(user_id=super_reception.user_id, role_id=roles["SUPER_RECEPTIONIST"].role_id, branch_id=pal.branch_id))

        clinic_admin = db.scalar(select(User).where(User.username == "clinicadmin"))
        if not clinic_admin:
            clinic_admin = User(
                organization_id=org.organization_id,
                name="Aastha Admin",
                username="clinicadmin",
                password_hash=hash_password(_bootstrap_password("BOOTSTRAP_ADMIN_PASSWORD", "ClinicAdmin123!")),
                status="ACTIVE",
            )
            db.add(clinic_admin); db.flush()
            db.add(UserRole(user_id=clinic_admin.user_id, role_id=roles["ADMIN"].role_id))

        doctor_user = db.scalar(select(User).where(User.username == "doctor"))
        if not doctor_user:
            doctor_user = User(
                organization_id=org.organization_id,
                name="Dr. Cheena Langer",
                username="doctor",
                password_hash=hash_password(_bootstrap_password("BOOTSTRAP_DOCTOR_PASSWORD", "Doctor123!")),
                status="ACTIVE",
            )
            db.add(doctor_user); db.flush()
            db.add(UserRole(user_id=doctor_user.user_id, role_id=roles["DOCTOR"].role_id))
        doctor = get_or_create(
            db, Doctor,
            organization_id=org.organization_id,
            doctor_code="DCL",
            defaults={"doctor_name": "Dr. Cheena Langer", "speciality": "Dermatology", "user_id": doctor_user.user_id},
        )

        for code, name in [
            ("INSTAGRAM", "Instagram"), ("FACEBOOK", "Facebook"), ("GOOGLE", "Google"),
            ("WHATSAPP", "WhatsApp"), ("PHONE", "Phone"), ("WALKIN", "Walk-in"),
            ("REFERRAL", "Referral"), ("AI_VOICE", "AI Voice"), ("WHATSAPP_AI", "WhatsApp AI"),
            ("WEBSITE", "Website"), ("THIRD_PARTY", "Third Party"),
        ]:
            get_or_create(db, LeadSource, code=code, defaults={"name": name})

        for code in ["NEW", "FOLLOW_UP_REQUIRED", "APPOINTMENT_BOOKED", "CONVERTED", "LOST", "NO_SHOW", "SPAM_FAKE", "DO_NOT_CALL"]:
            get_or_create(db, LeadStatus, code=code, defaults={"name": code.replace("_", " ").title(), "terminal": code in {"CONVERTED", "LOST", "SPAM_FAKE"}})
        for code in ["PRICE", "NOT_INTERESTED", "NO_RESPONSE", "OUT_OF_TOWN", "WENT_ELSEWHERE", "POSTPONED", "OTHER"]:
            get_or_create(db, LostReason, code=code, defaults={"name": code.replace("_", " ").title()})
        for code in ["SCHEDULED", "CONFIRMED", "WAITLISTED", "CHECKED_IN", "RESCHEDULED", "CANCELLED", "NO_SHOW", "COMPLETED"]:
            get_or_create(db, AppointmentStatus, code=code, defaults={"name": code.replace("_", " ").title()})
        # Doctor availability is configured by Admin; never recreate or invent clinic timings.
        for code in ["CONSULTATION", "PROCEDURE", "REPORT_CHECK", "FOLLOW_UP", "OTHER"]:
            get_or_create(db, VisitType, code=code, defaults={"name": code.replace("_", " ").title()})
        for complaint in ["Acne", "Acne Scars", "Hair Fall", "Pigmentation", "Melasma", "Fungal Infection", "Eczema", "Psoriasis", "Vitiligo", "Warts"]:
            get_or_create(db, ChiefComplaint, name=complaint, defaults={"approval_status": "APPROVED", "active": True})

        jammu_region = get_or_create(db, Region, name="Jammu", defaults={"status": "ACTIVE"})
        outside_region = get_or_create(db, Region, name="Outside", defaults={"status": "ACTIVE"})
        jammu_district = get_or_create(db, District, region_id=jammu_region.region_id, name="Jammu", defaults={"status": "ACTIVE"})
        for locality_name in ["Paloura", "Karan Nagar", "Amphalla", "Janipur", "Talab Tillo", "Bakshi Nagar", "Rehari", "Gandhi Nagar", "Trikuta Nagar", "Roop Nagar", "Bantalab", "Sidhra"]:
            get_or_create(db, Locality, district_id=jammu_district.district_id, locality_name=locality_name, defaults={"approval_status": "APPROVED"})
        for code in ["CREATED", "WAITING", "IN_PROGRESS", "COMPLETED", "CANCELLED", "ABANDONED"]:
            get_or_create(db, VisitStatus, code=code, defaults={"name": code.replace("_", " ").title()})
        for code in ["ORDERED", "FINANCIAL_HOLD", "READY", "PARTIALLY_COMPLETED", "COMPLETED", "CANCELLED"]:
            get_or_create(db, ProcedureOrderStatus, code=code, defaults={"name": code.replace("_", " ").title()})
        for code in ["PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]:
            get_or_create(db, ProcedureExecutionStatus, code=code, defaults={"name": code.replace("_", " ").title()})
        for code in ["CASH", "UPI", "CARD", "OTHER"]:
            get_or_create(db, PaymentMode, code=code, defaults={"name": code.title()})

        consult_cat = get_or_create(db, ServiceCategory, code="CONSULTATION", defaults={"name": "Consultation"})
        get_or_create(db, Service, organization_id=org.organization_id, service_code="CONSULT", defaults={"service_name": "General Consultation", "service_category_id": consult_cat.service_category_id, "clinical_type": "CONSULTATION"})
        get_or_create(db, ConsultationPolicyVersion, name="Standard 10-day follow-up", effective_from=date(2026, 1, 1), defaults={"free_followup_window_days": 10, "max_free_followups": 1})

        hair_cat = get_or_create(db, ServiceCategory, code="HAIR", defaults={"name": "Hair"})
        acne_cat = get_or_create(db, ServiceCategory, code="ACNE_SCAR", defaults={"name": "Acne / Scar"})
        for service_code, service_name, category, clinical_type in [
            ("GFC", "GFC Hair Treatment", hair_cat, "PROCEDURE"),
            ("PRP", "PRP Hair Treatment", hair_cat, "PROCEDURE"),
            ("MNRF", "Microneedling RF", acne_cat, "PROCEDURE"),
        ]:
            get_or_create(
                db, Service, organization_id=org.organization_id, service_code=service_code,
                defaults={"service_name": service_name, "service_category_id": category.service_category_id, "clinical_type": clinical_type},
            )

        if not get_settings().is_production:
            get_or_create(
                db, IntegrationClient, organization_id=org.organization_id, client_name="Procedure Finance DEV",
                defaults={
                    "client_type": "PROCEDURE_FINANCE", "status": "ACTIVE",
                    "allowed_scopes": {"scopes": ["procedure_order.read", "procedure_financial_status.write", "procedure_order_event.read", "procedure_order_event.ack"]},
                    "credential_hash": hash_integration_key("dev-procedure-finance-key"),
                },
            )
            get_or_create(
                db, IntegrationClient, organization_id=org.organization_id, client_name="Inventory DEV",
                defaults={
                    "client_type": "INVENTORY", "status": "ACTIVE",
                    "allowed_scopes": {"scopes": ["inventory_event.read", "inventory_event.ack"]},
                    "credential_hash": hash_integration_key("dev-inventory-key"),
                },
            )

        for code, branch in [("UHID", None), ("CONSULTATION_BILL", pal), ("CONSULTATION_BILL", amp)]:
            template = "AAS-{NUMBER}" if code == "UHID" else "AAS/{BRANCH}/{FY}/{NUMBER}"
            get_or_create(
                db, NumberSeries,
                organization_id=org.organization_id,
                branch_id=branch.branch_id if branch else None,
                series_code=code,
                fiscal_year="2026-27",
                defaults={"prefix_template": template, "current_number": 0},
            )

        db.commit()
        if get_settings().is_production:
            print("Production bootstrap complete. User passwords were supplied through environment variables and are not printed.")
        else:
            print("Seed complete. Dev logins: reception / Reception123!, superreception / SuperReception123!, clinicadmin / ClinicAdmin123!, admin / ChangeMe123!, doctor / Doctor123! (change immediately)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
