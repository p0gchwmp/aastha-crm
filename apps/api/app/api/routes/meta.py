from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.access import allowed_branch_ids
from app.core.security import current_user
from app.models.clinical import ChiefComplaint, VisitStatus, VisitType
from app.models.core import Branch, Doctor, Service, User
from app.models.crm import LeadSource, LeadStatus, LostReason
from app.models.patient import District, Locality, Region
from app.models.scheduling import AppointmentStatus
from app.schemas.core import BootstrapOut, BranchItem, DistrictItem, DoctorItem, LocalityItem, LookupItem, NamedItem

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/bootstrap", response_model=BootstrapOut)
def bootstrap(db: Session = Depends(get_db), user: User = Depends(current_user)):
    branches = list(db.scalars(select(Branch).where(Branch.organization_id == user.organization_id, Branch.active.is_(True)).order_by(Branch.branch_name)).all())
    allowed = allowed_branch_ids(db, user)
    if allowed is not None:
        branches = [branch for branch in branches if branch.branch_id in allowed]
    doctors = list(db.scalars(select(Doctor).where(Doctor.organization_id == user.organization_id, Doctor.active.is_(True)).order_by(Doctor.doctor_name)).all())
    sources = list(db.scalars(select(LeadSource).where(LeadSource.active.is_(True)).order_by(LeadSource.name)).all())
    statuses = list(db.scalars(select(LeadStatus).order_by(LeadStatus.name)).all())
    lost_reasons = list(db.scalars(select(LostReason).where(LostReason.active.is_(True)).order_by(LostReason.name)).all())
    appt_statuses = list(db.scalars(select(AppointmentStatus).order_by(AppointmentStatus.name)).all())
    services = list(db.scalars(select(Service).where(Service.organization_id == user.organization_id, Service.active.is_(True)).order_by(Service.service_name)).all())
    visit_types = list(db.scalars(select(VisitType).where(VisitType.active.is_(True)).order_by(VisitType.name)).all())
    visit_statuses = list(db.scalars(select(VisitStatus).order_by(VisitStatus.name)).all())
    complaints = list(db.scalars(select(ChiefComplaint).where(ChiefComplaint.active.is_(True), ChiefComplaint.merged_into_complaint_id.is_(None)).order_by(ChiefComplaint.name)).all())
    regions = list(db.scalars(select(Region).where(Region.status == "ACTIVE").order_by(Region.name)).all())
    districts = list(db.scalars(select(District).where(District.status == "ACTIVE").order_by(District.name)).all())
    localities = list(db.scalars(select(Locality).where(Locality.approval_status.in_(["APPROVED", "PENDING"]), Locality.merged_into_locality_id.is_(None)).order_by(Locality.locality_name)).all())
    if not branches:
        raise HTTPException(503, "CRM masters are not seeded")
    return BootstrapOut(
        organization_id=user.organization_id,
        branches=[BranchItem(id=x.branch_id, code=x.branch_code, name=x.branch_name) for x in branches],
        doctors=[DoctorItem(id=x.doctor_id, code=x.doctor_code, name=x.doctor_name) for x in doctors],
        lead_sources=[LookupItem(id=x.lead_source_id, code=x.code, name=x.name) for x in sources],
        lead_statuses=[LookupItem(id=x.lead_status_id, code=x.code, name=x.name) for x in statuses],
        lost_reasons=[LookupItem(id=x.lost_reason_id, code=x.code, name=x.name) for x in lost_reasons],
        appointment_statuses=[LookupItem(id=x.appointment_status_id, code=x.code, name=x.name) for x in appt_statuses],
        services=[LookupItem(id=x.service_id, code=x.service_code, name=x.service_name) for x in services],
        visit_types=[LookupItem(id=x.visit_type_id, code=x.code, name=x.name) for x in visit_types],
        visit_statuses=[LookupItem(id=x.visit_status_id, code=x.code, name=x.name) for x in visit_statuses],
        chief_complaints=[NamedItem(id=x.chief_complaint_id, name=x.name) for x in complaints],
        regions=[NamedItem(id=x.region_id, name=x.name) for x in regions],
        districts=[DistrictItem(id=x.district_id, name=x.name, region_id=x.region_id) for x in districts],
        localities=[LocalityItem(id=x.locality_id, name=x.locality_name, district_id=x.district_id, approval_status=x.approval_status) for x in localities],
    )
