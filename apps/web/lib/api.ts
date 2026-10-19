export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = typeof window !== "undefined" ? localStorage.getItem("aastha_token") : null;
  const headers = new Headers(init?.headers || {});
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_URL}${path}`, {...init, headers, cache: "no-store"});
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body?.detail;
    const message = Array.isArray(detail) ? detail.map((x:{loc?:string[];msg?:string})=>`${x.loc?.slice(1).join(" ")}: ${x.msg}`).join("; ") : typeof detail === "string" ? detail : detail?.message || `Request failed: ${response.status}`;
    const error = new Error(message) as Error & {status?:number;detail?:unknown};
    error.status = response.status;
    error.detail = detail;
    throw error;
  }
  return response.json();
}

export async function apiUpload<T>(path:string, form:FormData):Promise<T>{
  const token = typeof window !== "undefined" ? localStorage.getItem("aastha_token") : null;
  const headers = new Headers();
  if(token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_URL}${path}`,{method:"POST",headers,body:form,cache:"no-store"});
  if(!response.ok){
    const body=await response.json().catch(()=>({}));
    const detail=body?.detail;const message=typeof detail==="string"?detail:detail?.message||`Request failed: ${response.status}`;
    throw new Error(message);
  }
  return response.json();
}
