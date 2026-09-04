"use client";
import {useEffect,useState} from "react";
import {apiFetch} from "../../lib/api";
import type {Bootstrap,Visit} from "../../lib/types";

function d(v:string){return new Date(v).toLocaleString("en-IN",{dateStyle:"medium",timeStyle:"short"})}

export default function VisitsPage(){
  const [meta,setMeta]=useState<Bootstrap|null>(null);const [rows,setRows]=useState<Visit[]>([]);const [date,setDate]=useState(new Date().toISOString().slice(0,10));const [branch,setBranch]=useState("");const [error,setError]=useState("");
  async function load(nextDate=date,nextBranch=branch){const p=new URLSearchParams();p.set("on_date",nextDate);if(nextBranch)p.set("branch_id",nextBranch);setRows(await apiFetch<Visit[]>(`/visits?${p.toString()}`))}
  useEffect(()=>{apiFetch<Bootstrap>("/meta/bootstrap").then(setMeta).catch(e=>setError(e.message));load().catch(e=>setError(e.message))},[]);
  return <><div className="header"><div><div className="eyebrow">VISIT REGISTER</div><h1 className="page-title">Visits</h1><div className="muted">Every clinic attendance is a separate Visit linked to the permanent UHID.</div></div><button onClick={()=>window.location.href="/patients"}>Find Patient / New Visit</button></div>
  {error&&<div className="alert danger-box">{error}</div>}
  <div className="toolbar"><input type="date" value={date} onChange={e=>setDate(e.target.value)}/><select value={branch} onChange={e=>setBranch(e.target.value)}><option value="">All branches</option>{meta?.branches.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select><button className="secondary" onClick={()=>load()}>Apply</button></div>
  <div className="table-wrap"><table><thead><tr><th>Check-in</th><th>Patient</th><th>Visit</th><th>Doctor</th><th>Branch</th><th>Status</th></tr></thead><tbody>{rows.map(v=><tr key={v.visit_id}><td>{d(v.checkin_at)}</td><td><b>{v.patient_name||"—"}</b><div className="muted">{v.uhid}</div></td><td><b>{v.visit_type||"—"}</b><div className="muted">{(v.complaints||[]).map(x=>x.name).join(", ")||"No complaint selected"}</div></td><td>{v.doctor||"—"}</td><td>{v.branch||"—"}</td><td><span className="badge">{v.status||"—"}</span></td></tr>)}{!rows.length&&<tr><td className="empty" colSpan={6}>No Visits for this date.</td></tr>}</tbody></table></div></>
}
