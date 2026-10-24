"""Organization-scoped catalogue; this API never returns patient diagnoses."""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.permissions import require_permission
from app.models.core import Organization, User
from app.models.diagnosis import Diagnosis
from app.services.diagnoses import normalized
from app.services.audit import log_audit

router = APIRouter(prefix="/diagnoses", tags=["diagnoses"])

class CatalogueInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=240)
    category: str = Field(min_length=1, max_length=120)
    active: bool = True
    requires_review: bool = False

    @field_validator("name", "category")
    @classmethod
    def clean(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("Enter a nonblank value")
        return value


class CatalogueUpdate(CatalogueInput):
    row_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=1000)

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value):
        if len(value.strip()) < 3:
            raise ValueError("Enter a reason")
        return value.strip()


def serialize(d):
    return {"diagnosis_id":d.diagnosis_id, "name":d.name, "category":d.category,
            "active":d.active, "requires_review":d.requires_review, "row_version":d.row_version,
            "source_row":d.source_row, "source_key":d.source_key}


@router.get("")
def catalogue(q: str = Query("", max_length=240), include_inactive: bool = False,
              offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=250),
              db: Session = Depends(get_db), user: User = Depends(require_permission("DIAGNOSIS_MASTER_MANAGE"))):
    stmt = select(Diagnosis).where(Diagnosis.organization_id == user.organization_id)
    if not include_inactive:
        stmt = stmt.where(Diagnosis.active.is_(True), Diagnosis.requires_review.is_(False))
    if q.strip():
        stmt = stmt.where(or_(Diagnosis.normalized_name.contains(normalized(q), autoescape=True),
                             Diagnosis.category.icontains(q.strip(), autoescape=True)))
    return [serialize(d) for d in db.scalars(stmt.order_by(Diagnosis.normalized_name, Diagnosis.diagnosis_id).offset(offset).limit(limit)).all()]


@router.post("", status_code=201)
def create(payload: CatalogueInput, db: Session = Depends(get_db), user: User = Depends(require_permission("DIAGNOSIS_MASTER_MANAGE"))):
    try:
        db.scalar(select(Organization).where(Organization.organization_id == user.organization_id).with_for_update())
        if payload.active and payload.requires_review:
            raise HTTPException(422, "An entry awaiting review must remain inactive")
        row = Diagnosis(organization_id=user.organization_id, normalized_name=normalized(payload.name), **payload.model_dump())
        db.add(row); db.flush()
        log_audit(db, organization_id=user.organization_id, entity_type="DIAGNOSIS_MASTER", entity_id=row.diagnosis_id,
                  action="CREATE", actor_user_id=user.user_id, after_data={"name":row.name,"category":row.category,"active":row.active,"requires_review":row.requires_review})
        db.commit()
        return serialize(row)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "A diagnosis with this name already exists, including inactive entries") from exc
    except Exception:
        db.rollback(); raise


@router.patch("/{diagnosis_id}")
def update(diagnosis_id: uuid.UUID, payload: CatalogueUpdate, db: Session = Depends(get_db), user: User = Depends(require_permission("DIAGNOSIS_MASTER_MANAGE"))):
    try:
        db.scalar(select(Organization).where(Organization.organization_id == user.organization_id).with_for_update())
        row = db.scalar(select(Diagnosis).where(Diagnosis.diagnosis_id == diagnosis_id, Diagnosis.organization_id == user.organization_id).execution_options(populate_existing=True).with_for_update())
        if not row:
            raise HTTPException(404, "Diagnosis not found")
        if row.row_version != payload.row_version:
            raise HTTPException(409, "Diagnosis changed. Refresh before saving")
        if payload.active and payload.requires_review:
            raise HTTPException(422, "An entry awaiting review must remain inactive")
        fields = ("name", "category", "active", "requires_review")
        before = {key:getattr(row,key) for key in fields}
        for key in fields:
            setattr(row, key, getattr(payload,key))
        row.normalized_name = normalized(row.name)
        row.row_version += 1
        log_audit(db, organization_id=user.organization_id, entity_type="DIAGNOSIS_MASTER", entity_id=row.diagnosis_id,
                  action="UPDATE", actor_user_id=user.user_id, before_data=before, after_data={key:getattr(row,key) for key in fields}, reason=payload.reason)
        db.commit()
        return serialize(row)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "A diagnosis with this name already exists") from exc
    except Exception:
        db.rollback(); raise
