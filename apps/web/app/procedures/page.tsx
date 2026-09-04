"use client";
import {useCallback,useEffect,useMemo,useState} from "react";
import {apiFetch} from "../../lib/api";
import type {Bootstrap,ProcedureOrder,ProcedureSetup,Visit} from "../../lib/types";

type Me={name:string;roles:string[];permissions:string[]};
function fmt(v?:string|null){return v?new Date(v).toLocaleString("en-IN",{timeZone:"Asia/Kolkata",dateStyle:"medium",timeStyle:"short"}):"—"}
function today(){return new Date().toLocaleDateString("en-CA",{timeZone:"Asia/Kolkata"})}

export default function ProceduresPage(){
  const [me,setMe]=useState<Me|null>(null);
  const [meta,setMeta]=useState<Bootstrap|null>(null);
  const [setup,setSetup]=useState<ProcedureSetup|null>(null);
  const [orders,setOrders]=useState<ProcedureOrder[]>([]);
  const [visits,setVisits]=useState<Visit[]>([]);
  const [visitId,setVisitId]=useState("");
  const [serviceId,setServiceId]=useState("");
  const [notes,setNotes]=useState("");
  const [sessionVisit,setSessionVisit]=useState<Record<string,string>>({});
  const [busy,setBusy]=useState("");
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");

  const canOrder=!!me?.permissions.includes("PROCEDURE_ORDER_CREATE");
  const canExecute=!!me?.permissions.includes("PROCEDURE_EXECUTE");

  const load=useCallback(async()=>{
    setError("");
    try{
      const [m,b,s,o,v]=await Promise.all([
        apiFetch<Me>("/auth/me"),
        apiFetch<Bootstrap>("/meta/bootstrap"),
        apiFetch<ProcedureSetup>("/procedures/setup"),
        apiFetch<ProcedureOrder[]>("/procedures/orders"),
        apiFetch<Visit[]>(`/visits?on_date=${today()}&limit=250`),
      ]);
      setMe(m);setMeta(b);setSetup(s);setOrders(o);setVisits(v);
      if(!serviceId&&s.services[0])setServiceId(s.services[0].id);
    }catch(e:any){setError(e.message||"Unable to load Procedures")}
  },[serviceId]);
  useEffect(()=>{load()},[]);

  const eligibleVisits=useMemo(()=>visits.filter(v=>!!v.doctor_id),[visits]);
  const act=async(key:string,fn:()=>Promise<unknown>,message:string)=>{
    setBusy(key);setError("");setNotice("");
    try{await fn();setNotice(message);await load()}catch(e:any){setError(e.message||"Action failed")}finally{setBusy("")}
  };

  const createOrder=()=>{
    if(!visitId||!serviceId){setError("Select a Visit and Procedure service");return}
    return act("create",()=>apiFetch("/procedures/orders",{method:"POST",body:JSON.stringify({visit_id:visitId,service_id:serviceId,notes:notes||null})}),"Procedure Order created and sent to the integration outbox.");
  };

  const planExecution=(order:ProcedureOrder)=>{
    const performedVisitId=sessionVisit[order.procedure_order_id];
    if(!performedVisitId){setError("Create/select today's Procedure Visit for this patient before starting a session.");return}
    const visit=visits.find(v=>v.visit_id===performedVisitId);
    const branchId=visit?.branch_id||order.ordering_branch_id;
    return act(`plan-${order.procedure_order_id}`,()=>apiFetch(`/procedures/orders/${order.procedure_order_id}/executions`,{method:"POST",body:JSON.stringify({rendering_branch_id:branchId,performed_visit_id:performedVisitId,clinical_notes:null})}),"Procedure session created and linked to today's Procedure Visit.");
  };
  const startExecution=(executionId:string,rowVersion:number)=>act(`start-${executionId}`,()=>apiFetch(`/procedures/executions/${executionId}/start?row_version=${rowVersion}`,{method:"POST"}),"Procedure session started.");
  const completeExecution=(executionId:string,rowVersion:number)=>act(`complete-${executionId}`,()=>apiFetch(`/procedures/executions/${executionId}/complete`,{method:"POST",body:JSON.stringify({row_version:rowVersion,clinical_notes:null})}),"Procedure completed. Inventory event queued.");

  const cancelOrder=(order:ProcedureOrder)=>{
    const reason=window.prompt("Reason for cancelling this Procedure Order?");
    if(!reason?.trim())return;
    return act(`cancel-${order.procedure_order_id}`,()=>apiFetch(`/procedures/orders/${order.procedure_order_id}/cancel`,{method:"POST",body:JSON.stringify({row_version:order.row_version,reason:reason.trim()})}),"Procedure Order cancelled and Finance notified.");
  };

  return <>
    <div className="header"><div><div className="eyebrow">CLINICAL PROCEDURES</div><h1 className="page-title">Procedure Orders & Sessions</h1><div className="muted">Clinical CRM owns the order/session. External Procedure Finance owns money. Inventory consumes only after completion.</div></div><button onClick={load}>Refresh</button></div>
    {error&&<div className="alert danger-box">{error}</div>}{notice&&<div className="alert success-box">{notice}</div>}

    {canOrder&&<div className="card" style={{marginTop:18}}><h3>Create Procedure Order</h3><div className="muted">Doctor action. No procedure price is stored here.</div><div className="form-grid" style={{marginTop:12}}>
      <label>Today&apos;s Visit<select value={visitId} onChange={e=>setVisitId(e.target.value)}><option value="">Select Visit</option>{eligibleVisits.map(v=><option key={v.visit_id} value={v.visit_id}>{v.patient_name} • {v.uhid} • {v.visit_type} • {v.branch}</option>)}</select></label>
      <label>Procedure<select value={serviceId} onChange={e=>setServiceId(e.target.value)}><option value="">Select Procedure</option>{setup?.services.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
      <label style={{gridColumn:"1/-1"}}>Clinical order note<input value={notes} onChange={e=>setNotes(e.target.value)} placeholder="Optional note"/></label>
    </div><button onClick={createOrder} disabled={busy==="create"}>{busy==="create"?"Creating…":"Create Procedure Order"}</button></div>}

    <div className="header" style={{marginTop:24}}><div><h2>Procedure Orders</h2><div className="muted">A session may proceed only when Finance returns CLEARED or COMPLIMENTARY.</div></div></div>
    <div className="stack">
      {!orders.length&&<div className="card muted">No Procedure Orders yet.</div>}
      {orders.map(o=>{
        const ready=setup?.ready_financial_statuses.includes(o.financial_status);
        return <div className="card" key={o.procedure_order_id}>
          <div className="header"><div><h3>{o.patient_name} <span className="muted">• {o.uhid}</span></h3><div className="muted">{o.service_name} • Ordered by {o.doctor} • {o.ordering_branch} • {fmt(o.ordered_at)}</div></div><div><span className={`status-chip ${ready?"good":""}`}>{o.financial_status.replace(/_/g," ")}</span></div></div>
          <div className="muted">Order status: <b>{o.order_status?.replace(/_/g," ")}</b>{o.external_reference?` • Finance ref: ${o.external_reference}`:""}</div>
          {canExecute&&ready&&(()=>{const pv=visits.filter(v=>v.patient_id===o.patient_id&&v.visit_type_code==="PROCEDURE");return <div className="toolbar" style={{marginTop:12}}><select value={sessionVisit[o.procedure_order_id]||""} onChange={e=>setSessionVisit(x=>({...x,[o.procedure_order_id]:e.target.value}))}><option value="">Select today's Procedure Visit</option>{pv.map(v=><option key={v.visit_id} value={v.visit_id}>{v.branch} • {fmt(v.checkin_at)}</option>)}</select><button onClick={()=>planExecution(o)} disabled={busy===`plan-${o.procedure_order_id}`||!pv.length}>Create Session</button>{!pv.length&&<span className="warning-text">Create a Procedure Visit for this patient first.</span>}</div>})()}
          {!ready&&<div className="info-strip" style={{marginTop:12}}>Procedure session locked until external Finance sends CLEARED or COMPLIMENTARY.</div>}
          {!!o.executions.length&&<div className="table-wrap" style={{marginTop:14}}><table><thead><tr><th>Session</th><th>Rendering Branch</th><th>Status</th><th>Started</th><th>Completed</th><th>Action</th></tr></thead><tbody>{o.executions.map((x,i)=><tr key={x.procedure_execution_id}><td>#{i+1}</td><td>{x.rendering_branch}</td><td><span className="badge">{x.status}</span></td><td>{fmt(x.started_at)}</td><td>{fmt(x.completed_at)}</td><td>{canExecute&&x.status==="PLANNED"&&<button className="small" onClick={()=>startExecution(x.procedure_execution_id,x.row_version)}>Start</button>}{canExecute&&x.status==="IN_PROGRESS"&&<button className="small" onClick={()=>completeExecution(x.procedure_execution_id,x.row_version)}>Complete</button>}{x.status==="COMPLETED"&&<span className="muted">Inventory event queued</span>}</td></tr>)}</tbody></table></div>}
          {canExecute&&o.order_status==="PARTIALLY_COMPLETED"&&<button className="secondary" style={{marginTop:12}} onClick={()=>act(`close-${o.procedure_order_id}`,()=>apiFetch(`/procedures/orders/${o.procedure_order_id}/close?row_version=${o.row_version}`,{method:"POST"}),"Procedure Order closed.")}>Close Procedure Order</button>}
          {canOrder&&!o.executions.length&&!['COMPLETED','CANCELLED'].includes(o.order_status||'')&&<button className="ghost" style={{marginTop:12,marginLeft:8}} onClick={()=>cancelOrder(o)}>Cancel Order</button>}
        </div>
      })}
    </div>

    <div className="card" style={{marginTop:22}}><h3>External system contract</h3><div className="muted">Procedure Finance reads the Procedure Order and posts only its financial status back. Inventory reads procedure-completion events containing service + rendering branch; patient identity is not included in inventory payloads.</div><pre style={{whiteSpace:"pre-wrap"}}>{`Finance: GET /api/v1/external/procedures/orders/{order_id}\nFinance callback: POST /api/v1/external/procedures/orders/{order_id}/financial-status\nInventory: GET /api/v1/external/procedures/inventory-events\nHeader: X-Integration-Key`}</pre></div>
  </>;
}
