"use client";
import {FormEvent,useEffect,useMemo,useState} from "react";
import {apiFetch} from "../../lib/api";
import type {Appointment,Bootstrap,ConversionPreview,Patient,Visit} from "../../lib/types";

function ageLabel(p:Patient){return p.age!=null?`${p.age} yrs`:"Age —"}
function dt(v?:string|null){return v?new Date(v).toLocaleString("en-IN",{dateStyle:"medium",timeStyle:"short"}):"—"}
function estimatedDob(age?:number|null){if(age==null)return "";const y=new Date().getFullYear()-age;return `${y}-01-01`}

type RegForm={full_name:string;mobile:string;alternate_mobile:string;gender:string;dob:string;dob_is_estimated:boolean;registration_branch_id:string;region_id:string;district_id:string;locality_id:string;address_line:string;duplicate_override_confirmed:boolean};
const emptyForm:RegForm={full_name:"",mobile:"",alternate_mobile:"",gender:"",dob:"",dob_is_estimated:false,registration_branch_id:"",region_id:"",district_id:"",locality_id:"",address_line:"",duplicate_override_confirmed:false};

export default function PatientsPage(){
  const [meta,setMeta]=useState<Bootstrap|null>(null);
  const [patients,setPatients]=useState<Patient[]>([]);
  const [selected,setSelected]=useState<Patient|null>(null);
  const [visits,setVisits]=useState<Visit[]>([]);
  const [q,setQ]=useState("");
  const [error,setError]=useState("");
  const [showRegister,setShowRegister]=useState(false);
  const [leadPreview,setLeadPreview]=useState<ConversionPreview|null>(null);
  const [form,setForm]=useState<RegForm>(emptyForm);
  const [matches,setMatches]=useState<Patient[]>([]);
  const [existingPatientId,setExistingPatientId]=useState<string>("");
  const [showVisit,setShowVisit]=useState(false);
  const [confirmedIdentity,setConfirmedIdentity]=useState(false);
  const [todayAppts,setTodayAppts]=useState<Appointment[]>([]);
  const [visitForm,setVisitForm]=useState({appointment_id:"",branch_id:"",doctor_id:"",visit_type_id:"",visit_status_id:"",chief_complaint_ids:[] as string[]});

  const districts=useMemo(()=>meta?.districts.filter(x=>!form.region_id||x.region_id===form.region_id)||[],[meta,form.region_id]);
  const localities=useMemo(()=>meta?.localities.filter(x=>!form.district_id||x.district_id===form.district_id)||[],[meta,form.district_id]);
  const waitingStatus=useMemo(()=>meta?.visit_statuses.find(x=>x.code==="WAITING")||meta?.visit_statuses.find(x=>x.code==="CREATED"),[meta]);
  const consultationType=useMemo(()=>meta?.visit_types.find(x=>x.code==="CONSULTATION"),[meta]);

  useEffect(()=>{
    const params=new URLSearchParams(window.location.search);const lead=params.get("lead");const patient=params.get("patient");
    apiFetch<Bootstrap>("/meta/bootstrap").then(x=>{
      setMeta(x);
      setForm(f=>({...f,registration_branch_id:x.branches[0]?.id||""}));
      setVisitForm(v=>({...v,branch_id:x.branches[0]?.id||"",doctor_id:x.doctors[0]?.id||"",visit_type_id:x.visit_types.find(t=>t.code==="CONSULTATION")?.id||x.visit_types[0]?.id||"",visit_status_id:x.visit_statuses.find(t=>t.code==="WAITING")?.id||x.visit_statuses[0]?.id||""}));
      if(lead) openLeadConversion(lead,x); else if(patient) openPatient(patient);
    }).catch(e=>setError(e.message));
  },[]);

  async function search(){setError("");if(!q.trim()){setPatients([]);return}try{setPatients(await apiFetch<Patient[]>(`/patients/search?q=${encodeURIComponent(q.trim())}`))}catch(e){setError(e instanceof Error?e.message:"Search failed")}}

  async function openPatient(patientId:string){
    setError("");
    try{
      const p=await apiFetch<Patient>(`/patients/${patientId}`);setSelected(p);
      setVisits(await apiFetch<Visit[]>(`/patients/${patientId}/visits`));
    }catch(e){setError(e instanceof Error?e.message:"Unable to load Patient")}
  }

  function beginNewPatient(){
    if(!meta)return;
    setLeadPreview(null);setExistingPatientId("");setMatches([]);setForm({...emptyForm,registration_branch_id:meta.branches[0]?.id||""});setShowRegister(true);
  }

  async function openLeadConversion(leadId:string, bootstrap?:Bootstrap){
    setError("");
    try{
      const preview=await apiFetch<ConversionPreview>(`/leads/${leadId}/conversion-preview`);setLeadPreview(preview);setMatches(preview.candidates||[]);
      if(preview.already_converted_patient_id){await openPatient(preview.already_converted_patient_id);return}
      setForm(f=>({...emptyForm,
        full_name:preview.lead_name,
        mobile:preview.mobile||"",
        gender:preview.gender||"",
        dob:estimatedDob(preview.age),
        dob_is_estimated:preview.age!=null,
        registration_branch_id:preview.preferred_branch_id||bootstrap?.branches[0]?.id||meta?.branches[0]?.id||f.registration_branch_id,
      }));
      setShowRegister(true);
    }catch(e){setError(e instanceof Error?e.message:"Unable to prepare Lead conversion")}
  }

  async function checkMatches(next=form){
    const params=new URLSearchParams();if(next.full_name)params.set("name",next.full_name);if(next.mobile)params.set("mobile",next.mobile);if(next.dob)params.set("dob",next.dob);if(next.gender)params.set("gender",next.gender);
    if(!params.toString()){setMatches([]);return []}
    const rows=await apiFetch<Patient[]>(`/patients/match?${params.toString()}`);setMatches(rows);return rows;
  }

  function payload(overrides:Record<string,unknown>={}){
    if(!meta)throw new Error("CRM masters unavailable");
    return {
      organization_id:meta.organization_id,
      full_name:form.full_name,
      mobile:form.mobile||null,
      alternate_mobile:form.alternate_mobile||null,
      gender:form.gender||null,
      dob:form.dob||null,
      dob_is_estimated:form.dob_is_estimated,
      registration_branch_id:form.registration_branch_id,
      profile_status:"COMPLETE",
      legacy_patient_id:null,
      region_id:form.region_id||null,
      district_id:form.district_id||null,
      locality_id:form.locality_id||null,
      address_line:form.address_line||null,
      duplicate_override_confirmed:form.duplicate_override_confirmed,
      ...overrides,
    };
  }

  async function persistRegistration(){
    setError("");
    try{
      if(leadPreview){
        const p=await apiFetch<Patient>(`/leads/${leadPreview.lead_id}/convert`,{method:"POST",body:JSON.stringify(payload({existing_patient_id:existingPatientId||null}))});
        setShowRegister(false);setLeadPreview(null);window.history.replaceState({},"","/patients");await openPatient(p.patient_id);return;
      }
      const existing=await checkMatches();
      if(existing.length&&!form.duplicate_override_confirmed){setError("Possible existing Patient found. Review the matches below or tick ‘Create separate Patient’.");return}
      const p=await apiFetch<Patient>("/patients",{method:"POST",body:JSON.stringify(payload())});setShowRegister(false);await openPatient(p.patient_id);
    }catch(e){setError(e instanceof Error?e.message:"Registration failed")}
  }
  async function saveRegistration(e:FormEvent){e.preventDefault();await persistRegistration()}

  async function useExisting(patientId:string){
    if(!leadPreview){await openPatient(patientId);setShowRegister(false);return}
    setExistingPatientId(patientId);
  }

  async function startVisit(){
    if(!selected||!meta)return;
    setConfirmedIdentity(false);
    const appts=await apiFetch<Appointment[]>(`/appointments?patient_id=${selected.patient_id}`);setTodayAppts(appts);
    const first=appts.find(a=>!["CANCELLED","NO_SHOW","COMPLETED"].includes(a.status_code||""));
    setVisitForm(v=>({...v,appointment_id:first?.appointment_id||"",branch_id:first?.branch_id||selected.registration_branch_id||v.branch_id,doctor_id:first?.doctor_id||v.doctor_id,visit_type_id:consultationType?.id||v.visit_type_id,visit_status_id:waitingStatus?.id||v.visit_status_id,chief_complaint_ids:[]}));
    setShowVisit(true);
  }

  async function createVisit(e:FormEvent){
    e.preventDefault();if(!selected||!confirmedIdentity)return;setError("");
    try{
      await apiFetch("/visits",{method:"POST",body:JSON.stringify({patient_id:selected.patient_id,appointment_id:visitForm.appointment_id||null,branch_id:visitForm.branch_id,doctor_id:visitForm.doctor_id||null,visit_type_id:visitForm.visit_type_id,visit_status_id:visitForm.visit_status_id,checkin_at:new Date().toISOString(),chief_complaint_ids:visitForm.chief_complaint_ids,identity_confirmed:true})});
      setShowVisit(false);setVisits(await apiFetch<Visit[]>(`/patients/${selected.patient_id}/visits`));
    }catch(e){setError(e instanceof Error?e.message:"Unable to create Visit")}
  }

  function toggleComplaint(id:string){setVisitForm(v=>({...v,chief_complaint_ids:v.chief_complaint_ids.includes(id)?v.chief_complaint_ids.filter(x=>x!==id):[...v.chief_complaint_ids,id]}))}

  async function addCustomLocality(){
    if(!form.district_id){setError("Select District before adding a custom Locality.");return}
    const name=window.prompt("Enter new Locality");if(!name?.trim())return;
    try{const r=await apiFetch<any>("/masters/localities",{method:"POST",body:JSON.stringify({district_id:form.district_id,name:name.trim()})});
      setMeta(m=>m?({...m,localities:[...m.localities.filter(x=>x.id!==r.locality_id),{id:r.locality_id,name:r.name,district_id:form.district_id,approval_status:r.approval_status}]}):m);
      setForm(f=>({...f,locality_id:r.locality_id}));
    }catch(e){setError(e instanceof Error?e.message:"Unable to add Locality")}}

  async function addCustomComplaint(){
    const name=window.prompt("Enter new Chief Complaint");if(!name?.trim())return;
    try{const r=await apiFetch<any>("/masters/chief-complaints",{method:"POST",body:JSON.stringify({name:name.trim()})});
      setMeta(m=>m?({...m,chief_complaints:[...m.chief_complaints.filter(x=>x.id!==r.chief_complaint_id),{id:r.chief_complaint_id,name:r.name}]}):m);
      setVisitForm(v=>({...v,chief_complaint_ids:[...v.chief_complaint_ids.filter(x=>x!==r.chief_complaint_id),r.chief_complaint_id]}));
    }catch(e){setError(e instanceof Error?e.message:"Unable to add Chief Complaint")}}

  return <>
    <div className="header"><div><div className="eyebrow">PATIENT REGISTER</div><h1 className="page-title">Patients</h1><div className="muted">Global UHID, shared-mobile-safe matching, verified registration and Visit history.</div></div><button onClick={beginNewPatient}>+ Register Patient</button></div>
    {error&&<div className="alert danger-box">{error}</div>}
    <div className="toolbar"><input placeholder="Search UHID, name or mobile" value={q} onChange={e=>setQ(e.target.value)} onKeyDown={e=>e.key==="Enter"&&search()}/><button className="secondary" onClick={search}>Search</button><button className="ghost" onClick={()=>{setQ("");setPatients([])}}>Clear</button></div>
    <div className="table-wrap"><table><thead><tr><th>Patient</th><th>Contact</th><th>Area</th><th>Last Visit</th><th>Profile</th><th></th></tr></thead><tbody>
      {patients.map(p=><tr key={p.patient_id}><td><b>{p.full_name}</b><div className="muted">{p.uhid} · {ageLabel(p)} · {p.gender||"—"}</div></td><td>{p.primary_mobile||"—"}</td><td>{p.area||"—"}</td><td>{dt(p.last_visit_at)}</td><td><span className="badge">{p.profile_status}</span></td><td><button className="small secondary" onClick={()=>openPatient(p.patient_id)}>Open</button></td></tr>)}
      {!patients.length&&<tr><td colSpan={6} className="empty">Search by UHID, name or mobile. Shared mobile numbers will show all matching family members.</td></tr>}
    </tbody></table></div>

    {showRegister&&<div className="modal-backdrop"><div className="modal"><div className="modal-head"><div><div className="eyebrow">{leadPreview?"LEAD → PATIENT":"NEW PATIENT"}</div><h2>{leadPreview?"Verify registration":"Register Patient"}</h2></div><button className="icon" onClick={()=>setShowRegister(false)}>×</button></div>
      {leadPreview&&<div className="patient-strip"><b>{leadPreview.lead_name}</b><span>{leadPreview.mobile||"No mobile"}</span><span className="badge">Lead conversion</span></div>}
      {!!matches.length&&<div className="previous-box" style={{marginTop:12}}><b>Possible existing Patients</b><p className="muted">Mobile is not unique. Verify Name + Age/Gender + UHID before choosing.</p>{matches.map(m=><div className="candidate-card" key={m.patient_id}><div><b>{m.full_name}</b><div className="muted">{m.uhid} · {ageLabel(m)} · {m.gender||"—"} · {m.primary_mobile||"No mobile"}</div><div className="muted">{(m.match_reasons||[]).join(" · ")}</div></div><button type="button" className={existingPatientId===m.patient_id?"":"secondary"} onClick={()=>useExisting(m.patient_id)}>{existingPatientId===m.patient_id?"Selected":"Use Existing"}</button></div>)}</div>}
      {existingPatientId?<div className="alert warning-box" style={{marginTop:12}}>This Lead will be linked to the selected existing UHID. No new UHID will be generated.</div>:<form onSubmit={saveRegistration} className="form-grid" style={{marginTop:14}}>
        <label>Name<input required value={form.full_name} onChange={e=>setForm({...form,full_name:e.target.value})} onBlur={()=>checkMatches().catch(()=>{})}/></label>
        <label>Mobile<input value={form.mobile} onChange={e=>setForm({...form,mobile:e.target.value})} onBlur={()=>checkMatches().catch(()=>{})}/></label>
        <label>Alternate mobile<input value={form.alternate_mobile} onChange={e=>setForm({...form,alternate_mobile:e.target.value})}/></label>
        <label>Gender<select value={form.gender} onChange={e=>setForm({...form,gender:e.target.value})}><option value="">Select</option><option>Female</option><option>Male</option><option>Other</option></select></label>
        <label>DOB<input type="date" value={form.dob} onChange={e=>setForm({...form,dob:e.target.value,dob_is_estimated:false})}/></label>
        <label className="checkline"><input type="checkbox" checked={form.dob_is_estimated} onChange={e=>setForm({...form,dob_is_estimated:e.target.checked})}/> DOB estimated from age</label>
        <label>Registration branch<select required value={form.registration_branch_id} onChange={e=>setForm({...form,registration_branch_id:e.target.value})}>{meta?.branches.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
        <label>Region<select value={form.region_id} onChange={e=>setForm({...form,region_id:e.target.value,district_id:"",locality_id:""})}><option value="">Select</option>{meta?.regions.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
        <label>District<select value={form.district_id} onChange={e=>setForm({...form,district_id:e.target.value,locality_id:""})}><option value="">Select</option>{districts.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
        <label>Locality<select value={form.locality_id} onChange={e=>setForm({...form,locality_id:e.target.value})}><option value="">Select</option>{localities.map(x=><option key={x.id} value={x.id}>{x.name}{x.approval_status==="PENDING"?" (Pending)":""}</option>)}</select><button type="button" className="small ghost" onClick={addCustomLocality}>+ Add Custom</button></label>
        <label className="span2">Address<input value={form.address_line} onChange={e=>setForm({...form,address_line:e.target.value})}/></label>
        {!!matches.length&&<label className="span2 checkline warning-check"><input type="checkbox" checked={form.duplicate_override_confirmed} onChange={e=>setForm({...form,duplicate_override_confirmed:e.target.checked})}/> I verified the matches and this is a genuinely separate Patient who needs a new UHID.</label>}
        <div className="span2 row end"><button type="button" className="secondary" onClick={()=>setShowRegister(false)}>Cancel</button><button>{leadPreview?"Create UHID & Convert":"Register Patient"}</button></div>
      </form>}
      {existingPatientId&&<div className="row end" style={{marginTop:14}}><button className="secondary" onClick={()=>setExistingPatientId("")}>Choose different</button><button onClick={()=>persistRegistration()}>Link Lead to Existing Patient</button></div>}
    </div></div>}

    {selected&&<div className="drawer-backdrop" onClick={()=>setSelected(null)}><div className="drawer wide-drawer" onClick={e=>e.stopPropagation()}><div className="modal-head"><div><div className="eyebrow">PATIENT</div><h2>{selected.full_name}</h2><div className="muted">{selected.uhid} · {ageLabel(selected)} · {selected.gender||"—"}</div></div><button className="icon" onClick={()=>setSelected(null)}>×</button></div>
      <div className="identity-banner"><div><span>UHID</span><b>{selected.uhid}</b></div><div><span>Mobile</span><b>{selected.primary_mobile||"—"}</b></div><div><span>Area</span><b>{selected.area||"—"}</b></div><div><span>Profile</span><b>{selected.profile_status}</b></div></div>
      <div className="row" style={{margin:"16px 0"}}><button onClick={startVisit}>+ New Visit</button></div>
      <div className="card inset"><h3>Visit history</h3>{visits.length?visits.map(v=><div className="visit-history" key={v.visit_id}><div><b>{v.visit_type||"Visit"}</b><div className="muted">{dt(v.checkin_at)} · {v.branch||"—"} · {v.doctor||"No doctor"}</div></div><span className="badge">{v.status||"—"}</span></div>):<div className="empty">No previous Visits.</div>}</div>
    </div></div>}

    {showVisit&&selected&&<div className="modal-backdrop"><div className="modal"><div className="modal-head"><div><div className="eyebrow">NEW VISIT</div><h2>Confirm Patient & Create Visit</h2></div><button className="icon" onClick={()=>setShowVisit(false)}>×</button></div>
      <div className="confirm-patient"><div className="confirm-name">{selected.full_name}</div><div>{ageLabel(selected)} · {selected.gender||"—"}</div><div className="confirm-uhid">UHID: {selected.uhid}</div></div>
      <label className="checkline identity-check"><input type="checkbox" checked={confirmedIdentity} onChange={e=>setConfirmedIdentity(e.target.checked)}/> I confirmed Name + Age/Gender + UHID for the correct Patient.</label>
      <form onSubmit={createVisit} className="form-grid" style={{marginTop:16}}>
        <label>Today's appointment<select value={visitForm.appointment_id} onChange={e=>{const a=todayAppts.find(x=>x.appointment_id===e.target.value);setVisitForm({...visitForm,appointment_id:e.target.value,branch_id:a?.branch_id||visitForm.branch_id,doctor_id:a?.doctor_id||visitForm.doctor_id})}}><option value="">Walk-in / no appointment</option>{todayAppts.map(a=><option key={a.appointment_id} value={a.appointment_id}>{new Date(a.scheduled_start).toLocaleTimeString("en-IN",{hour:"2-digit",minute:"2-digit"})} · {a.doctor||"Doctor"} · {a.status}</option>)}</select></label>
        <label>Branch<select required value={visitForm.branch_id} onChange={e=>setVisitForm({...visitForm,branch_id:e.target.value})}>{meta?.branches.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
        <label>Doctor<select value={visitForm.doctor_id} onChange={e=>setVisitForm({...visitForm,doctor_id:e.target.value})}><option value="">Unassigned</option>{meta?.doctors.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
        <label>Visit type<select required value={visitForm.visit_type_id} onChange={e=>setVisitForm({...visitForm,visit_type_id:e.target.value})}>{meta?.visit_types.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
        <label className="span2">Chief complaints<div className="chip-grid">{meta?.chief_complaints.map(x=><button type="button" className={visitForm.chief_complaint_ids.includes(x.id)?"chip selected":"chip"} key={x.id} onClick={()=>toggleComplaint(x.id)}>{x.name}</button>)}<button type="button" className="chip" onClick={addCustomComplaint}>+ Add Custom</button></div></label>
        <div className="span2 row end"><button type="button" className="secondary" onClick={()=>setShowVisit(false)}>Cancel</button><button disabled={!confirmedIdentity}>Create Visit</button></div>
      </form>
    </div></div>}
  </>
}
