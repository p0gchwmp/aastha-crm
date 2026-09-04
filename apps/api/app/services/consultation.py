import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session
from app.models.clinical import Visit, VisitType
from app.models.core import Branch, Doctor, Service
from app.models.finance import (
    ComplimentaryAuthorization,
    ConsultationBill,
    ConsultationClearance,
    ConsultationFeeVersion,
    ConsultationPayment,
    ConsultationPolicyVersion,
    EntitlementUsage,
    FollowupEntitlement,
    PaymentMode,
)
from app.models.patient import Patient
from app.services.audit import log_audit
from app.services.number_series import allocate_number

IST = ZoneInfo("Asia/Kolkata")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _active_policy(db: Session, *, on_date: date) -> ConsultationPolicyVersion | None:
    return db.scalar(
        select(ConsultationPolicyVersion)
        .where(
            ConsultationPolicyVersion.active.is_(True),
            ConsultationPolicyVersion.effective_from <= on_date,
            (ConsultationPolicyVersion.effective_until.is_(None) | (ConsultationPolicyVersion.effective_until >= on_date)),
        )
        .order_by(ConsultationPolicyVersion.effective_from.desc())
        .limit(1)
    )


def _consult_service(db: Session, organization_id: uuid.UUID) -> Service | None:
    return db.scalar(
        select(Service)
        .where(
            Service.organization_id == organization_id,
            Service.active.is_(True),
            Service.clinical_type == "CONSULTATION",
        )
        .order_by(Service.created_at.asc())
        .limit(1)
    )


def resolve_fee_version(
    db: Session,
    *,
    organization_id: uuid.UUID,
    doctor_id: uuid.UUID | None,
    branch_id: uuid.UUID,
    on_date: date,
) -> ConsultationFeeVersion | None:
    service = _consult_service(db, organization_id)
    if not service:
        return None
    doctor_specificity = case((ConsultationFeeVersion.doctor_id == doctor_id, 1), else_=0)
    branch_specificity = case((ConsultationFeeVersion.branch_id == branch_id, 1), else_=0)
    return db.scalar(
        select(ConsultationFeeVersion)
        .where(
            ConsultationFeeVersion.service_id == service.service_id,
            ConsultationFeeVersion.active.is_(True),
            ConsultationFeeVersion.effective_from <= on_date,
            (ConsultationFeeVersion.effective_until.is_(None) | (ConsultationFeeVersion.effective_until >= on_date)),
            (ConsultationFeeVersion.doctor_id.is_(None) | (ConsultationFeeVersion.doctor_id == doctor_id)),
            (ConsultationFeeVersion.branch_id.is_(None) | (ConsultationFeeVersion.branch_id == branch_id)),
        )
        .order_by((doctor_specificity + branch_specificity).desc(), ConsultationFeeVersion.effective_from.desc())
        .limit(1)
    )


def get_eligibility(db: Session, *, patient_id: uuid.UUID, at: datetime | None = None):
    at = at or _utc_now()
    entitlements = list(
        db.scalars(
            select(FollowupEntitlement)
            .where(
                FollowupEntitlement.patient_id == patient_id,
                FollowupEntitlement.status == "ACTIVE",
                FollowupEntitlement.valid_from <= at,
                FollowupEntitlement.valid_until >= at,
            )
            .order_by(FollowupEntitlement.valid_from.desc())
            .with_for_update()
        ).all()
    )
    for ent in entitlements:
        used = db.scalar(
            select(func.count(EntitlementUsage.usage_id)).where(EntitlementUsage.entitlement_id == ent.entitlement_id)
        ) or 0
        if used < ent.max_uses:
            return "FREE_FOLLOWUP_ELIGIBLE", ent
    return "PAID_CONSULTATION_REQUIRED", None


