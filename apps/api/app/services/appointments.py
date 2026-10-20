"""One availability engine for UI/API booking; doctor locks serialize all slot writers."""
import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import select
from app.core.access import ensure_branch_access
from app.models.core import Doctor, Service
from app.models.crm import Lead, LeadStatus, LeadStatusHistory, LeadInteraction
from app.models.patient import Patient
from app.models.scheduling import Appointment, AppointmentStatus, DoctorSchedule, ScheduleException
from app.services.audit import log_audit

IST = ZoneInfo("Asia/Kolkata")
FREE_STATUSES = {"CANCELLED", "NO_SHOW"}
TERMINAL = {"CANCELLED", "NO_SHOW", "COMPLETED"}

def now():
    return datetime.now(timezone.utc)

def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

def bounds(day):
    start=datetime.combine(day,time.min,tzinfo=IST).astimezone(timezone.utc)
    return start,start+timedelta(days=1)

def doctor(db, actor, doctor_id, *, lock=False):
    stmt=select(Doctor).where(Doctor.doctor_id==doctor_id,Doctor.organization_id==actor.organization_id,Doctor.active.is_(True))
    if lock: stmt=stmt.with_for_update().execution_options(populate_existing=True)
    item=db.scalar(stmt)
    if not item: raise HTTPException(404,"Active doctor not found")
    return item

def lock_doctors(db,actor,ids):
    for key in sorted({x for x in ids if x},key=str): doctor(db,actor,key,lock=True)

def status(db, code):
    item=db.scalar(select(AppointmentStatus).where(AppointmentStatus.code==code))
    if not item: raise HTTPException(503,f"Appointment status {code} is not configured")
    return item

def lead_for(db,actor,lead_id):
    if not lead_id: return None
    lead=db.scalar(select(Lead).where(Lead.lead_id==lead_id,Lead.organization_id==actor.organization_id).with_for_update().execution_options(populate_existing=True))
    if not lead: raise HTTPException(404,"Lead not found")
    if lead.preferred_branch_id: ensure_branch_access(db,actor,lead.preferred_branch_id)
    return lead

def require_open_lead(db,lead,allow_converted=False):
    if lead and db.get(LeadStatus,lead.lead_status_id).code in ({"LOST","NO_SHOW","SPAM_FAKE"} if allow_converted else {"LOST","NO_SHOW","SPAM_FAKE","CONVERTED"}):
        raise HTTPException(409,"Reopen the existing Lead first, or explicitly select the registered Patient for a converted Lead")

def available_slots(db, *, doctor_id, branch_id, day, exclude_id=None):
    schedules=db.scalars(select(DoctorSchedule).where(DoctorSchedule.doctor_id==doctor_id,DoctorSchedule.branch_id==branch_id,DoctorSchedule.day_of_week==day.weekday(),DoctorSchedule.active.is_(True),DoctorSchedule.effective_from<=day,(DoctorSchedule.effective_until.is_(None)|(DoctorSchedule.effective_until>=day)))).all()
    exceptions=db.scalars(select(ScheduleException).where(ScheduleException.doctor_id==doctor_id,ScheduleException.branch_id==branch_id,ScheduleException.date==day,ScheduleException.exception_type!="CANCELLED")).all()
    if any(x.exception_type!="ADDITIONAL" and x.start_time is None for x in exceptions): return []
    windows=[(s.start_time,s.end_time,s.slot_duration_minutes) for s in schedules]
    windows += [(x.start_time,x.end_time,x.slot_duration_minutes) for x in exceptions if x.exception_type=="ADDITIONAL"]
    start,end=bounds(day)
    stmt=select(Appointment).join(AppointmentStatus,AppointmentStatus.appointment_status_id==Appointment.appointment_status_id).where(Appointment.doctor_id==doctor_id,Appointment.scheduled_start<end,Appointment.scheduled_end>start,AppointmentStatus.code.not_in(FREE_STATUSES))
    if exclude_id: stmt=stmt.where(Appointment.appointment_id!=exclude_id)
    booked=db.scalars(stmt).all()  # All branches: a doctor cannot be in two places at once.
    closures=[x for x in exceptions if x.exception_type!="ADDITIONAL" and x.start_time is not None]
    result={}
    for first,last,minutes in windows:
        if minutes<=0 or first is None or last is None: continue
        cursor=datetime.combine(day,first,tzinfo=IST);until=datetime.combine(day,last,tzinfo=IST);delta=timedelta(minutes=minutes)
        while cursor+delta<=until:
            finish=cursor+delta;s=utc(cursor);e=utc(finish)
            blocked=any(utc(a.scheduled_start)<e and utc(a.scheduled_end)>s for a in booked)
            closed=any(datetime.combine(day,x.start_time,tzinfo=IST)<finish and datetime.combine(day,x.end_time,tzinfo=IST)>cursor for x in closures)
            if s>now() and not blocked and not closed: result[(s,e)]={"start":cursor.isoformat(),"end":finish.isoformat()}
            cursor=finish
    return [result[key] for key in sorted(result)]

