import { useCallback, useEffect, useRef, useState } from 'react'
import { BrowserRouter, Link, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import {
  api, auth, formatOrgNr,
  type CompanyEvent, type CompanyPage, type Organization, type SearchHit, type UploadResult, type WatchedCompany,
} from './api'
import { ErrorNote, RiskLevel, StatusBadge } from './ui'
import { eventLabel } from './labels'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<Signed><Watchlist /></Signed>} />
        <Route path="/company/:orgNr" element={<Signed><Company /></Signed>} />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </BrowserRouter>
  )
}

function Signed({ children }: { children: React.ReactNode }) {
  if (!auth.token()) return <Navigate to="/login" />
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
          <Link to="/" className="font-semibold tracking-tight">Bolagsvakt</Link>
          <Search />
          <button
            className="ml-auto whitespace-nowrap text-sm text-slate-500 hover:text-slate-900"
            onClick={() => { auth.clear(); window.location.assign('/login') }}
          >
            Sign out
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
    </div>
  )
}

function Login() {
  const [email, setEmail] = useState('')
  const [error, setError] = useState<unknown>(null)
  const navigate = useNavigate()
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      auth.set((await api.devLogin(email)).access_token)
      navigate('/')
    } catch (err) {
      setError(err)
    }
  }
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
        <div>
          <h1 className="text-lg font-semibold">Bolagsvakt</h1>
          <p className="text-sm text-slate-500">Know when a customer or supplier starts going wrong.</p>
        </div>
        <label className="block text-sm">
          <span className="text-slate-700">Email</span>
          <input
            type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 focus:border-slate-500 focus:outline-none"
          />
        </label>
        <ErrorNote error={error} />
        <button className="w-full rounded-md bg-slate-900 py-2 text-sm font-medium text-white hover:bg-slate-700">
          Sign in (local dev)
        </button>
      </form>
    </div>
  )
}

