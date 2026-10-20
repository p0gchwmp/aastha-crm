"""Permission-controlled schedule configuration. Existing appointments are never moved implicitly."""
import uuid
from datetime import date, datetime, time
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.access import allowed_branch_ids, ensure_branch_access
from app.core.permissions import require_permission
from app.models.core import User, Branch, Doctor
from app.models.scheduling import DoctorSchedule, ScheduleException, Appointment, AppointmentStatus
from app.schemas.scheduling import ScheduleFields, ScheduleUpdate, ExceptionCreate, VersionReason
from app.services import appointments as engine
from app.services.audit import log_audit
router=APIRouter(prefix="/appointments",tags=["doctor schedules"])
manager=require_permission("APPOINTMENT_SCHEDULE_MANAGE")

def recurring_data(db,x):
    b=db.get(Branch,x.branch_id);d=db.get(Doctor,x.doctor_id)
    return {"schedule_id":x.schedule_id,"doctor_id":x.doctor_id,"doctor":d.doctor_name if d else None,"branch_id":x.branch_id,"branch":b.branch_name if b else None,**{k:getattr(x,k) for k in ("day_of_week","start_time","end_time","slot_duration_minutes","effective_from","effective_until","active","row_version")}}

def exception_data(db,x):
    b=db.get(Branch,x.branch_id);d=db.get(Doctor,x.doctor_id)
    return {"exception_id":x.exception_id,"doctor_id":x.doctor_id,"doctor":d.doctor_name if d else None,"branch_id":x.branch_id,"branch":b.branch_name if b else None,**{k:getattr(x,k) for k in ("date","start_time","end_time","exception_type","slot_duration_minutes","note","row_version")}}

def overlaps(a,b):
    return a.day_of_week==b.day_of_week and a.effective_from<=(b.effective_until or date.max) and b.effective_from<=(a.effective_until or date.max) and a.start_time<b.end_time and a.end_time>b.start_time

def check_overlap(db,payload,ignore=None):
    if not payload.active: return
    for other in db.scalars(select(DoctorSchedule).where(DoctorSchedule.doctor_id==payload.doctor_id,DoctorSchedule.active.is_(True))).all():
        if other.schedule_id!=ignore and overlaps(payload,other): raise HTTPException(409,"Doctor schedules overlap, including across branches. Disable or adjust the conflicting window first")
    for other in db.scalars(select(ScheduleException).where(ScheduleException.doctor_id==payload.doctor_id,ScheduleException.exception_type=="ADDITIONAL")).all():
        if payload.effective_from<=other.date<=(payload.effective_until or date.max) and other.date.weekday()==payload.day_of_week and payload.start_time<other.end_time and payload.end_time>other.start_time:
            raise HTTPException(409,"Schedule overlaps an additional clinic exception")

def future_bookings(db,doctor_id,branch_id):
    return db.scalars(select(Appointment).join(AppointmentStatus,AppointmentStatus.appointment_status_id==Appointment.appointment_status_id).where(Appointment.doctor_id==doctor_id,Appointment.branch_id==branch_id,Appointment.scheduled_end>engine.now(),AppointmentStatus.code.not_in(engine.TERMINAL))).all()

def protects_window(db,doctor_id,branch_id,day,first,last):
    start,end=engine.bounds(day)
    if first is not None: start=engine.utc(datetime.combine(day,first,tzinfo=engine.IST));end=engine.utc(datetime.combine(day,last,tzinfo=engine.IST))
    if any(engine.utc(a.scheduled_start)<end and engine.utc(a.scheduled_end)>start for a in future_bookings(db,doctor_id,branch_id)):
        raise HTTPException(409,"Existing appointments are affected. Reschedule or cancel them before changing availability")

def config_audit(db,user,entity,identity,action,before,after,reason):
    def clean(data): return {k:(str(v) if v is not None else None) for k,v in data.items()} if data else None
    log_audit(db,organization_id=user.organization_id,entity_type=entity,entity_id=identity,action=action,actor_user_id=user.user_id,before_data=clean(before),after_data=clean(after),reason=reason)

@router.get("/schedules")
def list_schedules(db:Session=Depends(get_db),user:User=Depends(manager)):
    rows=db.scalars(select(DoctorSchedule).join(Doctor,Doctor.doctor_id==DoctorSchedule.doctor_id).where(Doctor.organization_id==user.organization_id).order_by(DoctorSchedule.day_of_week,DoctorSchedule.start_time)).all()
    allowed=allowed_branch_ids(db,user)
    if allowed is not None: rows=[x for x in rows if x.branch_id in allowed]
    active=[x for x in rows if x.active]
    warnings=["Existing schedules overlap for this doctor. Review and correct the windows before clinic use."] if any(a.doctor_id==b.doctor_id and overlaps(a,b) for i,a in enumerate(active) for b in active[i+1:]) else []
    return {"schedules":[recurring_data(db,x) for x in rows],"warnings":warnings,"timezone":"Asia/Kolkata"}

@router.post("/schedules",status_code=201)
def create_schedule(payload:ScheduleFields,db:Session=Depends(get_db),user:User=Depends(manager)):
    ensure_branch_access(db,user,payload.branch_id);engine.lock_doctors(db,user,[payload.doctor_id]);check_overlap(db,payload)
    item=DoctorSchedule(**payload.model_dump(exclude={"reason"}));db.add(item);db.flush()
    config_audit(db,user,"DOCTOR_SCHEDULE",item.schedule_id,"SCHEDULE_CREATED",None,recurring_data(db,item),payload.reason)
    db.commit();return recurring_data(db,item)