def validate_slot(db,payload,exclude_id=None):
    day=payload.scheduled_start.astimezone(IST).date()
    slots=available_slots(db,doctor_id=payload.doctor_id,branch_id=payload.branch_id,day=day,exclude_id=exclude_id)
    if not any(utc(datetime.fromisoformat(s["start"]))==utc(payload.scheduled_start) and utc(datetime.fromisoformat(s["end"]))==utc(payload.scheduled_end) for s in slots):
        raise HTTPException(409,"This slot is no longer available or is outside the doctor's configured schedule. Refresh available slots")

def snapshot(item):
    return {key:str(getattr(item,key)) if getattr(item,key) is not None else None for key in ("branch_id","doctor_id","lead_id","patient_id","scheduled_start","scheduled_end","appointment_status_id","row_version")}

def audit(db,actor,item,action,before=None,reason=None):
    log_audit(db,organization_id=actor.organization_id,entity_type="APPOINTMENT",entity_id=item.appointment_id,action=action,actor_user_id=actor.user_id,before_data=before,after_data=snapshot(item),reason=reason)

def sync_lead(db,actor,item,lead,code,reason):
    if not lead: return
    current=db.get(LeadStatus,lead.lead_status_id)
    target=None
    if current.code=="CONVERTED":
        target=None
    elif code in {"SCHEDULED","RESCHEDULED"}: target="APPOINTMENT_BOOKED"
    elif code in {"CANCELLED","NO_SHOW"} and current.code=="APPOINTMENT_BOOKED":
        another=db.scalar(select(Appointment.appointment_id).join(AppointmentStatus,AppointmentStatus.appointment_status_id==Appointment.appointment_status_id).where(Appointment.lead_id==lead.lead_id,Appointment.appointment_id!=item.appointment_id,AppointmentStatus.code.not_in(TERMINAL)).limit(1))
        if not another: target="NO_SHOW" if code=="NO_SHOW" else "FOLLOW_UP_REQUIRED"
    if target:
        dest=db.scalar(select(LeadStatus).where(LeadStatus.code==target))
        if not dest: raise HTTPException(503,f"Lead status {target} is not configured")
        if lead.lead_status_id!=dest.lead_status_id:
            db.add(LeadStatusHistory(lead_id=lead.lead_id,old_status_id=lead.lead_status_id,new_status_id=dest.lead_status_id,changed_by=actor.user_id,changed_at=now(),reason=reason))
            lead.lead_status_id=dest.lead_status_id;lead.row_version+=1;lead.updated_by=actor.user_id
    db.add(LeadInteraction(lead_id=lead.lead_id,interaction_type="APPOINTMENT_"+code,channel="CLINIC",interaction_at=now(),performed_by_user_id=actor.user_id,summary=reason,metadata_json={"appointment_id":str(item.appointment_id)}))
    lead.last_interaction_at=now()
    # Even status-neutral attendance history changes invalidate a stale Lead screen.
    if not target or lead.lead_status_id==current.lead_status_id: lead.row_version+=1
    lead.updated_by=actor.user_id

def request_hash(payload):
    return hashlib.sha256(json.dumps(payload.model_dump(mode="json",exclude={"booking_request_id"}),sort_keys=True).encode()).hexdigest()

def retry_booking(db,actor,payload):
    if not payload.booking_request_id: return None
    found=db.scalar(select(Appointment).where(Appointment.organization_id==actor.organization_id,Appointment.created_by==actor.user_id,Appointment.booking_request_id==payload.booking_request_id))
    if found and found.booking_request_hash!=request_hash(payload): raise HTTPException(409,"Booking request was already used with different details. Review the existing appointment")
    if found: ensure_branch_access(db,actor,found.branch_id)
    return found

