"use client";
import Link from "next/link";
import {usePathname, useRouter} from "next/navigation";
import {useEffect, useState} from "react";
import {apiFetch} from "../lib/api";

type Me = {name:string; username:string; roles:string[]; permissions:string[]; must_change_password:boolean};

export default function AppShell({children}:{children:React.ReactNode}) {
  const pathname = usePathname();
  const router = useRouter();
  const [me,setMe] = useState<Me|null>(null);
  const [ready,setReady] = useState(pathname === "/login");

  useEffect(()=>{
    if(pathname === "/login") { setReady(true); return; }
    const token = localStorage.getItem("aastha_token");
    if(!token){ router.replace("/login"); return; }
    apiFetch<Me>("/auth/me").then(x=>{setMe(x);if(x.must_change_password && pathname!=="/account"){setReady(false);router.replace("/account");return;}setReady(true)}).catch(()=>{
      localStorage.removeItem("aastha_token"); router.replace("/login");
    });
  },[pathname,router]);

  if(pathname === "/login") return <>{children}</>;
  if(!ready) return <div className="loading-screen">Loading Aastha CRM…</div>;

  const logout=()=>{localStorage.removeItem("aastha_token");router.replace("/login")};
  return <div className="shell">
    <aside className="sidebar">
      <div className="brand">AASTHA CRM</div>
      <div className="profile-mini"><b>{me?.name}</b><span>{me?.roles?.[0]?.replace(/_/g," ")}</span></div>
      <nav className="nav">
        <Link className={pathname==="/"?"active":""} href="/">Dashboard</Link>
        <Link className={pathname.startsWith("/leads")?"active":""} href="/leads">Leads</Link>
        <Link className={pathname.startsWith("/appointments")?"active":""} href="/appointments">Appointments</Link>
        <Link className={pathname.startsWith("/patients")?"active":""} href="/patients">Patients</Link>
        <Link className={pathname.startsWith("/visits")?"active":""} href="/visits">Visits</Link>
        <Link className={pathname.startsWith("/finance")?"active":""} href="/finance">Consultation Finance</Link>
        {me?.permissions?.includes("PROCEDURE_VIEW")&&<Link className={pathname.startsWith("/procedures")?"active":""} href="/procedures">Procedures</Link>}
        {me?.permissions?.includes("MASTER_APPROVE")&&<Link className={pathname.startsWith("/masters")?"active":""} href="/masters">Master Approvals</Link>}
        {me?.permissions?.includes("PATIENT_IMPORT")&&<Link className={pathname.startsWith("/imports")?"active":""} href="/imports">Legacy Import</Link>}
        {me?.permissions?.includes("AUDIT_VIEW")&&<Link className={pathname.startsWith("/admin")?"active":""} href="/admin">Admin Audit</Link>}
        {me?.permissions?.includes("STAFF_MANAGE")&&!me.must_change_password&&<Link className={pathname.startsWith("/staff")?"active":""} href="/staff">Staff Users</Link>}
        <Link className={pathname.startsWith("/account")?"active":""} href="/account">My Password</Link>
      </nav>
      <button className="logout" onClick={logout}>Sign out</button>
    </aside>
    <main>{me?.must_change_password&&<div className="alert warning-check">Please change your temporary password to access clinic records.</div>}{children}</main>
  </div>
}
