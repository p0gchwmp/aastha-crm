"use client";
import {useEffect,useState} from "react";
import {apiFetch} from "../../lib/api";
import type {Appointment,Bootstrap} from "../../lib/types";

function t(v:string){return new Date(v).toLocaleTimeString("en-IN",{hour:"2-digit",minute:"2-digit"})}
export default function Appointments(){
  const [meta,setMeta]=useState<Bootstrap|null>(null);const [rows,setRows]=useState<Appointment[]>([]);const [date,setDate]=useState(new Date().toISOString().slice(0,10));const [error,setError]=useState("");
  async function load(d=date){setRows(await apiFetch<Appointment[]>(`/appointments?on_date=${d}`))}
  useEffect(()=>{apiFetch<Bootstrap>("/meta/bootstrap").then(setMeta);load().catch(e=>setError(e.message))},[]);
  async function status(row:Appointment,code:string){await apiFetch(`/appointments/${row.appointment_id}/status?status_code=${code}&row_version=${row.row_version}`,{method:"PATCH"});await load()}
  return <><div className="header"><div><div className="eyebrow">SCHEDULING</div><h1 className="page-title">Appointments</h1><div className="muted">Appointments can belong to a Lead or an existing Patient. Booking alone never creates UHID.</div></div><input type="date" value={date} onChange={e=>{setDate(e.target.value);load(e.target.value)}}/></div>
  {error&&<div className="alert danger-box">{error}</div>}
  <div className="card"><div className="timeline">{rows.map(x=><div className="appt" key={x.appointment_id}><div className="appt-time">{t(x.scheduled_start)}</div><div className="appt-main"><b>{x.lead_name||"Registered patient"}</b><span>{x.doctor||"Doctor unassigned"} · {x.branch}</span><span className="muted">Booked via {x.booked_via}</span></div><span className="badge">{x.status}</span><div className="appt-actions">{x.lead_id&&!x.patient_id&&<button className="small" onClick={()=>window.location.href=`/patients?lead=${x.lead_id}`}>Check in</button>}{x.patient_id&&<button className="small" onClick={()=>window.location.href=`/patients?patient=${x.patient_id}`}>Patient</button>}{x.status_code!=="CONFIRMED"&&<button className="small secondary" onClick={()=>status(x,"CONFIRMED")}>Confirm</button>}{!['CANCELLED','COMPLETED'].includes(x.status_code||"")&&<button className="small ghost" onClick={()=>status(x,"CANCELLED")}>Cancel</button>}</div></div>)}{!rows.length&&<div className="empty">No appointments for this date.</div>}</div></div>
  <div className="card" style={{marginTop:16}}><b>Doctor availability foundation</b><p className="muted">{meta?.doctors.length||0} active doctor(s) and {meta?.branches.length||0} branch(es) loaded from configurable masters. Slot availability APIs can be used unchanged by Reception, WhatsApp AI and Voice AI.</p></div></>
}
