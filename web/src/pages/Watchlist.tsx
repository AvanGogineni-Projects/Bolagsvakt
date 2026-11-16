import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, formatOrgNr, type CompanyEvent, type Organization, type UploadResult, type WatchedCompany } from '../api'
import {
  SAMPLE_COMPANIES, eventLabel, formatDate, mainReason, needsAttention, outcomeKnown, riskBand,
} from '../labels'
import { Button, ErrorNote, RiskLadder, SkeletonRows, StatusStamp } from '../ui'
import { CreateOrg } from './Login'

type Filter = 'all' | 'attention' | 'known'

export function Watchlist() {
  const [org, setOrg] = useState<Organization | null | undefined>(undefined)
  const [rows, setRows] = useState<WatchedCompany[] | null>(null)
  const [events, setEvents] = useState<CompanyEvent[]>([])
  const [error, setError] = useState<unknown>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const [adding, setAdding] = useState(false)

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

  if (org === undefined) return error ? <ErrorNote error={error} /> : <SkeletonRows />
  if (org === null) return <CreateOrg onCreated={setOrg} />

  const all = rows ?? []
  const counts = {
    watched: all.length,
    known: all.filter((r) => outcomeKnown(r.status)).length,
    high: all.filter((r) => !outcomeKnown(r.status) && ['high', 'severe'].includes(riskBand(r.times_average) ?? '')).length,
    elevated: all.filter((r) => !outcomeKnown(r.status) && riskBand(r.times_average) === 'elevated').length,
  }
  const attention = all.filter((r) => needsAttention(r.status, r.times_average)).length
  const shown = all.filter((r) =>
    filter === 'all' ? true : filter === 'known' ? outcomeKnown(r.status) : needsAttention(r.status, r.times_average))
  const empty = rows !== null && all.length === 0

  return (
    <div className="space-y-10">
      <header className="flex flex-wrap items-end justify-between gap-6">
        <div className="max-w-2xl">
          <p className="eyebrow">Watchlist · {org.name}</p>
          <h1 className="mt-3 font-serif text-4xl leading-tight tracking-tight sm:text-5xl">
            {rows === null ? 'Loading your companies…'
              : empty ? 'Start with the companies that owe you money.'
              : attention === 0 ? <>All {counts.watched} companies look <em>steady</em>.</>
              : <>{counts.watched} companies, <span className="text-signal">{attention} need{attention === 1 ? 's' : ''} attention</span>.</>}
          </h1>
        </div>
        {!empty && rows !== null && (
          <Button variant={adding ? 'quiet' : 'primary'} onClick={() => setAdding((a) => !a)}>
            {adding ? 'Close' : '+ Add companies'}
          </Button>
        )}
      </header>

      <ErrorNote error={error} />

      {(adding || empty) && (
        // Stays open after an upload with problems, so its "not valid" / "not found" lines stay visible.
        <AddCompanies orgId={org.id} intro={empty} onDone={(problems) => { load(); setAdding(problems) }} />
      )}

      {!empty && (
        <>
          <dl className="grid grid-cols-2 border-y border-rule-strong sm:grid-cols-4">
            <Kpi label="Watched" value={counts.watched} />
            <Kpi label="Outcome known" value={counts.known} tone={counts.known ? 'signal' : undefined}
                 hint="In bankruptcy, liquidation or reconstruction, or deregistered" />
            <Kpi label="High risk" value={counts.high} tone={counts.high ? 'signal' : undefined} hint="5× the average risk or more" />
            <Kpi label="Elevated" value={counts.elevated} tone={counts.elevated ? 'ochre' : undefined} hint="2–5× the average risk" />
          </dl>

          <div className="grid gap-10 xl:grid-cols-[1fr_260px]">
            <section className="min-w-0">
              <div className="mb-3 flex items-center justify-between gap-4">
                <div role="tablist" aria-label="Filter companies" className="flex gap-5">
                  {([['all', 'All', counts.watched], ['attention', 'Needs attention', attention], ['known', 'Outcome known', counts.known]] as const)
                    .map(([key, label, n]) => (
                      <button key={key} role="tab" aria-selected={filter === key} onClick={() => setFilter(key)}
                              className={`border-b-2 pb-1.5 text-sm transition-colors ${filter === key ? 'border-ink text-ink' : 'border-transparent text-ink-3 hover:text-ink'}`}>
                        {label} <span className="font-mono text-xs tabular text-ink-3">{n}</span>
                      </button>
                    ))}
                </div>
              </div>
              {rows === null ? <SkeletonRows /> : shown.length === 0
                ? <p className="border-t border-rule py-10 text-sm text-ink-3">Nothing here. Good news, usually.</p>
                : <CompanyTable rows={shown} onRemove={(nr) => api.unwatch(org.id, nr).then(load).catch(setError)} />}
            </section>
            <ChangeLog events={events} />
          </div>
        </>
      )}
    </div>
  )
}

