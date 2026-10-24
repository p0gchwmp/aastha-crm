"use client";
import {FormEvent, useState} from "react";
import {useRouter} from "next/navigation";
import {apiFetch} from "../../lib/api";

export default function Login(){
  const router=useRouter();
  const [username,setUsername]=useState("");
  const [password,setPassword]=useState("");
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  async function submit(e:FormEvent){
    e.preventDefault(); setBusy(true); setError("");
    try{
      const x=await apiFetch<{access_token:string}>("/auth/login",{method:"POST",body:JSON.stringify({username,password})});
      localStorage.setItem("aastha_token",x.access_token);
      const me=await apiFetch<{must_change_password:boolean;permissions:string[]}>("/auth/me");
      router.replace(me.must_change_password?"/account":me.permissions.includes("CONSULTATION_CLINICAL")?"/doctor":me.permissions.includes("CLINICAL_PREPARATION")?"/assistant":"/");
    }catch(e){setError(e instanceof Error?e.message:"Login failed")}finally{setBusy(false)}
  }
  return <div className="login-page"><div className="login-card">
    <div className="eyebrow">AASTHA SKIN & DERMATO-COSMETIC CENTRE</div>
    <h1>Aastha CRM</h1><p className="muted">Secure clinic operations workspace</p>
    <form onSubmit={submit} className="form-stack">
      <label>Username<input value={username} onChange={e=>setUsername(e.target.value)} autoComplete="username"/></label>
      <label>Password<input type="password" value={password} onChange={e=>setPassword(e.target.value)} autoComplete="current-password"/></label>
      {error&&<div className="alert danger-box">{error}</div>}
      <button disabled={busy}>{busy?"Signing in…":"Sign in"}</button>
    </form>
    <div className="demo-note">Use your assigned Aastha CRM credentials.</div>
  </div></div>
}