def consume_entitlement(db: Session, *, entitlement_id: uuid.UUID, visit_id: uuid.UUID, at: datetime | None = None) -> EntitlementUsage:
    at = at or _utc_now()
    ent = db.scalar(
        select(FollowupEntitlement)
        .where(FollowupEntitlement.entitlement_id == entitlement_id)
        .with_for_update()
    )
    if not ent:
        raise ValueError("Entitlement not found")
    used = db.scalar(select(func.count(EntitlementUsage.usage_id)).where(EntitlementUsage.entitlement_id == ent.entitlement_id)) or 0
    if ent.status != "ACTIVE" or ent.valid_from > at or ent.valid_until < at or used >= ent.max_uses:
        raise ValueError("Entitlement is not available")
    prior_for_visit = db.scalar(select(EntitlementUsage).where(EntitlementUsage.visit_id == visit_id))
    if prior_for_visit:
        return prior_for_visit
    usage = EntitlementUsage(entitlement_id=entitlement_id, visit_id=visit_id, used_at=at)
    db.add(usage)
    db.flush()
    return usage


def create_free_followup_clearance(
    db: Session,
    *,
    visit_id: uuid.UUID,
    patient_id: uuid.UUID,
    entitlement_id: uuid.UUID,
) -> ConsultationClearance:
    existing = db.scalar(select(ConsultationClearance).where(ConsultationClearance.visit_id == visit_id).with_for_update())
    if existing:
        return existing
    usage = consume_entitlement(db, entitlement_id=entitlement_id, visit_id=visit_id)
    clearance = ConsultationClearance(
        visit_id=visit_id,
        patient_id=patient_id,
        clearance_type="FREE_FOLLOWUP",
        status="CLEARED",
        entitlement_usage_id=usage.usage_id,
        cleared_at=_utc_now(),
    )
    db.add(clearance)
    db.flush()
    return clearance


def create_bill_draft(db: Session, *, payload, actor_user_id: uuid.UUID) -> ConsultationBill:
    existing = db.scalar(select(ConsultationBill).where(ConsultationBill.visit_id == payload.visit_id).with_for_update())
    if existing:
        return existing
    fee = db.get(ConsultationFeeVersion, payload.fee_version_id)
    if not fee or not fee.active:
        raise ValueError("Consultation fee version unavailable")
    bill = ConsultationBill(
        patient_id=payload.patient_id,
        visit_id=payload.visit_id,
        doctor_id=payload.doctor_id,
        branch_id=payload.branch_id,
        fee_version_id=payload.fee_version_id,
        gross_amount=fee.amount,
        discount_amount=Decimal("0.00"),
        net_amount=fee.amount,
        bill_status="DRAFT",
        created_by=actor_user_id,
    )
    db.add(bill)
    db.flush()
    return bill


