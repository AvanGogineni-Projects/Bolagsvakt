// Typed client for the Bolagsvakt API. Every call sends the signed-in user's token;
// a 401 signs the user out so they never sit on a page that silently fails.

export type Status = 'active' | 'in_bankruptcy' | 'in_liquidation' | 'in_reconstruction' | 'deregistered'

export interface WatchedCompany {
  org_nr: string
  name: string
  city: string | null
  status: Status
  label: string | null
  added_at: string
  probability: number | null
  times_average: number | null
  reasons: string[] | null
  fiscal_end: string | null
}

export interface CompanyEvent {
  snapshot_date: string
  org_nr: string
  name: string
  event: string
  detail: string | null
}

export interface CompanyPage {
  org_nr: string
  name: string
  legal_form: string | null
  city: string | null
  registered_on: string | null
  deregistered_on: string | null
  status: Status
  probability: number | null
  times_average: number | null
  reasons: string[] | null
  fiscal_end: string | null
  filed_on: string | null
  model_version: string | null
  events: Omit<CompanyEvent, 'org_nr' | 'name'>[]
}

export interface SearchHit {
  org_nr: string
  name: string
  city: string | null
  status: Status
}

export interface Organization {
  id: string
  name: string
  role: 'owner' | 'member'
}

export interface UploadResult {
  added: number
  already_watched: number
  unknown: string[]
  invalid: string[]
  invalid_count: number
}

const TOKEN_KEY = 'bolagsvakt_token'

export const auth = {
  token: (): string | null => localStorage.getItem(TOKEN_KEY),
  // shortcut: token in localStorage for the local dev login; Supabase's client manages it once connected
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const token = auth.token()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const res = await fetch(path, { ...init, headers })
  if (res.status === 401) {
    auth.clear()
    window.location.assign('/login')
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(res.status, body.detail ?? `Request failed (${res.status})`)
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

export const api = {
  devLogin: (email: string) =>
    call<{ access_token: string }>('/v1/dev/token', { method: 'POST', body: JSON.stringify({ email }) }),
  me: () => call<{ user_id: string; organizations: Organization[] }>('/v1/me'),
  createOrg: (name: string) =>
    call<{ id: string; name: string }>('/v1/organizations', { method: 'POST', body: JSON.stringify({ name }) }),
  watchlist: (orgId: string) => call<WatchedCompany[]>(`/v1/organizations/${orgId}/watchlist`),
  upload: (orgId: string, file: Blob) => {
    const form = new FormData()
    form.append('file', file, 'watchlist.csv')
    return call<UploadResult>(`/v1/organizations/${orgId}/watchlist`, { method: 'POST', body: form })
  },
  unwatch: (orgId: string, orgNr: string) =>
    call<void>(`/v1/organizations/${orgId}/watchlist/${orgNr}`, { method: 'DELETE' }),
  events: (orgId: string) => call<CompanyEvent[]>(`/v1/organizations/${orgId}/events`),
  company: (orgNr: string) => call<CompanyPage>(`/v1/companies/${orgNr}`),
  search: (q: string) => call<SearchHit[]>(`/v1/search?q=${encodeURIComponent(q)}`),
}

export const formatOrgNr = (n: string) => `${n.slice(0, 6)}-${n.slice(6)}`