@router.patch("/schedules/{schedule_id}")
def edit_schedule(schedule_id:uuid.UUID,payload:ScheduleUpdate,db:Session=Depends(get_db),user:User=Depends(manager)):
    engine.lock_doctors(db,user,[payload.doctor_id]);ensure_branch_access(db,user,payload.branch_id)
    item=db.scalar(select(DoctorSchedule).where(DoctorSchedule.schedule_id==schedule_id).with_for_update().execution_options(populate_existing=True))
    if not item or item.doctor_id!=payload.doctor_id or item.branch_id!=payload.branch_id: raise HTTPException(404,"Schedule not found; doctor and branch cannot be changed on an existing window")
    engine.check_version(item,payload.row_version)
    for a in future_bookings(db,item.doctor_id,item.branch_id):
        local=engine.utc(a.scheduled_start).astimezone(engine.IST)
        if item.effective_from<=local.date()<=(item.effective_until or date.max) and local.weekday()==item.day_of_week and item.start_time<=local.time().replace(tzinfo=None)<item.end_time:
            raise HTTPException(409,"This schedule has appointments. Reschedule or cancel them first, or add a non-overlapping future period")
    check_overlap(db,payload,item.schedule_id);before=recurring_data(db,item)
    for k,v in payload.model_dump(exclude={"row_version","reason"}).items(): setattr(item,k,v)
    item.row_version+=1
    config_audit(db,user,"DOCTOR_SCHEDULE",item.schedule_id,"SCHEDULE_UPDATED",before,recurring_data(db,item),payload.reason)
    db.commit();return recurring_data(db,item)

@router.get("/schedule-exceptions")
def list_exceptions(on_date:date|None=None,db:Session=Depends(get_db),user:User=Depends(manager)):
    stmt=select(ScheduleException).join(Doctor,Doctor.doctor_id==ScheduleException.doctor_id).where(Doctor.organization_id==user.organization_id)
    allowed=allowed_branch_ids(db,user)
    if allowed is not None: stmt=stmt.where(ScheduleException.branch_id.in_(allowed))
    if on_date: stmt=stmt.where(ScheduleException.date==on_date)
    else: stmt=stmt.where(ScheduleException.date>=engine.now().astimezone(engine.IST).date())
    return [exception_data(db,x) for x in db.scalars(stmt.order_by(ScheduleException.date).limit(200)).all()]

@router.post("/schedule-exceptions",status_code=201)
def create_exception(payload:ExceptionCreate,db:Session=Depends(get_db),user:User=Depends(manager)):
    ensure_branch_access(db,user,payload.branch_id);engine.lock_doctors(db,user,[payload.doctor_id])
    if payload.exception_type!="ADDITIONAL": protects_window(db,payload.doctor_id,payload.branch_id,payload.date,payload.start_time,payload.end_time)
    else:
        for s in db.scalars(select(DoctorSchedule).where(DoctorSchedule.doctor_id==payload.doctor_id,DoctorSchedule.active.is_(True),DoctorSchedule.day_of_week==payload.date.weekday(),DoctorSchedule.effective_from<=payload.date,(DoctorSchedule.effective_until.is_(None)|(DoctorSchedule.effective_until>=payload.date)))).all():
            if s.start_time<payload.end_time and s.end_time>payload.start_time: raise HTTPException(409,"Additional clinic overlaps a configured schedule")
        for x in db.scalars(select(ScheduleException).where(ScheduleException.doctor_id==payload.doctor_id,ScheduleException.date==payload.date,ScheduleException.exception_type=="ADDITIONAL")).all():
            if x.start_time<payload.end_time and x.end_time>payload.start_time: raise HTTPException(409,"Additional clinic overlaps another additional clinic")
    item=ScheduleException(**payload.model_dump(exclude={"reason"}),note=payload.reason);db.add(item);db.flush()
    config_audit(db,user,"SCHEDULE_EXCEPTION",item.exception_id,"EXCEPTION_CREATED",None,exception_data(db,item),payload.reason)
    db.commit();return exception_data(db,item)

@router.patch("/schedule-exceptions/{exception_id}/cancel")
def cancel_exception(exception_id:uuid.UUID,payload:VersionReason,db:Session=Depends(get_db),user:User=Depends(manager)):
    candidate=db.get(ScheduleException,exception_id)
    if not candidate: raise HTTPException(404,"Exception not found")
    engine.lock_doctors(db,user,[candidate.doctor_id]);ensure_branch_access(db,user,candidate.branch_id)
    item=db.scalar(select(ScheduleException).where(ScheduleException.exception_id==exception_id).with_for_update().execution_options(populate_existing=True));engine.check_version(item,payload.row_version)
    if item.exception_type=="CANCELLED": raise HTTPException(409,"Exception already cancelled")
    if item.exception_type=="ADDITIONAL": protects_window(db,item.doctor_id,item.branch_id,item.date,item.start_time,item.end_time)
    before=exception_data(db,item);item.exception_type="CANCELLED";item.row_version+=1
    config_audit(db,user,"SCHEDULE_EXCEPTION",item.exception_id,"EXCEPTION_CANCELLED",before,exception_data(db,item),payload.reason)
    db.commit();return exception_data(db,item)
