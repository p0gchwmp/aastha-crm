"use client";
import {useEffect,useState} from "react";
import Link from "next/link";
import {apiFetch} from "../lib/api";

type Summary={leads_today:number;appointments_today:number;visits_today:number;consultation_collection:string;followups_due:number};
export default function Dashboard(){
  const [data,setData]=useState<Summary|null>(null);
  const [error,setError]=useState("");
  useEffect(()=>{apiFetch<Summary>("/dashboard/summary").then(setData).catch(e=>setError(e.message))},[]);
  return <>
    <div className="header"><div><div className="eyebrow">TODAY</div><h1 className="page-title">Reception Dashboard</h1><div className="muted">Live operational overview</div></div><Link className="button-link" href="/leads?new=1">+ New Lead</Link></div>
    {error&&<div className="alert danger-box">{error}</div>}
    <div className="grid">
      <div className="card"><div className="muted">Leads today</div><div className="kpi">{data?.leads_today ?? "—"}</div></div>
      <div className="card"><div className="muted">Appointments today</div><div className="kpi">{data?.appointments_today ?? "—"}</div></div>
      <div className="card"><div className="muted">Follow-ups due</div><div className="kpi">{data?.followups_due ?? "—"}</div></div>
      <div className="card"><div className="muted">Consultation collection</div><div className="kpi">₹{data?.consultation_collection ?? "—"}</div></div>
    </div>
    <div className="section-grid">
      <div className="card"><h3>Reception flow</h3><div className="flow-line"><span>Lead</span><b>→</b><span>Appointment</span><b>→</b><span>Patient</span><b>→</b><span>Visit</span></div><p className="muted">Appointments never generate UHID. Patient registration remains a verified internal action.</p></div>
      <div className="card"><h3>Built-in safeguards</h3><ul className="compact-list"><li>DNC blocked at outbound boundaries</li><li>Shared mobile never auto-selects a patient</li><li>Optimistic locking prevents silent overwrites</li><li>Business numbers allocated atomically</li></ul></div>
    </div>
  </>
}