def create_bill_from_visit(
    db: Session,
    *,
    visit: Visit,
    patient: Patient,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> ConsultationBill:
    existing_clearance = db.scalar(select(ConsultationClearance).where(ConsultationClearance.visit_id == visit.visit_id))
    if existing_clearance:
        raise ValueError(f"Visit is already cleared as {existing_clearance.clearance_type}")
    eligibility, _ = get_eligibility(db, patient_id=patient.patient_id, at=visit.checkin_at)
    if eligibility == "FREE_FOLLOWUP_ELIGIBLE":
        raise ValueError("Patient has an available free follow-up. Use the Free Follow-Up action or explicitly create a new qualifying Visit later.")
    if not visit.doctor_id:
        raise ValueError("Assign a Doctor before billing consultation")
    fee = resolve_fee_version(
        db,
        organization_id=organization_id,
        doctor_id=visit.doctor_id,
        branch_id=visit.branch_id,
        on_date=visit.checkin_at.astimezone(IST).date(),
    )
    if not fee:
        raise ValueError("No active Consultation Fee is configured for this Doctor/Branch/date")
    payload = type("BillPayload", (), {
        "patient_id": patient.patient_id,
        "visit_id": visit.visit_id,
        "doctor_id": visit.doctor_id,
        "branch_id": visit.branch_id,
        "fee_version_id": fee.fee_version_id,
    })()
    return create_bill_draft(db, payload=payload, actor_user_id=actor_user_id)


def finalize_bill(db: Session, *, bill: ConsultationBill, organization_id: uuid.UUID, fiscal_year: str, actor_user_id: uuid.UUID | None = None) -> ConsultationBill:
    locked = db.scalar(
        select(ConsultationBill)
        .where(ConsultationBill.consultation_bill_id == bill.consultation_bill_id)
        .with_for_update()
    )
    if not locked:
        raise ValueError("Bill not found")
    if locked.bill_status != "DRAFT":
        return locked
    branch = db.get(Branch, locked.branch_id)
    if not branch:
        raise ValueError("Branch not found")
    locked.bill_number = allocate_number(
        db,
        organization_id=organization_id,
        series_code="CONSULTATION_BILL",
        branch_id=locked.branch_id,
        fiscal_year=fiscal_year,
        variables={"BRANCH": branch.branch_code},
    )
    locked.bill_status = "FINALIZED"
    locked.finalized_at = _utc_now()
    locked.row_version += 1
    log_audit(
        db,
        organization_id=organization_id,
        entity_type="CONSULTATION_BILL",
        entity_id=locked.consultation_bill_id,
        action="BILL_FINALIZED",
        actor_user_id=actor_user_id,
        after_data={"bill_number": locked.bill_number, "net_amount": str(locked.net_amount)},
    )
    db.flush()
    return locked


def _create_entitlement_after_paid_bill(db: Session, *, bill: ConsultationBill, at: datetime) -> FollowupEntitlement | None:
    existing = db.scalar(select(FollowupEntitlement).where(FollowupEntitlement.source_bill_id == bill.consultation_bill_id))
    if existing:
        return existing
    local_date = at.astimezone(IST).date()
    policy = _active_policy(db, on_date=local_date)
    if not policy:
        return None
    old_entitlements = list(
        db.scalars(
            select(FollowupEntitlement)
            .where(FollowupEntitlement.patient_id == bill.patient_id, FollowupEntitlement.status == "ACTIVE")
            .with_for_update()
        ).all()
    )
    for old in old_entitlements:
        old.status = "SUPERSEDED"
    entitlement = FollowupEntitlement(
        patient_id=bill.patient_id,
        source_visit_id=bill.visit_id,
        source_bill_id=bill.consultation_bill_id,
        policy_version_id=policy.policy_version_id,
        valid_from=at,
        valid_until=at + timedelta(days=policy.free_followup_window_days),
        max_uses=policy.max_free_followups,
        status="ACTIVE",
    )
    db.add(entitlement)
    db.flush()
    return entitlement


def record_payment(db: Session, *, payload, actor_user_id: uuid.UUID, organization_id: uuid.UUID) -> ConsultationPayment:
    bill = db.scalar(
        select(ConsultationBill)
        .where(ConsultationBill.consultation_bill_id == payload.consultation_bill_id)
        .with_for_update()
    )
    if not bill or bill.bill_status not in {"FINALIZED", "PARTIALLY_PAID"}:
        raise ValueError("Bill is not payable")
    if payload.branch_id != bill.branch_id:
        raise ValueError("Payment Branch must match Consultation Bill Branch in Phase 1")
    mode = db.get(PaymentMode, payload.payment_mode_id)
    if not mode or not mode.active:
        raise ValueError("Payment mode is not active")
    already_paid = db.scalar(
        select(func.coalesce(func.sum(ConsultationPayment.amount), 0)).where(
            ConsultationPayment.consultation_bill_id == bill.consultation_bill_id,
            ConsultationPayment.payment_status == "COMPLETED",
        )
    )
    already_paid = Decimal(str(already_paid or 0))
    balance = Decimal(str(bill.net_amount)) - already_paid
    if payload.amount > balance:
        raise ValueError(f"Payment exceeds outstanding balance of {balance}")
    payment = ConsultationPayment(
        consultation_bill_id=bill.consultation_bill_id,
        amount=payload.amount,
        payment_mode_id=payload.payment_mode_id,
        received_by=actor_user_id,
        received_at=payload.received_at,
        branch_id=payload.branch_id,
        payment_status="COMPLETED",
    )
    db.add(payment)
    db.flush()
    total = already_paid + Decimal(str(payload.amount))
    if total == Decimal(str(bill.net_amount)):
        bill.bill_status = "PAID"
        clearance = db.scalar(select(ConsultationClearance).where(ConsultationClearance.visit_id == bill.visit_id))
        if not clearance:
            db.add(
                ConsultationClearance(
                    visit_id=bill.visit_id,
                    patient_id=bill.patient_id,
                    clearance_type="PAID",
                    status="CLEARED",
                    bill_id=bill.consultation_bill_id,
                    cleared_at=payload.received_at,
                )
            )
        _create_entitlement_after_paid_bill(db, bill=bill, at=payload.received_at)
    else:
        bill.bill_status = "PARTIALLY_PAID"
    bill.row_version += 1
    log_audit(
        db,
        organization_id=organization_id,
        entity_type="CONSULTATION_PAYMENT",
        entity_id=payment.payment_id,
        action="PAYMENT_RECORDED",
        actor_user_id=actor_user_id,
        after_data={"bill_id": str(bill.consultation_bill_id), "amount": str(payment.amount), "payment_mode_id": str(payment.payment_mode_id)},
    )
    db.flush()
    return payment


def authorize_complimentary(
    db: Session,
    *,
    visit: Visit,
    patient: Patient,
    doctor: Doctor,
) -> tuple[ComplimentaryAuthorization, ConsultationClearance]:
    if visit.patient_id != patient.patient_id:
        raise ValueError("Visit/Patient mismatch")
    if visit.doctor_id and visit.doctor_id != doctor.doctor_id:
        raise ValueError("Only the Doctor assigned to this Visit can authorize complimentary consultation")
    existing_clearance = db.scalar(select(ConsultationClearance).where(ConsultationClearance.visit_id == visit.visit_id).with_for_update())
    if existing_clearance:
        if existing_clearance.clearance_type == "COMPLIMENTARY":
            auth = db.get(ComplimentaryAuthorization, existing_clearance.complimentary_authorization_id)
            return auth, existing_clearance
        raise ValueError("Visit already has a financial clearance")
    bill = db.scalar(select(ConsultationBill).where(ConsultationBill.visit_id == visit.visit_id))
    if bill and bill.bill_status in {"FINALIZED", "PARTIALLY_PAID", "PAID"}:
        raise ValueError("Post-payment/finalized complimentary conversion is outside Phase 1; send to Admin for manual resolution")
    if bill and bill.bill_status == "DRAFT":
        bill.bill_status = "VOIDED"
        bill.row_version += 1
    now = _utc_now()
    auth = ComplimentaryAuthorization(
        visit_id=visit.visit_id,
        patient_id=patient.patient_id,
        doctor_id=doctor.doctor_id,
        authorized_at=now,
        status="ACTIVE",
    )
    db.add(auth)
    db.flush()
    clearance = ConsultationClearance(
        visit_id=visit.visit_id,
        patient_id=patient.patient_id,
        clearance_type="COMPLIMENTARY",
        status="CLEARED",
        complimentary_authorization_id=auth.authorization_id,
        cleared_at=now,
    )
    db.add(clearance)
    db.flush()
    return auth, clearance


def correct_payment_mode(
    db: Session,
    *,
    payment: ConsultationPayment,
    new_payment_mode_id: uuid.UUID,
    expected_row_version: int,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    reason: str,
) -> ConsultationPayment:
    locked = db.scalar(select(ConsultationPayment).where(ConsultationPayment.payment_id == payment.payment_id).with_for_update())
    if not locked:
        raise ValueError("Payment not found")
    if locked.row_version != expected_row_version:
        raise ValueError("Payment was updated by another user. Reload and review latest values.")
    mode = db.get(PaymentMode, new_payment_mode_id)
    if not mode or not mode.active:
        raise ValueError("Payment mode is not active")
    before = {"payment_mode_id": str(locked.payment_mode_id), "row_version": locked.row_version}
    locked.payment_mode_id = new_payment_mode_id
    locked.row_version += 1
    after = {"payment_mode_id": str(locked.payment_mode_id), "row_version": locked.row_version}
    log_audit(
        db,
        organization_id=organization_id,
        entity_type="CONSULTATION_PAYMENT",
        entity_id=locked.payment_id,
        action="PAYMENT_MODE_CORRECTED",
        actor_user_id=actor_user_id,
        before_data=before,
        after_data=after,
        reason=reason,
    )
    db.flush()
    return locked


def void_bill(
    db: Session,
    *,
    bill: ConsultationBill,
    expected_row_version: int,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    reason: str,
) -> ConsultationBill:
    locked = db.scalar(select(ConsultationBill).where(ConsultationBill.consultation_bill_id == bill.consultation_bill_id).with_for_update())
    if not locked:
        raise ValueError("Bill not found")
    if locked.row_version != expected_row_version:
        raise ValueError("Bill was updated by another user. Reload and review latest values.")
    paid = db.scalar(
        select(func.coalesce(func.sum(ConsultationPayment.amount), 0)).where(
            ConsultationPayment.consultation_bill_id == locked.consultation_bill_id,
            ConsultationPayment.payment_status == "COMPLETED",
        )
    )
    if Decimal(str(paid or 0)) > 0:
        raise ValueError("Paid bills cannot be voided in Phase 1 because automated refunds/credit notes are intentionally out of scope")
    before = {"bill_status": locked.bill_status, "bill_number": locked.bill_number, "row_version": locked.row_version}
    locked.bill_status = "VOIDED"
    locked.row_version += 1
    after = {"bill_status": locked.bill_status, "bill_number": locked.bill_number, "row_version": locked.row_version}
    log_audit(
        db,
        organization_id=organization_id,
        entity_type="CONSULTATION_BILL",
        entity_id=locked.consultation_bill_id,
        action="BILL_VOIDED",
        actor_user_id=actor_user_id,
        before_data=before,
        after_data=after,
        reason=reason,
    )
    db.flush()
    return locked


def visit_decision(db: Session, *, visit: Visit, patient: Patient, organization_id: uuid.UUID) -> dict:
    clearance = db.scalar(select(ConsultationClearance).where(ConsultationClearance.visit_id == visit.visit_id))
    bill = db.scalar(select(ConsultationBill).where(ConsultationBill.visit_id == visit.visit_id))
    status, entitlement = get_eligibility(db, patient_id=patient.patient_id, at=visit.checkin_at)
    fee = None
    if visit.doctor_id:
        fee = resolve_fee_version(
            db,
            organization_id=organization_id,
            doctor_id=visit.doctor_id,
            branch_id=visit.branch_id,
            on_date=visit.checkin_at.astimezone(IST).date(),
        )
    paid_amount = Decimal("0")
    balance = fee.amount if fee else None
    if bill:
        paid_value = db.scalar(
            select(func.coalesce(func.sum(ConsultationPayment.amount), 0)).where(
                ConsultationPayment.consultation_bill_id == bill.consultation_bill_id,
                ConsultationPayment.payment_status == "COMPLETED",
            )
        )
        paid_amount = Decimal(str(paid_value or 0))
        balance = Decimal(str(bill.net_amount)) - paid_amount
    if clearance:
        status = "CLEARED"
    elif bill:
        status = f"BILL_{bill.bill_status}"
    return {
        "visit_id": visit.visit_id,
        "patient_id": patient.patient_id,
        "patient_name": patient.full_name,
        "uhid": patient.uhid,
        "status": status,
        "entitlement_id": entitlement.entitlement_id if entitlement else None,
        "valid_until": entitlement.valid_until if entitlement else None,
        "bill_id": bill.consultation_bill_id if bill else None,
        "bill_number": bill.bill_number if bill else None,
        "bill_status": bill.bill_status if bill else None,
        "clearance_type": clearance.clearance_type if clearance else None,
        "clearance_status": clearance.status if clearance else None,
        "fee_version_id": fee.fee_version_id if fee else None,
        "amount": Decimal(str(bill.net_amount)) if bill else (fee.amount if fee else None),
        "paid_amount": paid_amount,
        "balance": balance,
    }


def _local_bounds(on_date: date) -> tuple[datetime, datetime]:
    local_start = datetime.combine(on_date, time.min, tzinfo=IST)
    local_end = local_start + timedelta(days=1)
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)


