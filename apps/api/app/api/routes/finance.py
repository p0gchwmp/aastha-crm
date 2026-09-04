import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.access import allowed_branch_ids, ensure_branch_access
from app.core.permissions import require_permission
from app.core.security import current_user
from app.models.clinical import Visit, VisitType
from app.models.core import Branch, Doctor, Organization, Service, User
from app.models.finance import (
    ConsultationBill,
    ConsultationFeeVersion,
    ConsultationPayment,
    ConsultationPolicyVersion,
    FinancialChangeRequest,
    PaymentMode,
)
from app.models.patient import Patient, PatientContact
from app.schemas.finance import (
    BillOut,
    BillVoidRequest,
    ChangeRequestCreate,
    ChangeRequestResolve,
    ComplimentaryCreate,
    ConsultationBillDraftCreate,
    ConsultationBillFromVisitCreate,
    ConsultationDecisionOut,
    ConsultationEligibilityOut,
    ConsultationFeeCreate,
    ConsultationFeeOut,
    ConsultationPaymentCreate,
    DailyFinanceReportOut,
    FinanceSetupOut,
    PaymentModeCorrection,
    PaymentOut,
)
from app.services.audit import log_audit
from app.services.consultation import (
    authorize_complimentary,
    correct_payment_mode,
    create_bill_draft,
    create_bill_from_visit,
    create_free_followup_clearance,
    daily_finance_report,
    finalize_bill,
    get_eligibility,
    record_payment,
    visit_decision,
    void_bill,
)
from app.services.patients import current_fiscal_year

router = APIRouter(prefix="/consultation-finance", tags=["consultation-finance"])


def _get_owned_visit(db: Session, visit_id: uuid.UUID, organization_id: uuid.UUID) -> tuple[Visit, Patient]:
    visit = db.get(Visit, visit_id)
    if not visit:
        raise HTTPException(404, "Visit not found")
    patient = db.get(Patient, visit.patient_id)
    if not patient or patient.organization_id != organization_id:
        raise HTTPException(404, "Visit not found")
    visit_type = db.get(VisitType, visit.visit_type_id)
    if not visit_type or visit_type.code not in {"CONSULTATION", "FOLLOW_UP"}:
        raise HTTPException(409, "Consultation Finance applies only to Consultation/Follow-Up visits")
    return visit, patient


