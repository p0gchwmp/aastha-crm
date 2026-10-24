"use client";
import {useEffect,useRef,useState} from "react";
import {apiFetch} from "../lib/api";

export type SelectedDiagnosis={diagnosis_id:string;name:string;category:string;is_primary:boolean};
export type CatalogueDiagnosis=SelectedDiagnosis&{active:boolean;requires_review:boolean;row_version:number};

export default function DiagnosisPicker({value,onChange,disabled}:{value:SelectedDiagnosis[];onChange:(value:SelectedDiagnosis[])=>void;disabled:boolean}){
 const [query,setQuery]=useState(""),[rows,setRows]=useState<CatalogueDiagnosis[]>([]),[error,setError]=useState(""),[loading,setLoading]=useState(false);
 const search=useRef<HTMLInputElement>(null);
 const term=query.trim();
 useEffect(()=>{let live=true;setRows([]);setError("");setLoading(false);if(disabled||term.length<2)return;setLoading(true);const timer=setTimeout(()=>{apiFetch<CatalogueDiagnosis[]>("/diagnoses?q="+encodeURIComponent(term)+"&limit=10").then(x=>{if(live)setRows(x)}).catch(e=>{if(live)setError(e.message)}).finally(()=>{if(live)setLoading(false)})},200);return()=>{live=false;clearTimeout(timer)}},[term,disabled]);
 const remove=(id:string)=>{const next=value.filter(d=>d.diagnosis_id!==id);if(next.length&&!next.some(d=>d.is_primary))next[0]={...next[0],is_primary:true};onChange(next)};
 const add=(d:CatalogueDiagnosis)=>{if(value.length>=20||value.some(x=>x.diagnosis_id===d.diagnosis_id))return;onChange([...value,{diagnosis_id:d.diagnosis_id,name:d.name,category:d.category,is_primary:value.length===0}]);setQuery("");setRows([]);setError("");search.current?.focus()};
 const matches=rows.filter(d=>!value.some(x=>x.diagnosis_id===d.diagnosis_id));
 return <section className="diagnosis-picker" aria-label="Visit diagnoses"><div className="diagnosis-heading"><h3>Diagnoses</h3><span className="badge">{value.length} selected</span></div>
 <p className="diagnosis-help">{disabled?"Recorded diagnoses for this consultation.":"Choose diagnoses, mark one as primary, then Save Notes. Maximum 20 diagnoses."}</p>
 {value.length?<div className="diagnosis-table-wrap"><table className="diagnosis-table"><thead><tr><th scope="col">Diagnosis</th><th scope="col">Primary</th>{!disabled&&<th scope="col">Action</th>}</tr></thead><tbody>{value.map(d=><tr key={d.diagnosis_id}><td><strong>{d.name}</strong><span className="diagnosis-category">{d.category}</span></td><td>{disabled?(d.is_primary?<span className="badge">Primary</span>:"—"):<label className="diagnosis-primary"><input type="radio" name="primary-diagnosis" aria-label={"Primary diagnosis "+d.name} checked={d.is_primary} onChange={()=>onChange(value.map(x=>({...x,is_primary:x.diagnosis_id===d.diagnosis_id})))}/><span>Primary</span></label>}</td>{!disabled&&<td><button className="ghost" type="button" aria-label={"Remove "+d.name} onClick={()=>remove(d.diagnosis_id)}>Remove</button></td>}</tr>)}</tbody></table></div>:<p className="diagnosis-help">No structured diagnoses recorded.</p>}
 {!disabled&&<div className="diagnosis-search"><label htmlFor="diagnosis-search">Search diagnoses</label><input ref={search} id="diagnosis-search" value={query} placeholder="Type at least 2 letters, e.g. acne" maxLength={240} autoComplete="off" aria-describedby="diagnosis-search-help" disabled={value.length>=20} onChange={e=>{setQuery(e.target.value);setRows([]);setError("")}} onKeyDown={e=>{if(e.key==="Escape"){setQuery("");setRows([])}}}/><p id="diagnosis-search-help" className="diagnosis-help">{value.length>=20?"Maximum reached. Remove a diagnosis to choose another.":"Search by diagnosis or category. Suggestions close after adding a diagnosis."}</p>
 {term.length>=2&&<div className="diagnosis-results" aria-label="Diagnosis suggestions">{loading?<p role="status">Searching…</p>:error?<p role="alert">{error}</p>:matches.length?<><ul>{matches.map(d=><li key={d.diagnosis_id}><div><strong>{d.name}</strong><span className="diagnosis-category">{d.category}</span></div><button type="button" aria-label={"Add "+d.name} onClick={()=>add(d)}>Add</button></li>)}</ul><p className="diagnosis-help">Up to 10 matches. Keep typing to narrow your search.</p></>:<p>No matching unselected diagnoses. Try a different search or add an entry in Diagnosis Master.</p>}</div>}
 </div>}
 </section>
}
