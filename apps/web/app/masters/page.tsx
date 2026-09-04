"use client";
import {useEffect,useState} from "react";
import {apiFetch} from "../../lib/api";
import type {Bootstrap,PendingMaster} from "../../lib/types";

export default function MastersPage(){
  const [rows,setRows]=useState<PendingMaster[]>([]);const [meta,setMeta]=useState<Bootstrap|null>(null);const [error,setError]=useState("");const [notice,setNotice]=useState("");
  const load=async()=>{try{setError("");const [r,m]=await Promise.all([apiFetch<PendingMaster[]>("/masters/pending"),apiFetch<Bootstrap>("/meta/bootstrap")]);setRows(r);setMeta(m)}catch(e){setError(e instanceof Error?e.message:"Unable to load approvals")}};
  useEffect(()=>{load()},[]);
  async function resolve(row:PendingMaster,action:string){
    let corrected_name:string|undefined;let merge_into_id:string|undefined;
    if(action==="CORRECT"){corrected_name=window.prompt("Correct name",row.name)||undefined;if(!corrected_name)return}
    if(action==="MERGE"){
      const options=row.master_type==="LOCALITY"?meta?.localities.filter(x=>x.approval_status==="APPROVED"&&x.district_id===row.parent_id):meta?.chief_complaints;
      const text=(options||[]).map(x=>`${x.id}  ${x.name}`).join("\n");merge_into_id=window.prompt(`Paste target ID:\n${text}`)||undefined;if(!merge_into_id)return;
    }
    const path=row.master_type==="LOCALITY"?`/masters/localities/${row.id}/resolve`:`/masters/chief-complaints/${row.id}/resolve`;
    try{await apiFetch(path,{method:"POST",body:JSON.stringify({action,corrected_name:corrected_name||null,merge_into_id:merge_into_id||null,reason:null})});setNotice(`${row.name}: ${action.toLowerCase()} completed.`);await load()}catch(e){setError(e instanceof Error?e.message:"Approval failed")}
  }
  return <>
    <div className="header"><div><div className="eyebrow">MAKER → CHECKER</div><h1 className="page-title">Master Approvals</h1><div className="muted">Patient registration and Visits continue while proposed Localities/Chief Complaints wait here for cleanup.</div></div><button onClick={load}>Refresh</button></div>
    {error&&<div className="alert danger-box">{error}</div>}{notice&&<div className="alert success-box">{notice}</div>}
    <div className="table-wrap"><table><thead><tr><th>Type</th><th>Proposed value</th><th>Maker</th><th>Usage</th><th>Actions</th></tr></thead><tbody>
      {rows.length===0&&<tr><td colSpan={5} className="empty">No pending master approvals.</td></tr>}
      {rows.map(r=><tr key={`${r.master_type}-${r.id}`}><td><span className="badge">{r.master_type.replace(/_/g," ")}</span></td><td><b>{r.name}</b><div className="muted">{r.created_at?new Date(r.created_at).toLocaleString("en-IN"):"—"}</div></td><td>{r.created_by_name||"—"}</td><td>{r.usage_count} linked record(s)</td><td><div className="row"><button className="small" onClick={()=>resolve(r,"APPROVE")}>Approve</button><button className="small secondary" onClick={()=>resolve(r,"CORRECT")}>Correct</button><button className="small ghost" onClick={()=>resolve(r,"MERGE")}>Merge</button><button className="small danger-button" onClick={()=>resolve(r,"REJECT")}>Reject</button></div></td></tr>)}
    </tbody></table></div>
  </>
}