def daily_finance_report(
    db: Session,
    *,
    on_date: date,
    organization_id: uuid.UUID,
    branch_id: uuid.UUID | None = None,
    doctor_id: uuid.UUID | None = None,
) -> dict:
    start, end = _local_bounds(on_date)
    clearance_stmt = (
        select(ConsultationClearance, ConsultationBill)
        .join(Visit, Visit.visit_id == ConsultationClearance.visit_id)
        .join(Patient, Patient.patient_id == Visit.patient_id)
        .outerjoin(ConsultationBill, ConsultationBill.consultation_bill_id == ConsultationClearance.bill_id)
        .where(
            ConsultationClearance.cleared_at >= start,
            ConsultationClearance.cleared_at < end,
            Patient.organization_id == organization_id,
        )
    )
    if branch_id:
        clearance_stmt = clearance_stmt.where(Visit.branch_id == branch_id)
    if doctor_id:
        clearance_stmt = clearance_stmt.where(Visit.doctor_id == doctor_id)
    clearances = db.execute(clearance_stmt).all()
    paid = sum(1 for c, _ in clearances if c.clearance_type == "PAID")
    free = sum(1 for c, _ in clearances if c.clearance_type == "FREE_FOLLOWUP")
    comp = sum(1 for c, _ in clearances if c.clearance_type == "COMPLIMENTARY")

    payment_stmt = (
        select(ConsultationPayment, PaymentMode)
        .join(PaymentMode, PaymentMode.payment_mode_id == ConsultationPayment.payment_mode_id)
        .join(ConsultationBill, ConsultationBill.consultation_bill_id == ConsultationPayment.consultation_bill_id)
        .join(Patient, Patient.patient_id == ConsultationBill.patient_id)
        .where(
            Patient.organization_id == organization_id,
            ConsultationPayment.received_at >= start,
            ConsultationPayment.received_at < end,
            ConsultationPayment.payment_status == "COMPLETED",
        )
    )
    if branch_id:
        payment_stmt = payment_stmt.where(ConsultationPayment.branch_id == branch_id)
    if doctor_id:
        payment_stmt = payment_stmt.where(ConsultationBill.doctor_id == doctor_id)
    payments = db.execute(payment_stmt).all()
    totals = {"CASH": Decimal("0"), "UPI": Decimal("0"), "CARD": Decimal("0"), "OTHER": Decimal("0")}
    for payment, mode in payments:
        key = mode.code if mode.code in totals else "OTHER"
        totals[key] += Decimal(str(payment.amount))
    total_collection = sum(totals.values(), Decimal("0"))
    consultation_types = select(VisitType.visit_type_id).where(VisitType.code.in_(["CONSULTATION", "FOLLOW_UP"]))
    visit_count_stmt = (
        select(func.count(Visit.visit_id))
        .join(Patient, Patient.patient_id == Visit.patient_id)
        .where(
            Visit.checkin_at >= start,
            Visit.checkin_at < end,
            Visit.visit_type_id.in_(consultation_types),
            Patient.organization_id == organization_id,
        )
    )
    if branch_id:
        visit_count_stmt = visit_count_stmt.where(Visit.branch_id == branch_id)
    if doctor_id:
        visit_count_stmt = visit_count_stmt.where(Visit.doctor_id == doctor_id)
    total_consultation_visits = db.scalar(visit_count_stmt) or 0
    return {
        "report_date": on_date,
        "branch_id": branch_id,
        "doctor_id": doctor_id,
        "total_consultation_visits": total_consultation_visits,
        "paid_consultations": paid,
        "free_followups": free,
        "complimentary_consultations": comp,
        "total_collection": total_collection,
        "cash": totals["CASH"],
        "upi": totals["UPI"],
        "card": totals["CARD"],
        "other": totals["OTHER"],
    }
