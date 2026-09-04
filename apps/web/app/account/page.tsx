"use client";
import {FormEvent, useState} from "react";
import {apiFetch} from "../../lib/api";

export default function AccountPage(){
  const [currentPassword,setCurrentPassword]=useState("");
  const [newPassword,setNewPassword]=useState("");
  const [confirmPassword,setConfirmPassword]=useState("");
  const [message,setMessage]=useState("");
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  async function submit(e:FormEvent){
    e.preventDefault(); setMessage(""); setError("");
    if(newPassword!==confirmPassword){setError("New passwords do not match");return;}
    setBusy(true);
    try{
      await apiFetch("/auth/change-password",{method:"POST",body:JSON.stringify({current_password:currentPassword,new_password:newPassword})});
      setCurrentPassword("");setNewPassword("");setConfirmPassword("");setMessage("Password changed successfully.");
    }catch(e){setError(e instanceof Error?e.message:"Password change failed");}finally{setBusy(false);}
  }
  return <section className="page"><div className="page-head"><div><div className="eyebrow">ACCOUNT SECURITY</div><h1>Change password</h1></div></div>
    <div className="card" style={{maxWidth:560}}><form className="form-stack" onSubmit={submit}>
      <label>Current password<input type="password" value={currentPassword} onChange={e=>setCurrentPassword(e.target.value)} required/></label>
      <label>New password<input type="password" minLength={12} value={newPassword} onChange={e=>setNewPassword(e.target.value)} required/></label>
      <label>Confirm new password<input type="password" minLength={12} value={confirmPassword} onChange={e=>setConfirmPassword(e.target.value)} required/></label>
      {error&&<div className="alert danger-box">{error}</div>}{message&&<div className="alert success-box">{message}</div>}
      <button disabled={busy}>{busy?"Changing…":"Change password"}</button>
    </form></div>
  </section>;
}
