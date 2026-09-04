"use client";
import {useCallback,useEffect,useMemo,useState} from "react";
import {apiFetch} from "../../lib/api";
import type {Bootstrap,ConsultationBill,ConsultationPayment,DailyFinance,FinanceDecision,FinanceSetup,Visit} from "../../lib/types";

type Me={name:string;roles:string[];permissions:string[]};

function today(){return new Date().toLocaleDateString("en-CA",{timeZone:"Asia/Kolkata"})}
function money(x?:string|null){return `₹${Number(x||0).toLocaleString("en-IN",{minimumFractionDigits:2,maximumFractionDigits:2})}`}
function fmtDateTime(x?:string|null){if(!x)return "—";return new Date(x).toLocaleString("en-IN",{timeZone:"Asia/Kolkata",dateStyle:"medium",timeStyle:"short"})}

export default function Finance(){
  const [bootstrap,setBootstrap]=useState<Bootstrap|null>(null);
  const [setup,setSetup]=useState<FinanceSetup|null>(null);
  const [me,setMe]=useState<Me|null>(null);
  const [visits,setVisits]=useState<Visit[]>([]);
  const [decisions,setDecisions]=useState<Record<string,FinanceDecision>>({});
  const [report,setReport]=useState<DailyFinance|null>(null);
  const [onDate,setOnDate]=useState(today());
  const [branchId,setBranchId]=useState("");
  const [doctorId,setDoctorId]=useState("");
  const [busy,setBusy]=useState<string|null>(null);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [paymentMode,setPaymentMode]=useState<Record<string,string>>({});
  const [paymentAmount,setPaymentAmount]=useState<Record<string,string>>({});
  const [feeAmount,setFeeAmount]=useState("");
  const [feeBranch,setFeeBranch]=useState("");
  const [feeDoctor,setFeeDoctor]=useState("");
  const [feeDate,setFeeDate]=useState(today());

  const canCorrect=!!me?.permissions.includes("FINANCE_CORRECT");
  const canBill=!!me?.permissions.includes("CONSULTATION_BILL_CREATE");
  const canPay=!!me?.permissions.includes("CONSULTATION_PAYMENT_CREATE");
  const canComplimentary=!!me?.permissions.includes("CONSULTATION_COMPLIMENTARY");
  const consultService=bootstrap?.services.find(x=>x.code==="CONSULT");

  const load=useCallback(async()=>{
    setError("");
    try{
      const [b,s,m]=await Promise.all([
        apiFetch<Bootstrap>("/meta/bootstrap"),
        apiFetch<FinanceSetup>("/consultation-finance/setup"),
        apiFetch<Me>("/auth/me"),
      ]);
      setBootstrap(b);setSetup(s);setMe(m);
      const q=new URLSearchParams({on_date:onDate});
      if(branchId)q.set("branch_id",branchId);
      const all=await apiFetch<Visit[]>(`/visits?${q}`);
      const financeVisits=all.filter(v=>["CONSULTATION","FOLLOW_UP"].includes(v.visit_type_code||""));
      setVisits(financeVisits);
      const pairs=await Promise.all(financeVisits.map(async v=>[v.visit_id,await apiFetch<FinanceDecision>(`/consultation-finance/visits/${v.visit_id}/decision`)] as const));
      setDecisions(Object.fromEntries(pairs));
      const rq=new URLSearchParams({on_date:onDate});
      if(branchId)rq.set("branch_id",branchId);
      if(doctorId)rq.set("doctor_id",doctorId);
      setReport(await apiFetch<DailyFinance>(`/consultation-finance/reports/daily?${rq}`));
    }catch(e:any){setError(e.message||"Unable to load Consultation Finance")}
  },[onDate,branchId,doctorId]);

  useEffect(()=>{load()},[load]);

  const refreshDecision=async(visitId:string)=>{
    const d=await apiFetch<FinanceDecision>(`/consultation-finance/visits/${visitId}/decision`);
    setDecisions(x=>({...x,[visitId]:d}));
    const rq=new URLSearchParams({on_date:onDate});if(branchId)rq.set("branch_id",branchId);if(doctorId)rq.set("doctor_id",doctorId);
    setReport(await apiFetch<DailyFinance>(`/consultation-finance/reports/daily?${rq}`));
  };

  const act=async(key:string,fn:()=>Promise<any>,message:string,visitId?:string)=>{
    setBusy(key);setError("");setNotice("");
    try{await fn();setNotice(message);if(visitId)await refreshDecision(visitId);else await load()}
    catch(e:any){setError(e.message||"Action failed")}
    finally{setBusy(null)}
  };

  const createBill=(visitId:string)=>act(`bill-${visitId}`,()=>apiFetch<ConsultationBill>("/consultation-finance/bills/from-visit",{method:"POST",body:JSON.stringify({visit_id:visitId})}),"Consultation bill draft created.",visitId);
  const finalizeBill=(visitId:string,billId:string)=>act(`final-${visitId}`,()=>apiFetch<ConsultationBill>(`/consultation-finance/bills/${billId}/finalize`,{method:"POST"}),"Bill finalized with sequential number.",visitId);
  const useFree=(visitId:string,entitlementId:string)=>act(`free-${visitId}`,()=>apiFetch(`/consultation-finance/visits/${visitId}/free-followup?entitlement_id=${entitlementId}`,{method:"POST"}),"Free follow-up entitlement used and visit cleared.",visitId);
  const makeComplimentary=(visitId:string)=>act(`comp-${visitId}`,()=>apiFetch("/consultation-finance/complimentary",{method:"POST",body:JSON.stringify({visit_id:visitId})}),"Doctor complimentary authorization recorded.",visitId);
  const pay=async(v:Visit,d:FinanceDecision)=>{
    if(!d.bill_id||!d.balance)return;
    const mode=paymentMode[v.visit_id]||setup?.payment_modes[0]?.id;
    const amount=paymentAmount[v.visit_id]||d.balance;
    if(!mode){setError("No payment mode configured");return}
    setBusy(`pay-${v.visit_id}`);setError("");setNotice("");
    try{
      const payment=await apiFetch<ConsultationPayment>("/consultation-finance/payments",{method:"POST",body:JSON.stringify({consultation_bill_id:d.bill_id,amount,payment_mode_id:mode,branch_id:v.branch_id,received_at:new Date().toISOString()})});
      setNotice("Payment recorded. Financial clearance updated.");await refreshDecision(v.visit_id);
      window.open(`/print/receipt/${payment.payment_id}`,"_blank");
    }catch(e:any){setError(e.message||"Payment failed")}finally{setBusy(null)}
  };

  const createFee=()=>{
    if(!consultService||!feeAmount)return setError("Enter consultation fee amount");
    return act("fee",()=>apiFetch("/consultation-finance/fees",{method:"POST",body:JSON.stringify({service_id:consultService.id,doctor_id:feeDoctor||null,branch_id:feeBranch||null,amount:feeAmount,effective_from:feeDate,effective_until:null})}),"New consultation fee version created.");
  };

  const filteredVisits=useMemo(()=>doctorId?visits.filter(v=>v.doctor_id===doctorId):visits,[visits,doctorId]);

  return <>
    <div className="header">
      <div><div className="eyebrow">PHASE 1 FINANCE</div><h1 className="page-title">Consultation Finance</h1><div className="muted">Clinical Visit stays separate. This module owns consultation money and clearance.</div></div>
      <button onClick={load} disabled={!!busy}>Refresh</button>
    </div>
    {error&&<div className="alert danger-box">{error}</div>}
    {notice&&<div className="alert success-box">{notice}</div>}

    <div className="toolbar card" style={{marginTop:16}}>
      <label>Date<input type="date" value={onDate} onChange={e=>setOnDate(e.target.value)}/></label>
      <label>Branch<select value={branchId} onChange={e=>setBranchId(e.target.value)}><option value="">All branches</option>{bootstrap?.branches.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
      <label>Doctor<select value={doctorId} onChange={e=>setDoctorId(e.target.value)}><option value="">All doctors</option>{bootstrap?.doctors.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
      <div className="policy-pill">{setup?.active_policy?`${setup.active_policy.free_followup_window_days}-day follow-up • ${setup.active_policy.max_free_followups} free use`:`No active follow-up policy`}</div>
    </div>

    <div className="grid" style={{marginTop:16}}>
      <div className="card"><div className="muted">Consultations cleared</div><div className="kpi">{report?.total_consultation_visits??"—"}</div></div>
      <div className="card"><div className="muted">Paid</div><div className="kpi">{report?.paid_consultations??"—"}</div></div>
      <div className="card"><div className="muted">Free / Complimentary</div><div className="kpi">{report?report.free_followups+report.complimentary_consultations:"—"}</div></div>
      <div className="card"><div className="muted">Collection</div><div className="kpi">{money(report?.total_collection)}</div><div className="muted">Cash {money(report?.cash)} • UPI {money(report?.upi)} • Card {money(report?.card)}</div></div>
    </div>

    {canCorrect&&<div className="card" style={{marginTop:18}}>
      <div className="header"><div><h3>Consultation Fee Master</h3><div className="muted">Create a new effective-dated version; historical bills never change.</div></div></div>
      <div className="form-grid">
        <label>Amount (₹)<input type="number" min="1" step="0.01" value={feeAmount} onChange={e=>setFeeAmount(e.target.value)} placeholder="Enter fee"/></label>
        <label>Branch<select value={feeBranch} onChange={e=>setFeeBranch(e.target.value)}><option value="">All branches</option>{bootstrap?.branches.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
        <label>Doctor<select value={feeDoctor} onChange={e=>setFeeDoctor(e.target.value)}><option value="">All doctors</option>{bootstrap?.doctors.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
        <label>Effective from<input type="date" value={feeDate} onChange={e=>setFeeDate(e.target.value)}/></label>
      </div>
      <button onClick={createFee} disabled={busy==="fee"}>{busy==="fee"?"Saving…":"Create Fee Version"}</button>
      <div className="muted" style={{marginTop:10}}>Configured versions: {setup?.fee_versions.length||0}</div>
    </div>}

    <div className="header" style={{marginTop:24}}><div><h2>Consultation queue</h2><div className="muted">The system decides whether money is required; Reception does not calculate the 10-day rule manually.</div></div></div>
    <div className="stack">
      {filteredVisits.length===0&&<div className="card muted">No Consultation/Follow-Up visits for this filter.</div>}
      {filteredVisits.map(v=>{
        const d=decisions[v.visit_id];
        if(!d)return <div className="card" key={v.visit_id}>Loading {v.patient_name}…</div>;
        const status=d.status;
        const cleared=status==="CLEARED";
        return <div className="card finance-row" key={v.visit_id}>
          <div className="finance-main">
            <div className="header"><div><h3>{v.patient_name} <span className="muted">• {v.uhid}</span></h3><div className="muted">{v.visit_type} • {v.doctor||"Doctor not assigned"} • {v.branch} • {fmtDateTime(v.checkin_at)}</div></div><span className={`status-chip ${cleared?"good":""}`}>{cleared?`${d.clearance_type} • CLEARED`:status.replace(/_/g," ")}</span></div>
            {d.valid_until&&status==="FREE_FOLLOWUP_ELIGIBLE"&&<div className="info-strip">Free follow-up valid until {fmtDateTime(d.valid_until)}.</div>}
            {d.amount&&<div className="amount-line">Consultation amount <b>{money(d.amount)}</b>{d.paid_amount!=="0"&&<> • Paid {money(d.paid_amount)} • Balance {money(d.balance)}</>}</div>}
            {d.bill_number&&<div className="muted">Bill: <b>{d.bill_number}</b> • {d.bill_status} {d.bill_id&&<button className="small ghost ml" onClick={()=>window.open(`/print/bill/${d.bill_id}`,"_blank")}>Print Bill</button>}</div>}
          </div>
          <div className="finance-actions">
            {canBill&&status==="FREE_FOLLOWUP_ELIGIBLE"&&d.entitlement_id&&<button onClick={()=>useFree(v.visit_id,d.entitlement_id!)} disabled={busy===`free-${v.visit_id}`}>Use Free Follow-Up</button>}
            {canBill&&status==="PAID_CONSULTATION_REQUIRED"&&d.amount&&<button onClick={()=>createBill(v.visit_id)} disabled={busy===`bill-${v.visit_id}`}>Create Bill</button>}
            {canBill&&status==="PAID_CONSULTATION_REQUIRED"&&!d.amount&&<span className="warning-text">Consultation fee not configured</span>}
            {canBill&&status==="BILL_DRAFT"&&d.bill_id&&<button onClick={()=>finalizeBill(v.visit_id,d.bill_id!)} disabled={busy===`final-${v.visit_id}`}>Finalize Bill</button>}
            {canPay&&["BILL_FINALIZED","BILL_PARTIALLY_PAID"].includes(status)&&d.bill_id&&<div className="payment-box">
              <select value={paymentMode[v.visit_id]||setup?.payment_modes[0]?.id||""} onChange={e=>setPaymentMode(x=>({...x,[v.visit_id]:e.target.value}))}>{setup?.payment_modes.map(m=><option key={m.id} value={m.id}>{m.name}</option>)}</select>
              <input type="number" step="0.01" min="0.01" value={paymentAmount[v.visit_id]??d.balance??""} onChange={e=>setPaymentAmount(x=>({...x,[v.visit_id]:e.target.value}))}/>
              <button onClick={()=>pay(v,d)} disabled={busy===`pay-${v.visit_id}`}>Receive Payment</button>
            </div>}
            {canComplimentary&&!cleared&&!["BILL_FINALIZED","BILL_PARTIALLY_PAID","BILL_PAID"].includes(status)&&<button className="secondary" onClick={()=>makeComplimentary(v.visit_id)} disabled={busy===`comp-${v.visit_id}`}>Doctor Complimentary</button>}
          </div>
        </div>
      })}
    </div>
  </>;
}