@router.get("/setup", response_model=FinanceSetupOut)
def setup(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    modes = list(db.scalars(select(PaymentMode).where(PaymentMode.active.is_(True)).order_by(PaymentMode.name)).all())
    today = datetime.now().date()
    policy = db.scalar(
        select(ConsultationPolicyVersion)
        .where(
            ConsultationPolicyVersion.active.is_(True),
            ConsultationPolicyVersion.effective_from <= today,
            (ConsultationPolicyVersion.effective_until.is_(None) | (ConsultationPolicyVersion.effective_until >= today)),
        )
        .order_by(ConsultationPolicyVersion.effective_from.desc())
        .limit(1)
    )
    service_ids = list(db.scalars(select(Service.service_id).where(Service.organization_id == user.organization_id)).all())
    fees = [] if not service_ids else list(
        db.scalars(
            select(ConsultationFeeVersion)
            .where(ConsultationFeeVersion.service_id.in_(service_ids))
            .order_by(ConsultationFeeVersion.effective_from.desc())
        ).all()
    )
    return {
        "payment_modes": [{"id": str(x.payment_mode_id), "code": x.code, "name": x.name} for x in modes],
        "active_policy": None if not policy else {
            "id": str(policy.policy_version_id),
            "name": policy.name,
            "free_followup_window_days": policy.free_followup_window_days,
            "max_free_followups": policy.max_free_followups,
            "effective_from": policy.effective_from.isoformat(),
        },
        "fee_versions": [{
            "id": str(x.fee_version_id),
            "service_id": str(x.service_id),
            "doctor_id": str(x.doctor_id) if x.doctor_id else None,
            "branch_id": str(x.branch_id) if x.branch_id else None,
            "amount": str(x.amount),
            "effective_from": x.effective_from.isoformat(),
            "effective_until": x.effective_until.isoformat() if x.effective_until else None,
            "active": x.active,
        } for x in fees],
    }


@router.get("/fees", response_model=list[ConsultationFeeOut])
def list_fees(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    service_ids = list(db.scalars(select(Service.service_id).where(Service.organization_id == user.organization_id)).all())
    if not service_ids:
        return []
    return list(db.scalars(select(ConsultationFeeVersion).where(ConsultationFeeVersion.service_id.in_(service_ids)).order_by(ConsultationFeeVersion.effective_from.desc())).all())


@router.post("/fees", response_model=ConsultationFeeOut)
def create_fee(
    payload: ConsultationFeeCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("FINANCE_CORRECT")),
):
    service = db.get(Service, payload.service_id)
    if not service or service.organization_id != user.organization_id or service.clinical_type != "CONSULTATION":
        raise HTTPException(400, "Consultation service not found")
    if payload.effective_until and payload.effective_until < payload.effective_from:
        raise HTTPException(400, "effective_until cannot be before effective_from")
    if payload.doctor_id:
        doctor = db.get(Doctor, payload.doctor_id)
        if not doctor or doctor.organization_id != user.organization_id:
            raise HTTPException(400, "Doctor not found")
    if payload.branch_id:
        ensure_branch_access(db, user, payload.branch_id)
    prior = list(db.scalars(
        select(ConsultationFeeVersion).where(
            ConsultationFeeVersion.service_id == payload.service_id,
            ConsultationFeeVersion.doctor_id == payload.doctor_id,
            ConsultationFeeVersion.branch_id == payload.branch_id,
            ConsultationFeeVersion.active.is_(True),
        ).with_for_update()
    ).all())
    for old in prior:
        if old.effective_from < payload.effective_from and (old.effective_until is None or old.effective_until >= payload.effective_from):
            old.effective_until = payload.effective_from - timedelta(days=1)
        elif old.effective_from == payload.effective_from:
            old.active = False
    fee = ConsultationFeeVersion(**payload.model_dump(), active=True)
    db.add(fee)
    db.flush()
    log_audit(
        db,
        organization_id=user.organization_id,
        entity_type="CONSULTATION_FEE_VERSION",
        entity_id=fee.fee_version_id,
        action="FEE_VERSION_CREATED",
        actor_user_id=user.user_id,
        after_data={"amount": str(fee.amount), "effective_from": fee.effective_from.isoformat()},
    )
    db.commit(); db.refresh(fee)
    return fee


@router.get("/eligibility/{patient_id}", response_model=ConsultationEligibilityOut)
def eligibility(
    patient_id: uuid.UUID,
    at: datetime | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("CONSULTATION_BILL_CREATE")),
):
    patient = db.get(Patient, patient_id)
    if not patient or patient.organization_id != user.organization_id:
        raise HTTPException(404, "Patient not found")
    status, ent = get_eligibility(db, patient_id=patient_id, at=at)
    db.rollback()
    return ConsultationEligibilityOut(status=status, entitlement_id=ent.entitlement_id if ent else None, valid_until=ent.valid_until if ent else None)


@router.get("/visits/{visit_id}/decision", response_model=ConsultationDecisionOut)
def decision(
    visit_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("CONSULTATION_FINANCE_VIEW")),
):
    visit, patient = _get_owned_visit(db, visit_id, user.organization_id)
    ensure_branch_access(db, user, visit.branch_id)
    result = visit_decision(db, visit=visit, patient=patient, organization_id=user.organization_id)
    db.rollback()
    return result


@router.post("/visits/{visit_id}/free-followup")
def clear_free_followup(
    visit_id: uuid.UUID,
    entitlement_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("CONSULTATION_BILL_CREATE")),
):
    visit, patient = _get_owned_visit(db, visit_id, user.organization_id)
    ensure_branch_access(db, user, visit.branch_id)
    status, ent = get_eligibility(db, patient_id=patient.patient_id, at=visit.checkin_at)
    if status != "FREE_FOLLOWUP_ELIGIBLE" or not ent or ent.entitlement_id != entitlement_id:
        db.rollback()
        raise HTTPException(409, "Free follow-up entitlement is not currently valid")
    try:
        clearance = create_free_followup_clearance(db, visit_id=visit.visit_id, patient_id=patient.patient_id, entitlement_id=entitlement_id)
        db.commit()
    except Exception as exc:
        db.rollback(); raise HTTPException(409, str(exc)) from exc
    return {"clearance_id": clearance.clearance_id, "clearance_type": clearance.clearance_type, "status": clearance.status}


