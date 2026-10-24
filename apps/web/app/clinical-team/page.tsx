"use client";
import {FormEvent, useEffect, useState} from "react";
import Link from "next/link";
import {apiFetch} from "../../lib/api";

type Staff = {user_id:string; name:string; username:string; status:string; roles:string[]; branch_ids:string[]; row_version:number; must_change_password:boolean; configured_roles:string[]; organization_wide:boolean; doctor:{doctor_id:string;doctor_code:string;speciality:string|null}|null};
type Directory = {users:Staff[]; branches:{id:string;name:string}[];unlinked_doctors:{id:string;name:string;code:string}[]};
const empty = {name:"",username:"",role:"DOCTOR",doctor_code:"",speciality:"",existing_doctor_id:"",branch_ids:[] as string[],status:"ACTIVE",reason:"",temporary_password:""};

export default function ClinicalTeamPage(){
  const [data,setData]=useState<Directory>({users:[],branches:[],unlinked_doctors:[]});
  const [selected,setSelected]=useState<Staff|null>(null);
  const [mode,setMode]=useState<"create"|"edit"|"reset"|null>(null);
  const [form,setForm]=useState(empty);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [message,setMessage]=useState("");
  const [loaded,setLoaded]=useState(false);
  async function load(){const d=await apiFetch<Directory>("/admin/clinical-team");setData(d);setLoaded(true);}
  useEffect(()=>{load().catch(e=>setError(e.message));},[]);
  function open(next:"create"|"edit"|"reset", user:Staff|null=null){
    setSelected(user);setMode(next);setError("");setMessage("");
    setForm(user?{...empty,name:user.name,username:user.username,role:user.configured_roles[0],doctor_code:user.doctor?.doctor_code||"",speciality:user.doctor?.speciality||"",branch_ids:user.branch_ids,status:user.status}:{...empty,branch_ids:data.branches.length===1?[data.branches[0].id]:[]});
  }
  async function submit(e:FormEvent){
    e.preventDefault();setBusy(true);setError("");setMessage("");
    try{
      if(mode==="create") await apiFetch("/admin/clinical-team",{method:"POST",body:JSON.stringify({name:form.name,username:form.username,role:form.role,branch_ids:form.branch_ids,temporary_password:form.temporary_password,...(form.role==="DOCTOR"?{doctor_code:form.doctor_code||null,speciality:form.speciality||null,existing_doctor_id:form.existing_doctor_id||null}:{})})});
      else if(selected&&mode==="edit") await apiFetch(`/admin/clinical-team/${selected.user_id}`,{method:"PATCH",body:JSON.stringify({name:form.name,role:form.role,branch_ids:form.branch_ids,status:form.status,row_version:selected.row_version,reason:form.reason,...(form.role==="DOCTOR"?{speciality:form.speciality||null}:{})})});
      else if(selected&&mode==="reset") await apiFetch(`/admin/clinical-team/${selected.user_id}/reset-password`,{method:"POST",body:JSON.stringify({row_version:selected.row_version,temporary_password:form.temporary_password,reason:form.reason})});
      setForm({...empty});setMode(null);setSelected(null);
      setMessage(mode==="create"?"Clinical account created. Share the username and temporary password securely. The staff member must change it at first login.":mode==="reset"?"Password reset. Existing sessions have ended. The staff member must change the temporary password at next login.":"Account updated. The staff member must sign in again.");
      await load();
    }catch(e){setError(e instanceof Error?e.message:"Unable to save");}finally{setBusy(false);}
  }
  return <section>
    <header className="header"><div><div className="eyebrow">ADMINISTRATION</div><h1 className="page-title">Clinical Team</h1><p className="muted">Individual Doctor and Clinical Assistant accounts. Deactivation ends access; existing appointments and records remain.</p></div><div className="finance-actions"><Link href="/appointments/schedules" className="button-link secondary">Doctor schedules</Link><Link href="/admin" className="button-link secondary">View audit history</Link><button disabled={!loaded||busy} onClick={()=>open("create")}>Add clinical account</button></div></header>
    {error&&<div role="alert" className="alert danger-box">{error}</div>}
    {message&&<div role="status" className="alert success-box">{message}</div>}
    {mode&&<div className="card" style={{maxWidth:680,marginBottom:20}}><h2>{mode==="create"?"Add clinical account":mode==="reset"?`Reset password: ${selected?.username}`:`Edit ${selected?.username}`}</h2>
    <form className="form-stack" onSubmit={submit}>
      {mode!=="reset"&&<>
      <label>Staff name<input required maxLength={150} value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label>
      {mode==="create"&&<label>Username<input aria-label="Username" required minLength={3} maxLength={100} pattern="[a-zA-Z0-9][a-zA-Z0-9._-]*" autoComplete="off" value={form.username} onChange={e=>setForm({...form,username:e.target.value})}/><span className="muted">Letters, numbers, dots, underscores or hyphens. Each person needs a unique username.</span></label>}
      <label>Role<select aria-label="Role" disabled={mode==="edit"} value={form.role} onChange={e=>setForm({...form,role:e.target.value})}><option value="DOCTOR">Doctor</option><option value="CLINICAL_ASSISTANT">Clinical Assistant</option></select></label>
      {form.role==="DOCTOR"&&<>
      {mode==="create"&&<label>Existing Doctor profile (optional)<select aria-label="Existing Doctor profile" value={form.existing_doctor_id} onChange={e=>setForm({...form,existing_doctor_id:e.target.value})}><option value="">Create a new Doctor profile</option>{data.unlinked_doctors.map(d=><option key={d.id} value={d.id}>{d.name} ({d.code})</option>)}</select></label>}
      {!form.existing_doctor_id&&<label>Doctor code<input aria-label="Doctor code" disabled={mode==="edit"} required maxLength={40} pattern="[A-Za-z0-9_-]+" value={form.doctor_code} onChange={e=>setForm({...form,doctor_code:e.target.value})}/></label>}
      <label>Speciality<input aria-label="Speciality" maxLength={120} value={form.speciality} onChange={e=>setForm({...form,speciality:e.target.value})}/></label></>}
      <fieldset style={{border:"1px solid #ddd",borderRadius:10,padding:12}}><legend>Allowed branches — choose at least one</legend>{data.branches.map(b=><label key={b.id} className="checkline"><input type="checkbox" checked={form.branch_ids.includes(b.id)} onChange={e=>setForm({...form,branch_ids:e.target.checked?[...form.branch_ids,b.id]:form.branch_ids.filter(x=>x!==b.id)})}/>{b.name}</label>)}</fieldset>
      {mode==="edit"&&<label>Account status<select aria-label="Account status" value={form.status} onChange={e=>setForm({...form,status:e.target.value})}><option value="ACTIVE">Active</option><option value="INACTIVE">Inactive — cannot sign in</option></select></label>}
      </>}
      {mode!=="edit"&&<label>Temporary password<input aria-label="Temporary password" type="password" required minLength={12} maxLength={128} autoComplete="new-password" value={form.temporary_password} onChange={e=>setForm({...form,temporary_password:e.target.value})}/><span className="muted">At least 12 characters. Staff must replace it at their next login.</span></label>}
      {mode!=="create"&&<label>Reason for change<input aria-label="Reason for change" required minLength={3} maxLength={500} value={form.reason} onChange={e=>setForm({...form,reason:e.target.value})}/></label>}
      <div className="finance-actions"><button type="button" className="secondary" disabled={busy} onClick={()=>{setMode(null);setForm({...empty});setError("");}}>Cancel</button><button disabled={busy||(mode!=="reset"&&!form.branch_ids.length)}>{busy?"Saving…":mode==="create"?"Create account":mode==="reset"?"Reset password":"Save changes"}</button></div>
    </form></div>}
    <div className="table-wrap"><table><thead><tr><th>Name / username</th><th>Role</th><th>Branches</th><th>Status</th><th>Actions</th></tr></thead><tbody>
      {data.users.map(u=><tr key={u.user_id}><td><b>{u.name}</b><div className="muted">{u.username}</div></td><td>{u.configured_roles.map(x=>x==="DOCTOR"?"Doctor":"Clinical Assistant").join(", ")}{u.doctor&&<div className="muted">{u.doctor.doctor_code} · {u.doctor.speciality}</div>}</td><td>{u.branch_ids.map(id=>data.branches.find(b=>b.id===id)?.name||"Unavailable branch").join(", ")||(u.organization_wide?"All clinic branches":"No current branch access")}</td><td><span className={`badge ${u.status!=="ACTIVE"?"danger":""}`}>{u.status==="ACTIVE"?"Active":"Inactive"}</span>{u.must_change_password&&<div className="muted">Password change required</div>}</td><td><div className="finance-actions"><button className="secondary" disabled={busy} onClick={()=>open("edit",u)}>Edit access</button><button className="secondary" disabled={busy} onClick={()=>open("reset",u)}>Reset password</button></div></td></tr>)}
      {!data.users.length&&<tr><td colSpan={5} className="empty">{loaded?"No clinical accounts found.":"Loading clinical accounts…"}</td></tr>}
    </tbody></table></div>
    <p className="muted">Account and access changes are recorded in Admin Audit. Deactivation preserves the staff member’s existing clinic records.</p>
  </section>;
}
