"use client";
import AppointmentBooking from "./AppointmentBooking";
import type {Bootstrap,Lead} from "../lib/types";
export default function LeadBooking({lead,meta,onSaved,onClose}:{lead:Lead;meta:Bootstrap;onSaved:()=>Promise<void>;onClose:()=>void}){
  const branches=[...meta.branches].sort((a,b)=>Number(b.id===lead.preferred_branch_id)-Number(a.id===lead.preferred_branch_id));
  return <AppointmentBooking party={{lead_id:lead.lead_id,name:lead.lead_name}} meta={{...meta,branches}} onSaved={onSaved} onClose={onClose}/>;
}
