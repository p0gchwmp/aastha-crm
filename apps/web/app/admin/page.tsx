"use client";
import {useEffect,useState} from "react";
import {apiFetch} from "../../lib/api";
import type {AuditEvent} from "../../lib/types";

export default function AdminPage(){
 const [rows,setRows]=useState<AuditEvent[]>([]);const [changes,setChanges]=useState<any[]>([]);const [error,setError]=useState("");
 const load=async()=>{try{const [a,c]=await Promise.all([apiFetch<AuditEvent[]>("/admin/audit?limit=300"),apiFetch<any[]>("/admin/financial-change-requests")]);setRows(a);setChanges(c)}catch(e){setError(e instanceof Error?e.message:"Unable to load Admin controls")}};
 useEffect(()=>{load()},[]);
 async function resolve(id:string,approve:boolean){const reason=window.prompt(approve?"Approval reason":"Rejection reason")||null;try{await apiFetch(`/consultation-finance/change-requests/${id}/resolve`,{method:"POST",body:JSON.stringify({approve,reason})});await load()}catch(e){setError(e instanceof Error?e.message:"Resolution failed")}}
 return <><div className="header"><div><div className="eyebrow">CONTROL & TRACEABILITY</div><h1 className="page-title">Admin Audit</h1><div className="muted">Focused Phase 1 audit for financial and high-impact master/import actions.</div></div><button onClick={load}>Refresh</button></div>{error&&<div className="alert danger-box">{error}</div>}
 <div className="card"><h3>Financial correction requests</h3>{changes.length===0?<div className="muted">No change requests.</div>:changes.map(c=><div className="visit-history" key={c.change_request_id}><div><b>{c.entity_type}</b><div className="muted">{c.status} • Requested by {c.requested_by_name||c.requested_by}</div><div className="muted">{JSON.stringify(c.requested_change)}</div></div>{c.status==="PENDING"&&<div className="row"><button className="small" onClick={()=>resolve(c.change_request_id,true)}>Approve</button><button className="small danger-button" onClick={()=>resolve(c.change_request_id,false)}>Reject</button></div>}</div>)}</div>
 <div className="card" style={{marginTop:16}}><h3>Audit events</h3><div className="table-wrap"><table><thead><tr><th>When</th><th>Action</th><th>Entity</th><th>User</th><th>Reason / change</th></tr></thead><tbody>{rows.map(r=><tr key={r.audit_event_id}><td>{new Date(r.occurred_at).toLocaleString("en-IN")}</td><td><span className="badge">{r.action}</span></td><td>{r.entity_type}<div className="muted">{r.entity_id}</div></td><td>{r.actor_name||"System/Integration"}</td><td>{r.reason||JSON.stringify(r.after_data||{})}</td></tr>)}</tbody></table></div></div></>
}