@router.post("/bills/from-visit", response_model=BillOut)
def draft_from_visit(
    payload: ConsultationBillFromVisitCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("CONSULTATION_BILL_CREATE")),
):
    visit, patient = _get_owned_visit(db, payload.visit_id, user.organization_id)
    ensure_branch_access(db, user, visit.branch_id)
    try:
        bill = create_bill_from_visit(db, visit=visit, patient=patient, organization_id=user.organization_id, actor_user_id=user.user_id)
        db.commit(); db.refresh(bill)
    except Exception as exc:
        db.rollback(); raise HTTPException(409, str(exc)) from exc
    return bill


@router.post("/bills", response_model=BillOut)
def draft_bill(
    payload: ConsultationBillDraftCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("CONSULTATION_BILL_CREATE")),
):
    visit, patient = _get_owned_visit(db, payload.visit_id, user.organization_id)
    ensure_branch_access(db, user, visit.branch_id)
    if patient.patient_id != payload.patient_id:
        raise HTTPException(409, "Bill Patient must match Visit Patient")
    if visit.branch_id != payload.branch_id:
        raise HTTPException(409, "Bill Branch must match Visit Branch")
    if not visit.doctor_id or visit.doctor_id != payload.doctor_id:
        raise HTTPException(409, "Bill Doctor must match assigned Visit Doctor")
    try:
        bill = create_bill_draft(db, payload=payload, actor_user_id=user.user_id)
        db.commit(); db.refresh(bill)
    except Exception as exc:
        db.rollback(); raise HTTPException(409, str(exc)) from exc
    return bill


@router.post("/bills/{bill_id}/finalize", response_model=BillOut)
def finalize(
    bill_id: uuid.UUID,
    fiscal_year: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("CONSULTATION_BILL_CREATE")),
):
    bill = db.get(ConsultationBill, bill_id)
    if not bill:
        raise HTTPException(404, "Bill not found")
    patient = db.get(Patient, bill.patient_id)
    if not patient or patient.organization_id != user.organization_id:
        raise HTTPException(404, "Bill not found")
    ensure_branch_access(db, user, bill.branch_id)
    try:
        finalize_bill(db, bill=bill, organization_id=user.organization_id, fiscal_year=fiscal_year or current_fiscal_year(), actor_user_id=user.user_id)
        db.commit(); db.refresh(bill)
    except Exception as exc:
        db.rollback(); raise HTTPException(409, str(exc)) from exc
    return bill


@router.post("/payments", response_model=PaymentOut)
def payment(
    payload: ConsultationPaymentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("CONSULTATION_PAYMENT_CREATE")),
):
    bill = db.get(ConsultationBill, payload.consultation_bill_id)
    patient = db.get(Patient, bill.patient_id) if bill else None
    if not bill or not patient or patient.organization_id != user.organization_id:
        raise HTTPException(404, "Bill not found")
    ensure_branch_access(db, user, bill.branch_id)
    if payload.branch_id != bill.branch_id:
        raise HTTPException(409, "Payment Branch must match Bill Branch")
    try:
        item = record_payment(db, payload=payload, actor_user_id=user.user_id, organization_id=user.organization_id)
        db.commit(); db.refresh(item)
    except Exception as exc:
        db.rollback(); raise HTTPException(409, str(exc)) from exc
    return item


