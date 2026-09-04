"use client";
import {FormEvent,useEffect,useMemo,useState} from "react";
import {apiFetch} from "../../lib/api";
import type {Appointment,Bootstrap,Lead} from "../../lib/types";

function dtLocal(v?:string|null){if(!v)return "—";return new Date(v).toLocaleString("en-IN",{dateStyle:"medium",timeStyle:"short"})}

export default function LeadsPage(){
  const [meta,setMeta]=useState<Bootstrap|null>(null);
  const [leads,setLeads]=useState<Lead[]>([]);
  const [selected,setSelected]=useState<Lead|null>(null);
  const [q,setQ]=useState("");
  const [error,setError]=useState("");
  const [showNew,setShowNew]=useState(false);
  const [showBooking,setShowBooking]=useState(false);
  const [form,setForm]=useState({lead_name:"",mobile:"",concern_text:"",lead_source_id:"",preferred_branch_id:"",nextfollowup_at:""});
  const [booking,setBooking]=useState({branch_id:"",doctor_id:"",date:"",slot_start:""});
  const [slots,setSlots]=useState<{start:string;end:string}[]>([]);
  const [previous,setPrevious]=useState<Lead[]>([]);

  const statusNew=useMemo(()=>meta?.lead_statuses.find(x=>x.code==="NEW"),[meta]);
  const scheduledStatus=useMemo(()=>meta?.appointment_statuses.find(x=>x.code==="SCHEDULED"),[meta]);

  async function loadLeads(search=q){
    const path=search?`/leads?q=${encodeURIComponent(search)}`:"/leads";
    setLeads(await apiFetch<Lead[]>(path));
  }
  useEffect(()=>{apiFetch<Bootstrap>("/meta/bootstrap").then(x=>{setMeta(x);setForm(f=>({...f,lead_source_id:x.lead_sources[0]?.id||"",preferred_branch_id:x.branches[0]?.id||""}));setBooking(b=>({...b,branch_id:x.branches[0]?.id||"",doctor_id:x.doctors[0]?.id||""}))}).catch(e=>setError(e.message));loadLeads().catch(e=>setError(e.message))},[]);

  async function findPrevious(){
    if(!form.mobile&&!form.lead_name){setPrevious([]);return}
    const params=new URLSearchParams();if(form.mobile)params.set("mobile",form.mobile);if(form.lead_name)params.set("name",form.lead_name);
    setPrevious(await apiFetch<Lead[]>(`/leads/search?${params.toString()}`));
  }

  async function createLead(e:FormEvent){
    e.preventDefault();if(!meta||!statusNew)return;setError("");
    try{
      await apiFetch("/leads",{method:"POST",body:JSON.stringify({organization_id:meta.organization_id,lead_name:form.lead_name,mobile:form.mobile,concern_text:form.concern_text||null,lead_source_id:form.lead_source_id,preferred_branch_id:form.preferred_branch_id||null,lead_status_id:statusNew.id,next_followup_at:form.nextfollowup_at?new Date(form.nextfollowup_at).toISOString():null})});
      setShowNew(false);setPrevious([]);setForm(f=>({...f,lead_name:"",mobile:"",concern_text:"",nextfollowup_at:""}));await loadLeads("");
    }catch(e){setError(e instanceof Error?e.message:"Unable to create Lead")}
  }

  async function toggleDnc(lead:Lead){
    const reason=lead.dnc?"DNC removed by reception":"Patient requested no outbound calls";
    await apiFetch(`/leads/${lead.lead_id}/dnc`,{method:"POST",body:JSON.stringify({dnc:!lead.dnc,reason})});await loadLeads();if(selected?.lead_id===lead.lead_id)setSelected({...lead,dnc:!lead.dnc});
  }
  async function reopen(lead:Lead){await apiFetch(`/leads/${lead.lead_id}/reopen`,{method:"POST"});await loadLeads();setSelected(null)}
  async function addFollowup(lead:Lead){
    const when=prompt("Next follow-up (example 2026-09-05T11:00)");if(!when)return;
    await apiFetch(`/leads/${lead.lead_id}/interactions`,{method:"POST",body:JSON.stringify({interaction_type:"FOLLOW_UP",channel:"PHONE",summary:"Follow-up scheduled",outcome:"CALL_BACK",next_followup_at:new Date(when).toISOString()})});await loadLeads();
  }
  async function loadSlots(next=booking){
    if(!next.branch_id||!next.doctor_id||!next.date){setSlots([]);return}
    const x=await apiFetch<{slots:{start:string;end:string}[]}>(`/appointments/availability?branch_id=${next.branch_id}&doctor_id=${next.doctor_id}&on_date=${next.date}`);
    setSlots(x.slots);
    setBooking(b=>({...b,slot_start:x.slots.some(s=>s.start===b.slot_start)?b.slot_start:(x.slots[0]?.start||"")}));
  }
  async function book(e:FormEvent){
    e.preventDefault();if(!meta||!selected||!scheduledStatus||!booking.slot_start)return;
    const slot=slots.find(x=>x.start===booking.slot_start);if(!slot)return;
    await apiFetch<Appointment>("/appointments",{method:"POST",body:JSON.stringify({organization_id:meta.organization_id,branch_id:booking.branch_id,doctor_id:booking.doctor_id||null,lead_id:selected.lead_id,patient_id:null,scheduled_start:slot.start,scheduled_end:slot.end,appointment_status_id:scheduledStatus.id,service_id:null,booked_via:"RECEPTION"})});
    setShowBooking(false);await loadLeads();
  }

  return <>
    <div className="header"><div><div className="eyebrow">LEAD REGISTER</div><h1 className="page-title">Leads</h1><div className="muted">Capture, follow up, reopen and book appointments without creating UHID.</div></div><button onClick={()=>setShowNew(true)}>+ New Lead</button></div>
    {error&&<div className="alert danger-box">{error}</div>}
    <div className="toolbar"><input placeholder="Search name or mobile" value={q} onChange={e=>setQ(e.target.value)} onKeyDown={e=>e.key==="Enter"&&loadLeads()}/><button className="secondary" onClick={()=>loadLeads()}>Search</button><button className="ghost" onClick={()=>{setQ("");loadLeads("")}}>Clear</button></div>
    <div className="table-wrap"><table><thead><tr><th>Lead</th><th>Concern</th><th>Source</th><th>Status</th><th>Follow-up</th><th>Actions</th></tr></thead><tbody>
      {leads.map(l=><tr key={l.lead_id}><td><b>{l.lead_name}</b><div className="muted">{l.mobile||"No mobile"}{l.dnc&&<span className="badge danger ml">DNC</span>}</div></td><td>{l.concern_text||"—"}</td><td>{l.source||"—"}</td><td><span className="badge">{l.status||"—"}</span></td><td>{dtLocal(l.next_followup_at)}</td><td><div className="row"><button className="small secondary" onClick={()=>setSelected(l)}>Open</button><button className="small secondary" disabled={l.dnc} onClick={()=>addFollowup(l)}>Follow-up</button></div></td></tr>)}
      {!leads.length&&<tr><td colSpan={6} className="empty">No Leads found.</td></tr>}
    </tbody></table></div>

    {showNew&&<div className="modal-backdrop"><div className="modal"><div className="modal-head"><h2>New Lead</h2><button className="icon" onClick={()=>setShowNew(false)}>×</button></div><form onSubmit={createLead} className="form-grid">
      <label>Name<input required value={form.lead_name} onChange={e=>setForm({...form,lead_name:e.target.value})} onBlur={findPrevious}/></label>
      <label>Mobile<input required value={form.mobile} onChange={e=>setForm({...form,mobile:e.target.value})} onBlur={findPrevious}/></label>
      <label className="span2">Concern<input value={form.concern_text} onChange={e=>setForm({...form,concern_text:e.target.value})}/></label>
      <label>Source<select required value={form.lead_source_id} onChange={e=>setForm({...form,lead_source_id:e.target.value})}>{meta?.lead_sources.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
      <label>Preferred branch<select value={form.preferred_branch_id} onChange={e=>setForm({...form,preferred_branch_id:e.target.value})}>{meta?.branches.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
      <label className="span2">Next follow-up<input type="datetime-local" value={form.nextfollowup_at} onChange={e=>setForm({...form,nextfollowup_at:e.target.value})}/></label>
      {!!previous.length&&<div className="span2 previous-box"><b>Previous inquiries found</b><p className="muted">Do not block a genuine new inquiry. Reopen the old Lead only when appropriate.</p>{previous.slice(0,5).map(x=><div className="previous-row" key={x.lead_id}><span>{x.lead_name} · {x.concern_text||"No concern"}</span><span className="badge">{x.status||"Previous"}</span></div>)}</div>}
      <div className="span2 row end"><button type="button" className="secondary" onClick={()=>setShowNew(false)}>Cancel</button><button>Create Lead</button></div>
    </form></div></div>}

    {selected&&<div className="drawer-backdrop" onClick={()=>setSelected(null)}><div className="drawer" onClick={e=>e.stopPropagation()}><div className="modal-head"><div><div className="eyebrow">LEAD</div><h2>{selected.lead_name}</h2></div><button className="icon" onClick={()=>setSelected(null)}>×</button></div>
      <div className="detail-grid"><div><span>Mobile</span><b>{selected.mobile||"—"}</b></div><div><span>Status</span><b>{selected.status}</b></div><div><span>Source</span><b>{selected.source}</b></div><div><span>Branch</span><b>{selected.preferred_branch||"—"}</b></div></div>
      <div className="card inset"><div className="muted">Concern</div><p>{selected.concern_text||"No concern recorded"}</p></div>
      <div className="action-stack">{selected.status_code!=="CONVERTED"&&<button onClick={()=>window.location.href=`/patients?lead=${selected.lead_id}`}>Convert / Check in Patient</button>}<button onClick={()=>{const next={...booking,date:booking.date||new Date().toISOString().slice(0,10)};setBooking(next);setShowBooking(true);setTimeout(()=>loadSlots(next),0)}}>Book appointment</button><button className="secondary" disabled={selected.dnc} onClick={()=>addFollowup(selected)}>Schedule follow-up</button>{["LOST","NO_SHOW"].includes(selected.status_code||"")&&<button className="secondary" onClick={()=>reopen(selected)}>Reopen Lead</button>}<button className={selected.dnc?"secondary":"danger-button"} onClick={()=>toggleDnc(selected)}>{selected.dnc?"Remove DNC":"Mark Do Not Call"}</button></div>
      {selected.dnc&&<div className="alert warning-box">Outbound calls, marketing exports, AI outbound calls and third-party calling assignments are blocked by the CRM.</div>}
    </div></div>}

    {showBooking&&selected&&<div className="modal-backdrop"><div className="modal narrow"><div className="modal-head"><h2>Book appointment</h2><button className="icon" onClick={()=>setShowBooking(false)}>×</button></div><form onSubmit={book} className="form-stack">
      <div className="patient-strip"><b>{selected.lead_name}</b><span>{selected.mobile}</span><span className="badge">Lead — no UHID</span></div>
      <label>Branch<select value={booking.branch_id} onChange={e=>{const next={...booking,branch_id:e.target.value,slot_start:""};setBooking(next);loadSlots(next)}}>{meta?.branches.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
      <label>Doctor<select value={booking.doctor_id} onChange={e=>{const next={...booking,doctor_id:e.target.value,slot_start:""};setBooking(next);loadSlots(next)}}>{meta?.doctors.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
      <label>Date<input required type="date" value={booking.date} onChange={e=>{const next={...booking,date:e.target.value,slot_start:""};setBooking(next);loadSlots(next)}}/></label>
      <label>Available slot<select required value={booking.slot_start} onChange={e=>setBooking({...booking,slot_start:e.target.value})}><option value="">Select a slot</option>{slots.map(x=><option key={x.start} value={x.start}>{new Date(x.start).toLocaleTimeString("en-IN",{hour:"2-digit",minute:"2-digit"})}</option>)}</select>{booking.date&&!slots.length&&<span className="muted">No configured slots available.</span>}</label>
      <div className="row end"><button type="button" className="secondary" onClick={()=>setShowBooking(false)}>Cancel</button><button>Confirm appointment</button></div>
    </form></div></div>}
  </>
}