def book(db,actor,payload):
    if payload.organization_id!=actor.organization_id: raise HTTPException(403,"Cannot book for another organization")
    ensure_branch_access(db,actor,payload.branch_id)
    lock_doctors(db,actor,[payload.doctor_id])
    existing=retry_booking(db,actor,payload)
    if existing: return existing
    lead=lead_for(db,actor,payload.lead_id);require_open_lead(db,lead)
    if payload.patient_id:
        patient=db.get(Patient,payload.patient_id)
        if not patient or patient.organization_id!=actor.organization_id: raise HTTPException(404,"Patient not found")
    if payload.service_id:
        service=db.get(Service,payload.service_id)
        if not service or service.organization_id!=actor.organization_id or not service.active: raise HTTPException(422,"Select an active clinic service")
    if payload.appointment_status_id!=status(db,"SCHEDULED").appointment_status_id: raise HTTPException(422,"New appointments must start as Scheduled")
    validate_slot(db,payload)
    data=payload.model_dump();data["scheduled_start"]=utc(payload.scheduled_start);data["scheduled_end"]=utc(payload.scheduled_end)
    item=Appointment(**data,booking_request_hash=request_hash(payload),created_by=actor.user_id)
    db.add(item);db.flush()
    sync_lead(db,actor,item,lead,"SCHEDULED","Appointment booked")
    audit(db,actor,item,"APPOINTMENT_BOOKED")
    return item

def locked_appointment(db,actor,appointment_id,new_doctor=None):
    candidate=db.get(Appointment,appointment_id)
    if not candidate or candidate.organization_id!=actor.organization_id: raise HTTPException(404,"Appointment not found")
    old_doctor=candidate.doctor_id;old_lead=candidate.lead_id
    ensure_branch_access(db,actor,candidate.branch_id)
    lock_doctors(db,actor,[old_doctor,new_doctor])
    lead=lead_for(db,actor,old_lead)
    item=db.scalar(select(Appointment).where(Appointment.appointment_id==appointment_id).with_for_update().execution_options(populate_existing=True))
    if item.doctor_id!=old_doctor or item.lead_id!=old_lead: raise HTTPException(409,"Appointment changed. Reload before saving")
    ensure_branch_access(db,actor,item.branch_id)
    return item,lead

def check_version(item,version):
    if item.row_version!=version: raise HTTPException(409,"Appointment changed. Reload before saving")

def reschedule(db,actor,appointment_id,payload):
    item,lead=locked_appointment(db,actor,appointment_id,payload.doctor_id);check_version(item,payload.row_version)
    ensure_branch_access(db,actor,payload.branch_id)
    if db.get(AppointmentStatus,item.appointment_status_id).code not in {"SCHEDULED","CONFIRMED","RESCHEDULED","WAITLISTED"}: raise HTTPException(409,"Only appointments awaiting attendance can be rescheduled. Create a new appointment for a completed or closed encounter")
    require_open_lead(db,lead,allow_converted=bool(item.patient_id));validate_slot(db,payload,item.appointment_id)
    before=snapshot(item)
    for key,value in payload.model_dump(exclude={"row_version","reason"}).items(): setattr(item,key,utc(value) if key in {"scheduled_start","scheduled_end"} else value)
    item.appointment_status_id=status(db,"RESCHEDULED").appointment_status_id;item.row_version+=1
    sync_lead(db,actor,item,lead,"RESCHEDULED","Appointment rescheduled: "+payload.reason)
    audit(db,actor,item,"APPOINTMENT_RESCHEDULED",before,payload.reason)
    return item

def set_status(db,actor,appointment_id,code,version,reason=None):
    item,lead=locked_appointment(db,actor,appointment_id);check_version(item,version)
    current=db.get(AppointmentStatus,item.appointment_status_id).code
    if code==current: return item
    transitions={"SCHEDULED":{"CONFIRMED","CHECKED_IN","NO_SHOW","CANCELLED"},"CONFIRMED":{"CHECKED_IN","NO_SHOW","CANCELLED"},"RESCHEDULED":{"CONFIRMED","CHECKED_IN","NO_SHOW","CANCELLED"},"WAITLISTED":{"CONFIRMED","CANCELLED"},"CHECKED_IN":{"COMPLETED","CANCELLED"}}
    if code not in transitions.get(current,set()): raise HTTPException(409,"This attendance change is not allowed from the current status")
    if code in {"CANCELLED","NO_SHOW"} and (not reason or len(reason.strip())<3): raise HTTPException(422,"Enter a reason for cancellation or no-show")
    if code=="NO_SHOW" and utc(item.scheduled_start)>now(): raise HTTPException(409,"Cannot mark a future appointment as No Show")
    if code=="CHECKED_IN" and utc(item.scheduled_start).astimezone(IST).date()>now().astimezone(IST).date(): raise HTTPException(409,"Attendance can only be marked on the appointment date or later")
    before=snapshot(item);item.appointment_status_id=status(db,code).appointment_status_id;item.row_version+=1
    sync_lead(db,actor,item,lead,code,reason or ("Appointment "+code.lower().replace("_"," ")))
    audit(db,actor,item,"APPOINTMENT_"+code,before,reason)
    return item