function Search() {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<SearchHit[]>([])
  const navigate = useNavigate()
  useEffect(() => {
    if (q.trim().length < 2) return
    const t = setTimeout(() => api.search(q).then(setHits).catch(() => setHits([])), 200)
    return () => clearTimeout(t)
  }, [q])
  const shown = q.trim().length < 2 ? [] : hits
  return (
    <div className="relative w-full max-w-md">
      <input
        value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search companies"
        placeholder="Search company name or org number"
        className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-slate-500 focus:outline-none"
      />
      {shown.length > 0 && (
        <ul className="absolute z-10 mt-1 w-full overflow-hidden rounded-md bg-white shadow-lg ring-1 ring-slate-200">
          {shown.map((h) => (
            <li key={h.org_nr}>
              <button
                className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-slate-50"
                onClick={() => { setQ(''); navigate(`/company/${h.org_nr}`) }}
              >
                <span className="truncate">{h.name}</span>
                <span className="shrink-0 text-xs text-slate-500">{formatOrgNr(h.org_nr)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Watchlist() {
  const [org, setOrg] = useState<Organization | null | undefined>(undefined)
  const [rows, setRows] = useState<WatchedCompany[]>([])
  const [events, setEvents] = useState<CompanyEvent[]>([])
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    api.me().then((me) => setOrg(me.organizations[0] ?? null)).catch(setError)
  }, [])
  const load = useCallback(() => {
    if (!org) return
    Promise.all([api.watchlist(org.id), api.events(org.id)])
      .then(([w, e]) => { setRows(w); setEvents(e) })
      .catch(setError)
  }, [org])
  useEffect(load, [load])

  if (org === undefined) return <ErrorNote error={error} />
  if (org === null) return <CreateOrg onCreated={setOrg} />

  const atRisk = rows.filter((r) => r.status !== 'active' || (r.times_average ?? 0) >= 5).length
  return (
    <div className="grid gap-6 xl:grid-cols-3">
      <section className="min-w-0 space-y-4 xl:col-span-2">
        <div>
          <h1 className="text-xl font-semibold">{org.name}</h1>
          <p className="text-sm text-slate-500">{rows.length} companies watched · {atRisk} need attention</p>
        </div>
        <ErrorNote error={error} />
        <Upload orgId={org.id} onDone={load} />
        {rows.length > 0 && (
          <div className="overflow-x-auto rounded-xl bg-white ring-1 ring-slate-200">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 text-xs uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-2 font-medium">Company</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Risk</th>
                  <th className="px-4 py-2 font-medium">Main reason</th>
                  <th className="px-4 py-2"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((r) => (
                  <tr key={r.org_nr} className="align-top">
                    <td className="min-w-44 px-4 py-3">
                      <Link to={`/company/${r.org_nr}`} className="font-medium hover:underline">{r.name}</Link>
                      <div className="text-xs text-slate-500">{formatOrgNr(r.org_nr)}{r.city ? ` · ${r.city}` : ''}</div>
                    </td>
                    <td className="px-4 py-3"><StatusBadge status={r.status} /></td>
                    <td className="px-4 py-3"><RiskLevel timesAverage={r.times_average} /></td>
                    <td className="px-4 py-3 text-slate-600">{r.reasons?.[0] ?? '—'}</td>
                    <td className="px-4 py-3 text-right">
                      <button
                        className="text-xs text-slate-400 hover:text-red-600"
                        onClick={() => api.unwatch(org.id, r.org_nr).then(load).catch(setError)}
                        aria-label={`Stop watching ${r.name}`}
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <aside className="space-y-3">
        <h2 className="text-sm font-semibold text-slate-700">What changed (90 days)</h2>
        {events.length === 0 ? (
          <p className="text-sm text-slate-500">No changes for your companies yet. Bolagsverket publishes weekly.</p>
        ) : (
          <ul className="space-y-2">
            {events.map((e) => (
              <li key={`${e.snapshot_date}-${e.org_nr}-${e.event}-${e.detail}`} className="rounded-lg bg-white p-3 text-sm ring-1 ring-slate-200">
                <div className="flex justify-between text-xs text-slate-500">
                  <span>{eventLabel(e.event)}</span><span>{e.snapshot_date}</span>
                </div>
                <Link to={`/company/${e.org_nr}`} className="font-medium hover:underline">{e.name}</Link>
                {e.detail && <div className="text-xs text-slate-600">{e.detail}</div>}
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  )
}

function CreateOrg({ onCreated }: { onCreated: (o: Organization) => void }) {
  const [name, setName] = useState('')
  const [error, setError] = useState<unknown>(null)
  return (
    <form
      className="mx-auto max-w-md space-y-3 rounded-xl bg-white p-6 ring-1 ring-slate-200"
      onSubmit={async (e) => {
        e.preventDefault()
        try {
          const o = await api.createOrg(name)
          onCreated({ ...o, role: 'owner' })
        } catch (err) {
          setError(err)
        }
      }}
    >
      <h1 className="text-lg font-semibold">Name your company</h1>
      <p className="text-sm text-slate-500">Your watchlist belongs to your company, so colleagues can share it later.</p>
      <input
        required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} aria-label="Company name"
        className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
      />
      <ErrorNote error={error} />
      <button className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700">Continue</button>
    </form>
  )
}

function Upload({ orgId, onDone }: { orgId: string; onDone: () => void }) {
  const [text, setText] = useState('')
  const [result, setResult] = useState<UploadResult | null>(null)
  const [error, setError] = useState<unknown>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const send = async (blob: Blob) => {
    setError(null)
    try {
      setResult(await api.upload(orgId, blob))
      setText('')
      onDone()
    } catch (err) {
      setError(err)
    }
  }
  return (
    <div className="space-y-2 rounded-xl bg-white p-4 ring-1 ring-slate-200">
      <label className="block text-sm font-medium text-slate-700" htmlFor="orgnrs">Add customers or suppliers</label>
      <textarea
        id="orgnrs" rows={3} value={text} onChange={(e) => setText(e.target.value)}
        placeholder={'Paste organisation numbers, one per line\n556000-0001'}
        className="w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm focus:border-slate-500 focus:outline-none"
      />
      <div className="flex items-center gap-2">
        <button
          disabled={!text.trim()} onClick={() => send(new Blob([text], { type: 'text/csv' }))}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-40"
        >
          Add
        </button>
        <button onClick={() => fileInput.current?.click()} className="rounded-md px-3 py-1.5 text-sm ring-1 ring-slate-300 hover:bg-slate-50">
          Upload CSV
        </button>
        <input
          ref={fileInput} type="file" accept=".csv,.txt,text/csv" className="hidden" aria-label="CSV file"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) send(f); e.target.value = '' }}
        />
      </div>
      <ErrorNote error={error} />
      {result && (
        <p className="text-sm text-slate-600">
          Added {result.added}
          {result.already_watched > 0 && `, ${result.already_watched} already watched`}
          {result.unknown.length > 0 &&
            `, ${result.unknown.length} not found in the registry (${result.unknown.slice(0, 3).map(formatOrgNr).join(', ')}${result.unknown.length > 3 ? '…' : ''})`}
          {result.invalid_count > 0 && `, ${result.invalid_count} not valid organisation numbers`}.
        </p>
      )}
    </div>
  )
}

function Company() {
  const { orgNr = '' } = useParams()
  const [state, setState] = useState<{ orgNr: string; c?: CompanyPage; error?: unknown }>({ orgNr })
  useEffect(() => {
    api.company(orgNr).then((c) => setState({ orgNr, c })).catch((error) => setState({ orgNr, error }))
  }, [orgNr])
  const c = state.orgNr === orgNr ? state.c : undefined
  if (!c) return <ErrorNote error={state.orgNr === orgNr ? state.error : null} />
  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold">{c.name}</h1>
          <StatusBadge status={c.status} />
        </div>
        <p className="text-sm text-slate-500">
          {formatOrgNr(c.org_nr)}{c.city ? ` · ${c.city}` : ''}{c.registered_on ? ` · registered ${c.registered_on}` : ''}
        </p>
      </div>
      <section className="space-y-3 rounded-xl bg-white p-5 ring-1 ring-slate-200">
        <h2 className="text-sm font-semibold text-slate-700">Bankruptcy risk</h2>
        <RiskLevel timesAverage={c.times_average} />
        {c.reasons && c.reasons.length > 0 ? (
          <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
            {c.reasons.map((r) => <li key={r}>{r}</li>)}
          </ul>
        ) : (
          c.times_average !== null && <p className="text-sm text-slate-600">No warning signs in the latest annual report.</p>
        )}
        {c.fiscal_end && (
          <p className="text-xs text-slate-500">
            Based on the annual report for the year ending {c.fiscal_end}, filed {c.filed_on} · model {c.model_version}
          </p>
        )}
      </section>
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-slate-700">Registry history</h2>
        {c.events.length === 0 ? (
          <p className="text-sm text-slate-500">No changes recorded since Bolagsvakt started watching.</p>
        ) : (
          <ul className="divide-y divide-slate-100 rounded-xl bg-white ring-1 ring-slate-200">
            {c.events.map((e) => (
              <li key={`${e.snapshot_date}-${e.event}-${e.detail}`} className="flex justify-between gap-4 px-4 py-2 text-sm">
                <span>{eventLabel(e.event)}{e.detail ? `: ${e.detail}` : ''}</span>
                <span className="shrink-0 text-slate-500">{e.snapshot_date}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