@router.post("/complimentary", dependencies=[Depends(require_permission("CONSULTATION_COMPLIMENTARY"))])
def complimentary(
    payload: ComplimentaryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    visit, patient = _get_owned_visit(db, payload.visit_id, user.organization_id)
    doctor = db.scalar(select(Doctor).where(Doctor.user_id == user.user_id, Doctor.organization_id == user.organization_id))
    if not doctor:
        raise HTTPException(403, "Doctor profile is required for complimentary authorization")
    try:
        auth, clearance = authorize_complimentary(db, visit=visit, patient=patient, doctor=doctor)
        log_audit(
            db,
            organization_id=user.organization_id,
            entity_type="CONSULTATION_VISIT",
            entity_id=visit.visit_id,
            action="COMPLIMENTARY_AUTHORISED",
            actor_user_id=user.user_id,
            after_data={"doctor_id": str(doctor.doctor_id), "clearance_id": str(clearance.clearance_id)},
        )
        db.commit()
    except Exception as exc:
        db.rollback(); raise HTTPException(409, str(exc)) from exc
    return {"authorization_id": auth.authorization_id, "clearance_id": clearance.clearance_id, "status": "CLEARED"}


@router.post("/payments/{payment_id}/correct-mode", response_model=PaymentOut)
def correct_mode(
    payment_id: uuid.UUID,
    payload: PaymentModeCorrection,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("FINANCE_CORRECT")),
):
    item = db.get(ConsultationPayment, payment_id)
    if not item:
        raise HTTPException(404, "Payment not found")
    bill = db.get(ConsultationBill, item.consultation_bill_id)
    patient = db.get(Patient, bill.patient_id) if bill else None
    if not bill or not patient or patient.organization_id != user.organization_id:
        raise HTTPException(404, "Payment not found")
    ensure_branch_access(db, user, bill.branch_id)
    try:
        item = correct_payment_mode(
            db,
            payment=item,
            new_payment_mode_id=payload.payment_mode_id,
            expected_row_version=payload.expected_row_version,
            organization_id=user.organization_id,
            actor_user_id=user.user_id,
            reason=payload.reason,
        )
        db.commit(); db.refresh(item)
    except Exception as exc:
        db.rollback(); raise HTTPException(409, str(exc)) from exc
    return item


@router.post("/bills/{bill_id}/void", response_model=BillOut)
def void(
    bill_id: uuid.UUID,
    payload: BillVoidRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("FINANCE_CORRECT")),
):
    bill = db.get(ConsultationBill, bill_id)
    if not bill:
        raise HTTPException(404, "Bill not found")
    patient = db.get(Patient, bill.patient_id)
    if not patient or patient.organization_id != user.organization_id:
        raise HTTPException(404, "Bill not found")
    ensure_branch_access(db, user, bill.branch_id)
    try:
        bill = void_bill(
            db,
            bill=bill,
            expected_row_version=payload.expected_row_version,
            organization_id=user.organization_id,
            actor_user_id=user.user_id,
            reason=payload.reason,
        )
        db.commit(); db.refresh(bill)
    except Exception as exc:
        db.rollback(); raise HTTPException(409, str(exc)) from exc
    return bill


@router.post("/change-requests")
def request_change(
    payload: ChangeRequestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("CONSULTATION_PAYMENT_CREATE")),
):
    item = FinancialChangeRequest(
        organization_id=user.organization_id,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        requested_change=payload.requested_change,
        requested_by=user.user_id,
        status="PENDING",
    )
    db.add(item); db.commit(); db.refresh(item)
    return {"change_request_id": item.change_request_id, "status": item.status}


@router.post("/change-requests/{request_id}/resolve")
def resolve_change_request(
    request_id: uuid.UUID,
    payload: ChangeRequestResolve,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("FINANCE_CORRECT")),
):
    item = db.scalar(select(FinancialChangeRequest).where(FinancialChangeRequest.change_request_id == request_id, FinancialChangeRequest.organization_id == user.organization_id).with_for_update())
    if not item:
        raise HTTPException(404, "Change request not found")
    if item.status != "PENDING":
        raise HTTPException(409, "Change request already resolved")
    item.status = "APPROVED" if payload.approve else "REJECTED"
    item.resolved_by = user.user_id
    item.resolved_at = datetime.now(timezone.utc)
    log_audit(
        db,
        organization_id=user.organization_id,
        entity_type="FINANCIAL_CHANGE_REQUEST",
        entity_id=item.change_request_id,
        action=item.status,
        actor_user_id=user.user_id,
        before_data={"status": "PENDING"},
        after_data={"status": item.status},
        reason=payload.reason,
    )
    db.commit()
    return {"change_request_id": item.change_request_id, "status": item.status}


