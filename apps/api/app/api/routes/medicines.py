"""Medicine catalogue maintenance; only a linked Doctor may verify products."""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.permissions import require_permission
from app.models.core import Organization, User
from app.models.prescription import Medicine
from app.services.prescriptions import PRODUCT_FIELDS, set_search
from app.services.diagnoses import normalized
from app.services.audit import log_audit

router = APIRouter(prefix="/medicines", tags=["medicines"])


class ProductInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brand: str = Field(default="", max_length=240)
    generic: str = Field(default="", max_length=300)
    strength: str = Field(default="", max_length=240)
    form: str = Field(default="", max_length=120)
    route: str = Field(default="", max_length=120)
    pack_size: str = Field(default="", max_length=120)
    manufacturer: str = Field(default="", max_length=240)
    active: bool = False
    review_confirmed: bool = False

    @field_validator(*PRODUCT_FIELDS)
    @classmethod
    def clean(cls,value):
        return " ".join(value.split())


class ProductUpdate(ProductInput):
    row_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reason_text(cls,value):
        if len(value.strip()) < 3:
            raise ValueError("Enter a reason")
        return value.strip()


def serialize(row):
    return {"medicine_id":row.medicine_id, **{f:getattr(row,f) for f in PRODUCT_FIELDS},
            "active":row.active,"requires_review":row.requires_review,"row_version":row.row_version,
            "verified_at":row.verified_at,"source_row":row.source_row,"source_verification":row.source_verification,
            "source_url":row.source_url}


def apply(db,user,row,payload):
    if not payload.brand and not payload.generic:
        raise HTTPException(422,"Enter a brand or generic name")
    changed = any(getattr(row,f,None) != getattr(payload,f) for f in PRODUCT_FIELDS)
    if payload.review_confirmed:
        require_permission("MEDICINE_MASTER_VERIFY")(user=user,db=db)
        from app.api.routes.doctor_consultations import doctor_for
        doctor = doctor_for(db,user)
        if not all(getattr(payload,f).strip() for f in ("generic","strength","form","route")):
            raise HTTPException(422,"Verification requires composition/generic, exact strength, form and route. Use Not applicable only when clinically appropriate")
        row.verified_by_doctor_id = doctor.doctor_id
        row.verified_at = datetime.now(timezone.utc)
        row.requires_review = False
    elif changed:
        row.requires_review = True
        row.verified_by_doctor_id = None;row.verified_at = None
    if payload.active and (row.requires_review is not False or not row.verified_by_doctor_id):
        raise HTTPException(409,"A Doctor must verify the product details before activation")
    for f in PRODUCT_FIELDS:
        setattr(row,f,getattr(payload,f))
    row.active = payload.active
    set_search(row)


@router.get("")
def catalogue(q: str = Query("",max_length=300), include_inactive: bool = False,
              offset: int = Query(0,ge=0), limit: int = Query(100,ge=1,le=250),
              db: Session = Depends(get_db), user: User = Depends(require_permission("MEDICINE_MASTER_MANAGE"))):
    stmt = select(Medicine).where(Medicine.organization_id == user.organization_id)
    if not include_inactive:
        stmt = stmt.where(Medicine.active.is_(True),Medicine.requires_review.is_(False))
    if q.strip():
        stmt = stmt.where(Medicine.search_name.contains(normalized(q),autoescape=True))
    return [serialize(r) for r in db.scalars(stmt.order_by(Medicine.search_name,Medicine.medicine_id).offset(offset).limit(limit)).all()]


@router.post("",status_code=201)
def create(payload:ProductInput, db:Session=Depends(get_db), user:User=Depends(require_permission("MEDICINE_MASTER_MANAGE"))):
    try:
        db.scalar(select(Organization).where(Organization.organization_id==user.organization_id).with_for_update())
        row=Medicine(organization_id=user.organization_id,requires_review=True)
        apply(db,user,row,payload);db.add(row);db.flush()
        log_audit(db,organization_id=user.organization_id,entity_type="MEDICINE_MASTER",entity_id=row.medicine_id,action="CREATE",actor_user_id=user.user_id,after_data={**{f:getattr(row,f) for f in PRODUCT_FIELDS},"active":row.active,"requires_review":row.requires_review})
        db.commit();return serialize(row)
    except IntegrityError as exc:
        db.rollback();raise HTTPException(409,"This exact medicine product already exists, including inactive entries") from exc
    except Exception:
        db.rollback();raise


@router.patch("/{medicine_id}")
def update(medicine_id:uuid.UUID,payload:ProductUpdate,db:Session=Depends(get_db),user:User=Depends(require_permission("MEDICINE_MASTER_MANAGE"))):
    try:
        db.scalar(select(Organization).where(Organization.organization_id==user.organization_id).with_for_update())
        row=db.scalar(select(Medicine).where(Medicine.medicine_id==medicine_id,Medicine.organization_id==user.organization_id).execution_options(populate_existing=True).with_for_update())
        if not row:raise HTTPException(404,"Medicine not found")
        if row.row_version!=payload.row_version:raise HTTPException(409,"Medicine changed. Refresh before saving")
        before={**{f:getattr(row,f) for f in PRODUCT_FIELDS},"active":row.active,"requires_review":row.requires_review}
        apply(db,user,row,payload);row.row_version+=1
        log_audit(db,organization_id=user.organization_id,entity_type="MEDICINE_MASTER",entity_id=row.medicine_id,action="VERIFY" if payload.review_confirmed else "UPDATE",actor_user_id=user.user_id,before_data=before,after_data={**{f:getattr(row,f) for f in PRODUCT_FIELDS},"active":row.active,"requires_review":row.requires_review},reason=payload.reason)
        db.commit();return serialize(row)
    except IntegrityError as exc:
        db.rollback();raise HTTPException(409,"This exact medicine product already exists") from exc
    except Exception:
        db.rollback();raise
