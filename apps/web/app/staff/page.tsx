"use client";
import {FormEvent, useEffect, useState} from "react";
import Link from "next/link";
import {apiFetch} from "../../lib/api";

type Staff = {user_id:string; name:string; username:string; status:string; roles:string[]; branch_ids:string[]; row_version:number; must_change_password:boolean};
type Directory = {users:Staff[]; branches:{id:string;name:string}[]};
const empty = {name:"",username:"",role:"RECEPTIONIST",branch_ids:[] as string[],status:"ACTIVE",reason:"",temporary_password:""};

export default function StaffPage(){
  const [data,setData]=useState<Directory>({users:[],branches:[]});
  const [selected,setSelected]=useState<Staff|null>(null);
  const [mode,setMode]=useState<"create"|"edit"|"reset"|null>(null);
  const [form,setForm]=useState(empty);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [message,setMessage]=useState("");
  const [loaded,setLoaded]=useState(false);
  async function load(){const d=await apiFetch<Directory>("/admin/staff");setData(d);setLoaded(true);}
  useEffect(()=>{load().catch(e=>setError(e.message));},[]);
  function open(next:"create"|"edit"|"reset", user:Staff|null=null){
    setSelected(user);setMode(next);setError("");setMessage("");
    setForm(user?{...empty,name:user.name,username:user.username,role:user.roles[0],branch_ids:user.branch_ids,status:user.status}:{...empty,branch_ids:data.branches.length===1?[data.branches[0].id]:[]});
  }
  async function submit(e:FormEvent){
    e.preventDefault();setBusy(true);setError("");setMessage("");
    try{
      if(mode==="create") await apiFetch("/admin/staff",{method:"POST",body:JSON.stringify({name:form.name,username:form.username,role:form.role,branch_ids:form.branch_ids,temporary_password:form.temporary_password})});
      else if(selected&&mode==="edit") await apiFetch(`/admin/staff/${selected.user_id}`,{method:"PATCH",body:JSON.stringify({name:form.name,role:form.role,branch_ids:form.branch_ids,status:form.status,row_version:selected.row_version,reason:form.reason})});
      else if(selected&&mode==="reset") await apiFetch(`/admin/staff/${selected.user_id}/reset-password`,{method:"POST",body:JSON.stringify({row_version:selected.row_version,temporary_password:form.temporary_password,reason:form.reason})});
      setForm({...empty});setMode(null);setSelected(null);
      setMessage(mode==="create"?"Reception account created. Share the username and temporary password securely. The staff member must change it at first login.":mode==="reset"?"Password reset. Existing sessions have ended. The staff member must change the temporary password at next login.":"Account updated. The staff member must sign in again.");
      await load();
    }catch(e){setError(e instanceof Error?e.message:"Unable to save");}finally{setBusy(false);}
  }
  return <section>
    <header className="header"><div><div className="eyebrow">ADMINISTRATION</div><h1 className="page-title">Staff Users</h1><p className="muted">Individual accounts for your reception team.</p></div><div className="finance-actions"><Link href="/admin" className="button-link secondary">View audit history</Link><button disabled={!loaded||busy} onClick={()=>open("create")}>Add receptionist</button></div></header>
    {error&&<div role="alert" className="alert danger-box">{error}</div>}
    {message&&<div role="status" className="alert success-box">{message}</div>}
    {mode&&<div className="card" style={{maxWidth:680,marginBottom:20}}><h2>{mode==="create"?"Add receptionist":mode==="reset"?`Reset password: ${selected?.username}`:`Edit ${selected?.username}`}</h2>
    <form className="form-stack" onSubmit={submit}>
      {mode!=="reset"&&<>
      <label>Staff name<input required maxLength={150} value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label>
      {mode==="create"&&<label>Username<input required minLength={3} maxLength={100} pattern="[a-zA-Z0-9][a-zA-Z0-9._-]*" autoComplete="off" value={form.username} onChange={e=>setForm({...form,username:e.target.value})}/><span className="muted">Letters, numbers, dots, underscores or hyphens. Each person needs a unique username.</span></label>}
      <label>Role<select value={form.role} onChange={e=>setForm({...form,role:e.target.value})}><option value="RECEPTIONIST">Receptionist</option><option value="SUPER_RECEPTIONIST">Super Receptionist</option></select></label>
      <fieldset style={{border:"1px solid #ddd",borderRadius:10,padding:12}}><legend>Allowed branches — choose at least one</legend>{data.branches.map(b=><label key={b.id} className="checkline"><input type="checkbox" checked={form.branch_ids.includes(b.id)} onChange={e=>setForm({...form,branch_ids:e.target.checked?[...form.branch_ids,b.id]:form.branch_ids.filter(x=>x!==b.id)})}/>{b.name}</label>)}</fieldset>
      {mode==="edit"&&<label>Account status<select value={form.status} onChange={e=>setForm({...form,status:e.target.value})}><option value="ACTIVE">Active</option><option value="INACTIVE">Inactive — cannot sign in</option></select></label>}
      </>}
      {mode!=="edit"&&<label>Temporary password<input type="password" required minLength={12} maxLength={128} autoComplete="new-password" value={form.temporary_password} onChange={e=>setForm({...form,temporary_password:e.target.value})}/><span className="muted">At least 12 characters. Staff must replace it at their next login.</span></label>}
      {mode!=="create"&&<label>Reason for change<input required minLength={3} maxLength={500} value={form.reason} onChange={e=>setForm({...form,reason:e.target.value})}/></label>}
      <div className="finance-actions"><button type="button" className="secondary" disabled={busy} onClick={()=>{setMode(null);setForm({...empty});setError("");}}>Cancel</button><button disabled={busy||(mode!=="reset"&&!form.branch_ids.length)}>{busy?"Saving…":mode==="create"?"Create account":mode==="reset"?"Reset password":"Save changes"}</button></div>
    </form></div>}
    <div className="table-wrap"><table><thead><tr><th>Name / username</th><th>Role</th><th>Branches</th><th>Status</th><th>Actions</th></tr></thead><tbody>
      {data.users.map(u=><tr key={u.user_id}><td><b>{u.name}</b><div className="muted">{u.username}</div></td><td>{u.roles.map(x=>x==="RECEPTIONIST"?"Receptionist":"Super Receptionist").join(", ")}</td><td>{u.branch_ids.map(id=>data.branches.find(b=>b.id===id)?.name||"Unavailable branch").join(", ")||"No branch assigned — please edit"}</td><td><span className={`badge ${u.status!=="ACTIVE"?"danger":""}`}>{u.status==="ACTIVE"?"Active":"Inactive"}</span>{u.must_change_password&&<div className="muted">Password change required</div>}</td><td><div className="finance-actions"><button className="secondary" disabled={busy} onClick={()=>open("edit",u)}>Edit access</button><button className="secondary" disabled={busy} onClick={()=>open("reset",u)}>Reset password</button></div></td></tr>)}
      {!data.users.length&&<tr><td colSpan={5} className="empty">{loaded?"No reception accounts found.":"Loading reception accounts…"}</td></tr>}
    </tbody></table></div>
    <p className="muted">Account and access changes are recorded in Admin Audit. Deactivation preserves the staff member’s existing clinic records.</p>
  </section>;
}