@router.get("/reports/daily", response_model=DailyFinanceReportOut)
def daily_report(
    on_date: date | None = None,
    branch_id: uuid.UUID | None = None,
    doctor_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    local_date = on_date or datetime.now(ZoneInfo("Asia/Kolkata")).date()
    allowed = allowed_branch_ids(db, user)
    if branch_id:
        ensure_branch_access(db, user, branch_id)
    elif allowed is not None:
        if len(allowed) == 1:
            branch_id = next(iter(allowed))
        else:
            raise HTTPException(400, "Select an authorized branch for this report")
    return daily_finance_report(db, on_date=local_date, organization_id=user.organization_id, branch_id=branch_id, doctor_id=doctor_id)


@router.get("/bills/{bill_id}/document")
def bill_document(
    bill_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("CONSULTATION_FINANCE_VIEW")),
):
    bill = db.get(ConsultationBill, bill_id)
    patient = db.get(Patient, bill.patient_id) if bill else None
    if not bill or not patient or patient.organization_id != user.organization_id:
        raise HTTPException(404, "Bill not found")
    ensure_branch_access(db, user, bill.branch_id)
    branch = db.get(Branch, bill.branch_id)
    doctor = db.get(Doctor, bill.doctor_id)
    org = db.get(Organization, user.organization_id)
    mobile = db.scalar(select(PatientContact.contact_value).where(PatientContact.patient_id==patient.patient_id, PatientContact.contact_type=="MOBILE").order_by(PatientContact.is_primary.desc()).limit(1))
    payments = list(db.scalars(select(ConsultationPayment).where(ConsultationPayment.consultation_bill_id==bill.consultation_bill_id, ConsultationPayment.payment_status=="COMPLETED").order_by(ConsultationPayment.received_at)).all())
    modes = {m.payment_mode_id:m.name for m in db.scalars(select(PaymentMode)).all()}
    paid = sum((p.amount for p in payments), start=__import__("decimal").Decimal("0"))
    return {
        "document_type":"CONSULTATION_BILL","organization":org.organization_name if org else "Aastha",
        "bill_id":bill.consultation_bill_id,"bill_number":bill.bill_number,"bill_status":bill.bill_status,"bill_date":bill.finalized_at or bill.created_at,
        "patient":{"patient_id":patient.patient_id,"uhid":patient.uhid,"name":patient.full_name,"gender":patient.gender,"mobile":mobile},
        "branch":{"id":bill.branch_id,"name":branch.branch_name if branch else None,"address":branch.address if branch else None,"phone":branch.phone if branch else None},
        "doctor":{"id":bill.doctor_id,"name":doctor.doctor_name if doctor else None},
        "amounts":{"gross":str(bill.gross_amount),"discount":str(bill.discount_amount),"net":str(bill.net_amount),"paid":str(paid),"balance":str(bill.net_amount-paid)},
        "payments":[{"payment_id":p.payment_id,"amount":str(p.amount),"mode":modes.get(p.payment_mode_id),"received_at":p.received_at} for p in payments],
    }


@router.get("/payments/{payment_id}/document")
def receipt_document(
    payment_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("CONSULTATION_FINANCE_VIEW")),
):
    payment = db.get(ConsultationPayment, payment_id)
    bill = db.get(ConsultationBill, payment.consultation_bill_id) if payment else None
    patient = db.get(Patient, bill.patient_id) if bill else None
    if not payment or not bill or not patient or patient.organization_id != user.organization_id:
        raise HTTPException(404, "Receipt not found")
    ensure_branch_access(db, user, payment.branch_id)
    branch = db.get(Branch, payment.branch_id); doctor=db.get(Doctor,bill.doctor_id); org=db.get(Organization,user.organization_id); mode=db.get(PaymentMode,payment.payment_mode_id)
    mobile = db.scalar(select(PatientContact.contact_value).where(PatientContact.patient_id==patient.patient_id, PatientContact.contact_type=="MOBILE").order_by(PatientContact.is_primary.desc()).limit(1))
    total_paid = db.scalar(select(func.coalesce(func.sum(ConsultationPayment.amount),0)).where(ConsultationPayment.consultation_bill_id==bill.consultation_bill_id,ConsultationPayment.payment_status=="COMPLETED"))
    return {
        "document_type":"CONSULTATION_RECEIPT","organization":org.organization_name if org else "Aastha",
        "receipt_id":payment.payment_id,"payment_date":payment.received_at,"bill_number":bill.bill_number,
        "patient":{"patient_id":patient.patient_id,"uhid":patient.uhid,"name":patient.full_name,"mobile":mobile},
        "branch":{"id":payment.branch_id,"name":branch.branch_name if branch else None,"address":branch.address if branch else None,"phone":branch.phone if branch else None},
        "doctor":{"id":bill.doctor_id,"name":doctor.doctor_name if doctor else None},
        "payment":{"amount":str(payment.amount),"mode":mode.name if mode else None,"status":payment.payment_status},
        "bill":{"net":str(bill.net_amount),"total_paid":str(total_paid),"balance":str(bill.net_amount-total_paid)},
    }
