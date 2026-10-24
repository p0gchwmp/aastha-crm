"use client";
import {useEffect,useState} from "react";
import {apiFetch} from "../lib/api";

export type SelectedDiagnosis={diagnosis_id:string;name:string;category:string;is_primary:boolean};
export type CatalogueDiagnosis=SelectedDiagnosis&{active:boolean;requires_review:boolean;row_version:number};

export default function DiagnosisPicker({value,onChange,disabled}:{value:SelectedDiagnosis[];onChange:(value:SelectedDiagnosis[])=>void;disabled:boolean}){
 const [query,setQuery]=useState(""),[rows,setRows]=useState<CatalogueDiagnosis[]>([]),[error,setError]=useState(""),[loading,setLoading]=useState(false);
 useEffect(()=>{let live=true;if(disabled)return;const timer=setTimeout(()=>{setLoading(true);apiFetch<CatalogueDiagnosis[]>("/diagnoses?q="+encodeURIComponent(query)+"&limit=50").then(x=>{if(live){setRows(x);setError("")}}).catch(e=>{if(live)setError(e.message)}).finally(()=>{if(live)setLoading(false)})},200);return()=>{live=false;clearTimeout(timer)}},[query,disabled]);
 const remove=(id:string)=>{const next=value.filter(d=>d.diagnosis_id!==id);if(next.length&&!next.some(d=>d.is_primary))next[0]={...next[0],is_primary:true};onChange(next)};
 return <section aria-label="Visit diagnoses"><h3>Diagnoses</h3><p>Choose up to 20 diagnoses and mark one as primary. Save Notes to store your selection.</p>
 {value.length?<ul>{value.map(d=><li key={d.diagnosis_id}><b>{d.name}</b> · {d.category} {disabled?(d.is_primary?"(Primary)":""):<><label><input type="radio" name="primary-diagnosis" aria-label={"Primary diagnosis "+d.name} checked={d.is_primary} onChange={()=>onChange(value.map(x=>({...x,is_primary:x.diagnosis_id===d.diagnosis_id})))}/> Primary</label><button type="button" onClick={()=>remove(d.diagnosis_id)}>Remove {d.name}</button></>}</li>)}</ul>:<p>No structured diagnoses recorded.</p>}
 {!disabled&&<><label>Search diagnoses <input value={query} maxLength={240} onChange={e=>setQuery(e.target.value)}/></label>{loading&&<p>Searching…</p>}{error&&<p role="alert">{error}</p>}<ul>{rows.filter(d=>!value.some(x=>x.diagnosis_id===d.diagnosis_id)).map(d=><li key={d.diagnosis_id}>{d.name} · {d.category} <button type="button" disabled={value.length>=20} onClick={()=>onChange([...value,{diagnosis_id:d.diagnosis_id,name:d.name,category:d.category,is_primary:value.length===0}])}>Add {d.name}</button></li>)}</ul>{!loading&&!rows.length&&!error&&<p>No matching diagnoses. Add a new entry in Diagnosis Master if needed.</p>}<p>Showing up to 50 matches. Search to narrow the list.</p></>}
 </section>
}
