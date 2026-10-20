import uuid
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.access import allowed_branch_ids, ensure_branch_access
from app.core.permissions import require_permission
from app.models.core import Branch, Doctor, User
from app.models.crm import Lead
from app.models.patient import Patient
from app.models.integration import AuditEvent
from app.models.scheduling import Appointment, AppointmentStatus
from app.schemas.scheduling import AppointmentAttendance, AppointmentCreate, AppointmentReschedule
from app.services import appointments as engine

router=APIRouter(prefix="/appointments",tags=["appointments"])
IST=engine.IST
_local_bounds=engine.bounds

def _serialize(db,item):
    branch=db.get(Branch,item.branch_id);doctor=db.get(Doctor,item.doctor_id) if item.doctor_id else None
    status=db.get(AppointmentStatus,item.appointment_status_id)
    lead=db.get(Lead,item.lead_id) if item.lead_id else None
    patient=db.get(Patient,item.patient_id) if item.patient_id else None
    return {"dnc":bool(lead and lead.dnc),**engine.snapshot(item),"appointment_id":item.appointment_id,"branch_id":item.branch_id,"branch":branch.branch_name if branch else None,"doctor_id":item.doctor_id,"doctor":doctor.doctor_name if doctor else None,"lead_id":item.lead_id,"lead_name":lead.lead_name if lead else None,"patient_id":item.patient_id,"patient_name":patient.full_name if patient else None,"uhid":patient.uhid if patient else None,"scheduled_start":item.scheduled_start,"scheduled_end":item.scheduled_end,"status":status.name if status else None,"status_code":status.code if status else None,"booked_via":item.booked_via,"row_version":item.row_version}

@router.get("")
def list_appointments(on_date:date|None=None,branch_id:uuid.UUID|None=None,doctor_id:uuid.UUID|None=None,status_code:str|None=None,patient_id:uuid.UUID|None=None,lead_id:uuid.UUID|None=None,db:Session=Depends(get_db),user:User=Depends(require_permission("APPOINTMENT_CREATE"))):
    start,end=engine.bounds(on_date or engine.now().astimezone(IST).date())
    stmt=select(Appointment).where(Appointment.organization_id==user.organization_id,Appointment.scheduled_start>=start,Appointment.scheduled_start<end)
    allowed=allowed_branch_ids(db,user)
    if branch_id: ensure_branch_access(db,user,branch_id);stmt=stmt.where(Appointment.branch_id==branch_id)
    elif allowed is not None: stmt=stmt.where(Appointment.branch_id.in_(allowed))
    if doctor_id: engine.doctor(db,user,doctor_id);stmt=stmt.where(Appointment.doctor_id==doctor_id)
    if patient_id: stmt=stmt.where(Appointment.patient_id==patient_id)
    if lead_id: stmt=stmt.where(Appointment.lead_id==lead_id)
    if status_code: stmt=stmt.join(AppointmentStatus,AppointmentStatus.appointment_status_id==Appointment.appointment_status_id).where(AppointmentStatus.code==status_code)
    return [_serialize(db,x) for x in db.scalars(stmt.order_by(Appointment.scheduled_start,Appointment.appointment_id)).all()]

@router.get("/availability")
def availability(branch_id:uuid.UUID,doctor_id:uuid.UUID,on_date:date,exclude_appointment_id:uuid.UUID|None=None,db:Session=Depends(get_db),user:User=Depends(require_permission("APPOINTMENT_CREATE"))):
    ensure_branch_access(db,user,branch_id);engine.doctor(db,user,doctor_id)
    if exclude_appointment_id:
        item=db.get(Appointment,exclude_appointment_id)
        if not item or item.organization_id!=user.organization_id: raise HTTPException(404,"Appointment not found")
        ensure_branch_access(db,user,item.branch_id)
    return {"date":on_date,"timezone":"Asia/Kolkata","slots":engine.available_slots(db,doctor_id=doctor_id,branch_id=branch_id,day=on_date,exclude_id=exclude_appointment_id)}

@router.post("")
def create(payload:AppointmentCreate,db:Session=Depends(get_db),user:User=Depends(require_permission("APPOINTMENT_CREATE"))):
    try:
        item=engine.book(db,user,payload);db.commit()
    except IntegrityError:
        db.rollback()
        item=engine.retry_booking(db,user,payload)
        if not item: raise HTTPException(409,"Booking conflicted with another request. Refresh and review")
    return _serialize(db,item)

@router.get("/{appointment_id}")
def detail(appointment_id:uuid.UUID,db:Session=Depends(get_db),user:User=Depends(require_permission("APPOINTMENT_CREATE"))):
    item=db.get(Appointment,appointment_id)
    if not item or item.organization_id!=user.organization_id: raise HTTPException(404,"Appointment not found")
    ensure_branch_access(db,user,item.branch_id)
    history=db.scalars(select(AuditEvent).where(AuditEvent.organization_id==user.organization_id,AuditEvent.entity_type=="APPOINTMENT",AuditEvent.entity_id==appointment_id).order_by(AuditEvent.occurred_at.desc())).all()
    return {**_serialize(db,item),"history":[{"action":x.action,"reason":x.reason,"occurred_at":x.occurred_at,"actor_user_id":x.actor_user_id,"before":x.before_data,"after":x.after_data} for x in history]}

@router.patch("/{appointment_id}/reschedule")
def reschedule(appointment_id:uuid.UUID,payload:AppointmentReschedule,db:Session=Depends(get_db),user:User=Depends(require_permission("APPOINTMENT_EDIT"))):
    item=engine.reschedule(db,user,appointment_id,payload);db.commit();return _serialize(db,item)

@router.patch("/{appointment_id}/status")
def update_status(appointment_id:uuid.UUID,status_code:str,row_version:int=Query(ge=1),reason:str|None=Query(default=None,max_length=500),db:Session=Depends(get_db),user:User=Depends(require_permission("APPOINTMENT_EDIT"))):
    item=engine.set_status(db,user,appointment_id,status_code,row_version,reason);db.commit();return _serialize(db,item)


@router.patch("/{appointment_id}/attendance")
def attendance(appointment_id:uuid.UUID,payload:AppointmentAttendance,db:Session=Depends(get_db),user:User=Depends(require_permission("APPOINTMENT_EDIT"))):
    item=engine.set_status(db,user,appointment_id,payload.status_code,payload.row_version,payload.reason);db.commit();return _serialize(db,item)
