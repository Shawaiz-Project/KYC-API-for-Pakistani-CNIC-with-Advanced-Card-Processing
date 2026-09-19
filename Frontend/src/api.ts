export type Outcome = 'pending' | 'checks_passed' | 'checks_failed' | 'needs_recapture' | 'needs_review'
export type ApplicationState = 'draft' | 'queued' | 'processing' | 'completed' | 'failed'

export interface Membership { organization_id: string; organization: string; role: 'admin' | 'reviewer' | 'applicant' | 'api_client' }
export interface User { type: 'user'; id: number; username: string; email: string; memberships: Membership[] }
export interface CheckResult { detector: string; execution_status: string; status: string; score: null | {value: number; type: string; calibrated_probability: false}; threshold: number | null; reason_codes: string[]; evidence: Record<string, unknown>[]; model_version: string | null; detector_version: string; execution_ms: number; experimental: boolean }
export interface Artifact { id: string; kind: string; content_type: string; byte_size: number; media_url: string; dimensions: {width: number; height: number} }
export interface KycApplication { id: string; display_id: string; external_reference: string; state: ApplicationState; outcome: Outcome; outcome_reasons: string[]; workflow: string; policy_version: string; version: number; submitted_at: string | null; created_at: string; completed_at: string | null; assigned_to: string | null; artifacts?: Artifact[]; fields?: Record<string, {raw: {value: string | null; normalized_value: string | null} | null; current: {value: string | null; source: string; revision_id: number} | null}>; checks?: CheckResult[]; authoritative_verification?: {status: string; reason_code: string} }

const BASE = import.meta.env.VITE_API_BASE || '/api/v2'