function Kpi({ label, value, tone, hint }: { label: string; value: number; tone?: 'signal' | 'ochre'; hint?: string }) {
  const color = tone === 'signal' ? 'text-signal' : tone === 'ochre' ? 'text-ochre' : 'text-ink'
  return (
    <div className="border-rule px-1 py-4 sm:px-5 [&:not(:first-child)]:sm:border-l [&:nth-child(n+3)]:border-t sm:[&:nth-child(n+3)]:border-t-0" title={hint}>
      <dt className="eyebrow">{label}</dt>
      <dd className={`mt-1 font-serif text-4xl tabular ${color}`}>{value}</dd>
    </div>
  )
}

function CompanyTable({ rows, onRemove }: { rows: WatchedCompany[]; onRemove: (orgNr: string) => void }) {
  const navigate = useNavigate()
  return (
    <>
      {/* Desktop: a ruled register. */}
      <table className="hidden w-full border-collapse text-left md:table">
        <thead>
          <tr className="border-y border-rule">
            {['Company', 'Status', 'Risk', 'Warning sign', 'Report'].map((h) => (
              <th key={h} scope="col" className="eyebrow whitespace-nowrap py-2.5 pr-4 font-normal">{h}</th>
            ))}
            <th scope="col" className="py-2.5"><span className="sr-only">Remove</span></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const reason = mainReason(r.status, r.times_average, r.reasons)
            const quiet = reason === 'No major warning signs' || reason.startsWith('No digital')
            return (
              <tr key={r.org_nr} onClick={() => navigate(`/company/${r.org_nr}`)}
                  className="group cursor-pointer border-b border-rule align-top transition-colors hover:bg-card">
                <td className="min-w-[230px] py-4 pr-4">
                  <Link to={`/company/${r.org_nr}`} onClick={(e) => e.stopPropagation()}
                        className="font-serif text-[17px] leading-snug text-ink decoration-rule underline-offset-4 group-hover:underline">
                    {r.name}
                  </Link>
                  <div className="mt-0.5 font-mono text-[11px] text-ink-3">{formatOrgNr(r.org_nr)}{r.city ? ` · ${r.city}` : ''}</div>
                </td>
                <td className="py-4 pr-4 pt-[18px]"><StatusStamp status={r.status} /></td>
                <td className="py-4 pr-4 pt-[19px]"><RiskLadder timesAverage={r.times_average} status={r.status} /></td>
                <td className={`max-w-[240px] py-4 pr-4 text-[13px] leading-snug ${quiet ? 'text-ink-3' : 'text-ink-2'}`}>{reason}</td>
                <td className="whitespace-nowrap py-4 pr-2 pt-[18px] font-mono text-[11px] text-ink-3">
                  {r.fiscal_end ? `FY ${r.fiscal_end.slice(0, 4)}` : '—'}
                </td>
                <td className="py-4 pt-[15px] text-right">
                  <button onClick={(e) => { e.stopPropagation(); onRemove(r.org_nr) }} aria-label={`Stop watching ${r.name}`}
                          className="px-1 text-lg leading-none text-ink-3 opacity-0 transition-opacity hover:text-signal focus:opacity-100 group-hover:opacity-100">
                    ×
                  </button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>

      {/* Phone: one card per company. */}
      <ul className="divide-y divide-rule border-y border-rule md:hidden">
        {rows.map((r) => (
          <li key={r.org_nr}>
            <Link to={`/company/${r.org_nr}`} className="block py-4">
              <div className="flex items-start justify-between gap-3">
                <span className="font-serif text-lg leading-snug">{r.name}</span>
                <StatusStamp status={r.status} />
              </div>
              <div className="mt-0.5 font-mono text-[11px] text-ink-3">{formatOrgNr(r.org_nr)}{r.city ? ` · ${r.city}` : ''}</div>
              <div className="mt-3"><RiskLadder timesAverage={r.times_average} status={r.status} /></div>
              <p className="mt-2 text-sm text-ink-2">{mainReason(r.status, r.times_average, r.reasons)}</p>
            </Link>
          </li>
        ))}
      </ul>
    </>
  )
}

function ChangeLog({ events }: { events: CompanyEvent[] }) {
  return (
    <aside aria-labelledby="changes-heading">
      <h2 id="changes-heading" className="eyebrow border-b border-rule pb-2.5">Changes · last 90 days</h2>
      {events.length === 0 ? (
        <p className="pt-4 text-sm leading-relaxed text-ink-3">
          Nothing yet. Bolagsverket publishes the register weekly; the first changes appear after the next snapshot.
        </p>
      ) : (
        <ol className="relative mt-4 space-y-5 border-l border-rule pl-4">
          {events.map((e) => (
            <li key={`${e.snapshot_date}-${e.org_nr}-${e.event}-${e.detail}`} className="relative">
              <span className={`absolute -left-[21px] top-1.5 h-2 w-2 rounded-full ${e.event.startsWith('proceeding_started') || e.event === 'deregistered' ? 'bg-signal' : 'bg-ink-3'}`} aria-hidden="true" />
              <p className="font-mono text-[11px] text-ink-3">{formatDate(e.snapshot_date)}</p>
              <p className="text-sm text-ink">{eventLabel(e.event)}</p>
              <Link to={`/company/${e.org_nr}`} className="font-serif text-[15px] text-ink-2 hover:text-ink hover:underline">{e.name}</Link>
              {e.detail && <p className="mt-0.5 text-xs text-ink-3">{e.detail}</p>}
            </li>
          ))}
        </ol>
      )}
    </aside>
  )
}

function AddCompanies({ orgId, intro, onDone }: { orgId: string; intro: boolean; onDone: (problems: boolean) => void }) {
  const [text, setText] = useState('')
  const [result, setResult] = useState<UploadResult | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const send = async (blob: Blob) => {
    setError(null)
    setBusy(true)
    try {
      const r = await api.upload(orgId, blob)
      setResult(r)
      setText('')
      if (r.added > 0) onDone(r.invalid_count > 0 || r.unknown.length > 0)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }
  return (
    <section className="grid gap-8 border border-rule bg-card p-5 sm:p-7 lg:grid-cols-[1fr_1.2fr]">
      <div>
        <p className="eyebrow">{intro ? 'Step 2 of 2' : 'Add companies'}</p>
        <h2 className="mt-2 font-serif text-2xl tracking-tight">Paste organisation numbers.</h2>
        <p className="mt-2 text-sm leading-relaxed text-ink-2">
          One per line, with or without the dash, or upload a CSV export from your accounting system.
          Typos are caught by the check digit.
        </p>
        {intro && (
          <div className="mt-6 border-t border-rule pt-5">
            <p className="text-sm text-ink-2">Just looking around?</p>
            <Button variant="quiet" className="mt-2" disabled={busy}
                    onClick={() => send(new Blob([SAMPLE_COMPANIES.join('\n')], { type: 'text/csv' }))}>
              Load 8 sample companies
            </Button>
            <p className="mt-2 text-xs text-ink-3">Real companies, picked to show every kind of result.</p>
          </div>
        )}
      </div>
      <div>
        <label htmlFor="orgnrs" className="eyebrow">Organisation numbers</label>
        <textarea
          id="orgnrs" rows={6} value={text} onChange={(e) => setText(e.target.value)}
          placeholder={'556012-5790\n5593673121\n…'}
          className="mt-2 w-full resize-y rounded-[4px] border border-rule bg-paper px-3 py-2.5 font-mono text-sm text-ink placeholder:text-ink-3 focus:border-ink-3 focus:outline-none"
        />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button disabled={!text.trim() || busy} onClick={() => send(new Blob([text], { type: 'text/csv' }))}>
            {busy ? 'Adding…' : 'Add to watchlist'}
          </Button>
          <Button variant="quiet" disabled={busy} onClick={() => fileInput.current?.click()}>Upload CSV</Button>
          <input ref={fileInput} type="file" accept=".csv,.txt,text/csv" className="hidden" aria-label="CSV file"
                 onChange={(e) => { const f = e.target.files?.[0]; if (f) send(f); e.target.value = '' }} />
        </div>
        <div className="mt-3"><ErrorNote error={error} /></div>
        {result && <UploadSummary result={result} />}
      </div>
    </section>
  )
}

function UploadSummary({ result }: { result: UploadResult }) {
  const parts = [
    [result.added, 'added', 'text-moss'],
    [result.already_watched, 'already watched', 'text-ink-3'],
    [result.unknown.length, 'not in the register', 'text-ochre'],
    [result.invalid_count, 'not valid numbers', 'text-signal'],
  ] as const
  return (
    <div className="mt-3 border-t border-rule pt-3">
      <p className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs">
        {parts.filter(([n]) => n > 0).map(([n, label, color]) => (
          <span key={label} className={color}><span className="tabular">{n}</span> {label}</span>
        ))}
      </p>
      {result.unknown.length > 0 && (
        <p className="mt-1 font-mono text-[11px] text-ink-3">
          Not found: {result.unknown.slice(0, 5).map(formatOrgNr).join(', ')}{result.unknown.length > 5 ? ' …' : ''}
        </p>
      )}
    </div>
  )
}
