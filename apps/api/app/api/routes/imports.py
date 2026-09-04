import json
import uuid
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.permissions import require_permission
from app.models.core import Branch, User
from app.models.patient import ImportBatch, ImportStaging, Patient
from app.schemas.imports import ImportCommitRequest, ImportRowAction
from app.services.audit import log_audit
from app.services.legacy_import import commit_import, detect_mapping, read_uploaded_rows, stage_import

router = APIRouter(prefix="/imports", tags=["imports"])


@router.post("/patients/upload")
async def upload_patient_import(
    file: UploadFile = File(...),
    registration_branch_id: uuid.UUID = Form(...),
    mapping_json: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("PATIENT_IMPORT")),
):
    branch = db.get(Branch, registration_branch_id)
    if not branch or branch.organization_id != user.organization_id: raise HTTPException(400, "Registration Branch not found")
    data = await file.read()
    try: rows = read_uploaded_rows(file.filename or "", data)
    except Exception as exc: raise HTTPException(400, str(exc)) from exc
    if not rows: raise HTTPException(400, "Import file contains no patient rows")
    if len(rows) > 25000: raise HTTPException(413, "Maximum 25,000 patient rows per import batch")
    try: override = json.loads(mapping_json) if mapping_json else {}
    except Exception: raise HTTPException(400, "mapping_json must be valid JSON")
    mapping = detect_mapping(rows[0].keys(), override)
    batch = ImportBatch(organization_id=user.organization_id, file_name=file.filename or "patient-import", uploaded_by=user.user_id, status="UPLOADED")
    db.add(batch); db.flush()
    info = stage_import(db, batch=batch, rows=rows, mapping=mapping, organization_id=user.organization_id, branch_id=registration_branch_id)
    log_audit(db, organization_id=user.organization_id, entity_type="PATIENT_IMPORT_BATCH", entity_id=batch.import_batch_id, action="IMPORT_STAGED", actor_user_id=user.user_id, after_data={"rows":len(rows),"ignored_financial_columns":info["ignored_financial_columns"]})
    db.commit(); db.refresh(batch)
    return {"import_batch_id":batch.import_batch_id,"file_name":batch.file_name,"status":batch.status,"total_rows":batch.total_rows,"error_rows":batch.error_rows,"duplicate_rows":batch.duplicate_rows,**info}


@router.get("/patients/batches")
def batches(db: Session = Depends(get_db), user: User = Depends(require_permission("PATIENT_IMPORT"))):
    rows = list(db.scalars(select(ImportBatch).where(ImportBatch.organization_id==user.organization_id).order_by(ImportBatch.created_at.desc()).limit(50)).all())
    return [{"import_batch_id":x.import_batch_id,"file_name":x.file_name,"status":x.status,"total_rows":x.total_rows,"imported_rows":x.imported_rows,"error_rows":x.error_rows,"duplicate_rows":x.duplicate_rows,"created_at":x.created_at} for x in rows]


@router.get("/patients/{batch_id}/preview")
def preview(batch_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_permission("PATIENT_IMPORT"))):
    batch = db.get(ImportBatch,batch_id)
    if not batch or batch.organization_id != user.organization_id: raise HTTPException(404,"Import batch not found")
    rows = list(db.scalars(select(ImportStaging).where(ImportStaging.import_batch_id==batch_id).order_by(ImportStaging.source_row_number).limit(1000)).all())
    return {"batch":{"id":batch.import_batch_id,"file_name":batch.file_name,"status":batch.status,"total_rows":batch.total_rows,"duplicate_rows":batch.duplicate_rows,"error_rows":batch.error_rows},"rows":[{"staging_id":r.staging_id,"row":r.source_row_number,"data":r.raw_data.get("data",{}),"candidates":r.raw_data.get("candidates",[]),"validation_status":r.validation_status,"matched_patient_id":r.matched_patient_id,"import_action":r.import_action,"error_message":r.error_message} for r in rows]}


@router.patch("/patients/{batch_id}/rows/{staging_id}")
def set_row_action(batch_id: uuid.UUID, staging_id: uuid.UUID, payload: ImportRowAction, db: Session = Depends(get_db), user: User = Depends(require_permission("PATIENT_IMPORT"))):
    batch = db.get(ImportBatch, batch_id)
    if not batch or batch.organization_id != user.organization_id: raise HTTPException(404,"Import batch not found")
    row = db.scalar(select(ImportStaging).where(ImportStaging.import_batch_id==batch_id,ImportStaging.staging_id==staging_id).with_for_update())
    if not row: raise HTTPException(404,"Staging row not found")
    if payload.action == "LINK_EXISTING":
        pid = payload.matched_patient_id or row.matched_patient_id
        if not pid or not db.get(Patient,pid): raise HTTPException(400,"Existing Patient must be selected")
        row.matched_patient_id = pid
    row.import_action = payload.action; row.validation_status = "READY" if payload.action in {"CREATE","CREATE_SEPARATE","LINK_EXISTING"} else "SKIPPED"
    db.commit()
    return {"staging_id":row.staging_id,"import_action":row.import_action,"matched_patient_id":row.matched_patient_id}


@router.post("/patients/{batch_id}/commit")
def commit(batch_id: uuid.UUID, payload: ImportCommitRequest, db: Session = Depends(get_db), user: User = Depends(require_permission("PATIENT_IMPORT"))):
    batch = db.scalar(select(ImportBatch).where(ImportBatch.import_batch_id==batch_id, ImportBatch.organization_id==user.organization_id).with_for_update())
    if not batch: raise HTTPException(404,"Import batch not found")
    if batch.status.startswith("COMPLETED"): raise HTTPException(409,"Import batch is already completed")
    try: result = commit_import(db,batch=batch,organization_id=user.organization_id,branch_id=payload.registration_branch_id,actor_user_id=user.user_id)
    except Exception as exc: db.rollback(); raise HTTPException(409,str(exc)) from exc
    log_audit(db, organization_id=user.organization_id, entity_type="PATIENT_IMPORT_BATCH", entity_id=batch.import_batch_id, action="IMPORT_COMMITTED", actor_user_id=user.user_id, after_data=result)
    db.commit()
    return {"import_batch_id":batch.import_batch_id,"status":batch.status,**result}