function csrfCookie() {
  return document.cookie.split('; ').find((item) => item.startsWith('csrftoken='))?.split('=')[1] || ''
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const isForm = init.body instanceof FormData
  const response = await fetch(`${BASE}${path}`, {
    credentials: 'include',
    cache: 'no-store',
    ...init,
    headers: {...(!isForm && init.body ? {'Content-Type': 'application/json'} : {}), ...(init.method && init.method !== 'GET' ? {'X-CSRFToken': csrfCookie()} : {}), ...init.headers},
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body?.error?.message || `Request failed (${response.status})`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export async function ensureCsrf() { await api<{csrf_token: string}>('/auth/csrf') }
export const authApi = {
  me: () => api<User>('/auth/me'),
  signIn: async (email: string, password: string) => { await ensureCsrf(); return api<User>('/auth/sign-in', {method: 'POST', body: JSON.stringify({email, password})}) },
  signOut: () => api<void>('/auth/sign-out', {method: 'POST'}),
}
export const applicationsApi = {
  list: () => api<{count: number; results: KycApplication[]}>('/applications'),
  get: (id: string) => api<KycApplication>(`/applications/${id}`),
  create: (externalReference = '') => api<KycApplication>('/applications', {method: 'POST', body: JSON.stringify({external_reference: externalReference})}),
  upload: (id: string, kind: 'front'|'back'|'selfie', file: File) => { const body = new FormData(); body.append('kind', kind); body.append('file', file); return api<{artifact: Artifact; duplicate_signals?: any[]; extracted_fields?: Record<string, {raw_value: string|null; normalized_value: string|null; source: string}>}>(`/applications/${id}/artifacts`, {method: 'POST', body}) },
  detectCnic: (file: File, side = 'auto') => { const body = new FormData(); body.append('file', file); body.append('side', side); return api<{application_id: string; display_id: string; detected_side: string; extracted_fields: Record<string, any>}>(`/cnic/detect`, {method: 'POST', body}) },
  consentAndSubmit: async (id: string) => {
    await api(`/applications/${id}/consent`, {method: 'POST', body: JSON.stringify({accepted:true, policy_version:'phase3-consent-v1'})})
    return api<KycApplication>(`/applications/${id}/submit`, {method: 'POST', body: JSON.stringify({})})
  },
  correct: (id: string, field_name: string, value: string, reason: string) => api(`/applications/${id}/corrections`, {method: 'POST', body: JSON.stringify({field_name, value, reason})}),
  decide: (id: string, outcome: Outcome, reason: string, notes = '') => api(`/applications/${id}/decisions`, {method: 'POST', body: JSON.stringify({outcome, reason, notes})}),
  assign: (id:string,username:string)=>api<{assigned_to:string;version:number}>(`/applications/${id}/assignment`,{method:'POST',body:JSON.stringify({username})}),
  livenessStart: (id: string) => api<{id:string;actions:string[];expires_at:string;challenge_token:string;notice:string}>(`/applications/${id}/liveness-sessions`, {method:'POST',body:JSON.stringify({})}),
  livenessAlternative: (sessionId:string,challenge_token:string) => api<{state:string;manual_review:boolean}>(`/liveness-sessions/${sessionId}/complete`, {method:'POST',body:JSON.stringify({challenge_token,manual_review:true})}),
}

export interface APIKeyRecord {id:number;name:string;prefix:string;scopes:string[];is_active:boolean;quota_per_minute:number;usage_count:number;last_used_at:string|null;created_at:string}
export const apiKeysApi={
  list:()=>api<{results:APIKeyRecord[]}>('/api-keys'),
  create:(name:string,scopes:string[],quota_per_minute:number)=>api<{id:number;prefix:string;api_key:string;notice:string}>('/api-keys',{method:'POST',body:JSON.stringify({name,scopes,quota_per_minute})}),
  action:(id:number,action:'revoke'|'rotate')=>api<{revoked:boolean;replacement_id?:number;api_key?:string;notice?:string}>(`/api-keys/${id}/actions`,{method:'POST',body:JSON.stringify({action})}),
}
export interface WebhookRecord {id:number;url:string;event_types:string[];is_active:boolean;created_at:string}
export const webhooksApi={
  list:()=>api<{results:WebhookRecord[]}>('/webhooks'),
  create:(url:string)=>api<{id:number;url:string;secret:string;notice:string}>('/webhooks',{method:'POST',body:JSON.stringify({url,event_types:['application.completed']})}),
}

export const demoApplications: KycApplication[] = [
  {id:'demo-1',display_id:'APP-001',external_reference:'DEMO-001',state:'processing',outcome:'pending',outcome_reasons:[],workflow:'cnic_standard',policy_version:'phase2-policy-v1',version:1,submitted_at:new Date().toISOString(),created_at:new Date().toISOString(),completed_at:null,assigned_to:'A. Siddiqui'},
  {id:'demo-2',display_id:'APP-002',external_reference:'DEMO-002',state:'completed',outcome:'needs_review',outcome_reasons:['required_check_unavailable:face_comparison'],workflow:'cnic_standard',policy_version:'phase2-policy-v1',version:2,submitted_at:new Date().toISOString(),created_at:new Date().toISOString(),completed_at:new Date().toISOString(),assigned_to:'R. Khan'},
  {id:'demo-3',display_id:'APP-003',external_reference:'DEMO-003',state:'completed',outcome:'checks_passed',outcome_reasons:['all_required_checks_passed'],workflow:'cnic_standard',policy_version:'phase2-policy-v1',version:2,submitted_at:new Date().toISOString(),created_at:new Date().toISOString(),completed_at:new Date().toISOString(),assigned_to:'F. Malik'},
  {id:'demo-4',display_id:'APP-004',external_reference:'DEMO-004',state:'completed',outcome:'needs_recapture',outcome_reasons:['selfie_blurry'],workflow:'cnic_standard',policy_version:'phase2-policy-v1',version:2,submitted_at:new Date().toISOString(),created_at:new Date().toISOString(),completed_at:new Date().toISOString(),assigned_to:null},
]
