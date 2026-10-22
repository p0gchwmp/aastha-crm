"use client";
import {FormEvent,useEffect,useRef,useState} from 'react';
import {apiFetch} from '../lib/api';
import type {Appointment,Bootstrap,Patient,Visit} from '../lib/types';
export function indiaDate(){return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())}
export default function VisitRegistration({patientId,onClose,onSaved}:{patientId:string;onClose:()=>void;onSaved:(v:Visit)=>void}){
 const [patient,setPatient]=useState<Patient|null>(null),[meta,setMeta]=useState<Bootstrap|null>(null),[appts,setAppts]=useState<Appointment[]>([]);
 const [error,setError]=useState(''),[busy,setBusy]=useState(false),[confirmed,setConfirmed]=useState(false),[search,setSearch]=useState('');
 const [form,setForm]=useState({appointment_id:'',branch_id:'',doctor_id:'',visit_type_id:'',chief_complaint_ids:[] as string[]});
 const request=useRef(crypto.randomUUID()),saving=useRef(false);
 useEffect(()=>{let active=true;Promise.all([apiFetch<Patient>(`/patients/${patientId}`),apiFetch<Bootstrap>('/meta/bootstrap'),apiFetch<Appointment[]>(`/appointments?patient_id=${patientId}&on_date=${indiaDate()}`)]).then(([p,m,a])=>{
  if(!active)return;setPatient(p);setMeta(m);setAppts(a.filter(x=>['SCHEDULED','CONFIRMED','RESCHEDULED','CHECKED_IN','COMPLETED'].includes(x.status_code||'')));
  setForm(f=>({...f,branch_id:m.branches.some(x=>x.id===p.registration_branch_id)?p.registration_branch_id:m.branches[0]?.id||'',visit_type_id:m.visit_types.find(x=>x.code==='CONSULTATION')?.id||m.visit_types[0]?.id||''}));
 }).catch(e=>active&&setError(e.message));return()=>{active=false}},[patientId]);
 function change(next:typeof form){setForm(next);request.current=crypto.randomUUID();setError('')}
 async function save(e:FormEvent){e.preventDefault();if(saving.current||!confirmed||!patient)return;saving.current=true;setBusy(true);setError('');
  try{const a=appts.find(x=>x.appointment_id===form.appointment_id);const v=await apiFetch<Visit>('/visits',{method:'POST',body:JSON.stringify({...form,appointment_id:form.appointment_id||null,appointment_row_version:a?.row_version||null,doctor_id:form.doctor_id||null,patient_id:patient.patient_id,patient_row_version:patient.row_version,creation_request_id:request.current,identity_confirmed:true})});onSaved(v)}
  catch(e){setError((e instanceof Error?e.message:'Save could not be confirmed')+'. If the response was interrupted, retry with the same details or check Visit history before starting again.')}
  finally{saving.current=false;setBusy(false)}
 }
 async function propose(){const name=window.prompt('Enter new Chief Complaint');if(!name?.trim())return;setBusy(true);
  try{const c=await apiFetch<{chief_complaint_id:string;name:string}>('/masters/chief-complaints',{method:'POST',body:JSON.stringify({name:name.trim()})});setMeta(m=>m?({...m,chief_complaints:[...m.chief_complaints.filter(x=>x.id!==c.chief_complaint_id),{id:c.chief_complaint_id,name:c.name}]}):m);change({...form,chief_complaint_ids:Array.from(new Set([...form.chief_complaint_ids,c.chief_complaint_id]))});setSearch('')}
  catch(e){setError(e instanceof Error?e.message:'Could not propose complaint')}finally{setBusy(false)}
 }
 return <div className="modal-backdrop"><div className="modal" role="dialog" aria-modal="true" aria-label="New Visit"><div className="modal-head"><h2>Confirm Patient & Create Visit</h2><button className="icon" aria-label="Close New Visit" disabled={busy} onClick={onClose}>×</button></div>
 {error&&<div role="alert" className="alert danger-box">{error}</div>}
 {!patient||!meta?<p>Loading verified Patient details…</p>:<>
 <div className="confirm-patient"><div className="confirm-name">{patient.full_name}</div><div>{patient.age??'Age not recorded'}{patient.age!=null?' years':''}{patient.age_is_estimated?' (approx.)':''} · {patient.gender||'Gender not recorded'}</div><div className="confirm-uhid">UHID: {patient.uhid}</div></div>
 <p className="muted">The same UHID is retained. Each saved Visit gets its own Visit ID. Appointment attendance is managed separately.</p>
 <form onSubmit={save}><fieldset disabled={busy} style={{border:0,padding:0}}>
 <label className="checkline identity-check"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>I confirmed Name + Age/Gender + UHID for the correct Patient.</label>
 <div className="form-grid" style={{marginTop:16}}>
 <label>Today's appointment<select aria-label="Today's appointment" value={form.appointment_id} onChange={e=>{const a=appts.find(x=>x.appointment_id===e.target.value);change({...form,appointment_id:e.target.value,branch_id:a?.branch_id||form.branch_id,doctor_id:a?.doctor_id||form.doctor_id})}}><option value="">Walk-in / no appointment</option>{appts.map(a=><option key={a.appointment_id} value={a.appointment_id}>{new Date(a.scheduled_start).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit'})} · {a.branch} · {a.doctor} · {a.status}</option>)}</select></label>
 <label>Branch<select aria-label="Branch" required disabled={!!form.appointment_id} value={form.branch_id} onChange={e=>change({...form,branch_id:e.target.value})}>{meta.branches.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
 <label>Doctor<select aria-label="Doctor" disabled={!!form.appointment_id} value={form.doctor_id} onChange={e=>change({...form,doctor_id:e.target.value})}><option value="">Unassigned</option>{meta.doctors.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
 <label>Visit type<select aria-label="Visit type" required value={form.visit_type_id} onChange={e=>change({...form,visit_type_id:e.target.value})}>{meta.visit_types.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
 <label className="span2">Search chief complaints<input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search chief complaints"/></label>
 <div className="span2"><div className="chip-grid">{meta.chief_complaints.filter(x=>x.name.toLowerCase().includes(search.toLowerCase())||form.chief_complaint_ids.includes(x.id)).map(x=><button type="button" aria-pressed={form.chief_complaint_ids.includes(x.id)} className={form.chief_complaint_ids.includes(x.id)?'chip selected':'chip'} key={x.id} onClick={()=>change({...form,chief_complaint_ids:form.chief_complaint_ids.includes(x.id)?form.chief_complaint_ids.filter(id=>id!==x.id):[...form.chief_complaint_ids,x.id]})}>{x.name}</button>)}<button type="button" className="chip" onClick={propose}>+ Propose complaint</button></div><p className="muted">Multiple complaints are allowed. A proposed complaint can be used while awaiting review. Report Check needs no mandatory reason.</p></div>
 <div className="span2 row end"><button type="button" className="secondary" onClick={onClose}>Cancel</button><button disabled={!confirmed||busy}>{busy?'Saving…':'Create Visit'}</button></div>
 </div></fieldset></form></>}
 </div></div>
}
