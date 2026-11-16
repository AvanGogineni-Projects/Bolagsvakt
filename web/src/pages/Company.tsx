import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, formatOrgNr, type CompanyPage } from '../api'
import { STATUS_LABEL, eventLabel, formatDate, outcomeKnown, riskBand } from '../labels'
import { Button, ErrorNote, RiskLadder, SkeletonRows, StatusStamp } from '../ui'

const LEGAL_FORM: Record<string, string> = {
  'AB-ORGFO': 'Limited company (AB)',
  'BRF-ORGFO': 'Housing co-operative',
  'HB-ORGFO': 'Trading partnership',
  'KB-ORGFO': 'Limited partnership',
  'EK-ORGFO': 'Economic association',
}

export function Company() {
  const { orgNr = '' } = useParams()
  const [state, setState] = useState<{ orgNr: string; c?: CompanyPage; error?: unknown }>({ orgNr })
  useEffect(() => {
    api.company(orgNr).then((c) => setState({ orgNr, c })).catch((error) => setState({ orgNr, error }))
  }, [orgNr])
  const current = state.orgNr === orgNr
  const c = current ? state.c : undefined
  if (!c) return current && state.error ? <ErrorNote error={state.error} /> : <SkeletonRows rows={3} />

  const known = outcomeKnown(c.status)
  const band = riskBand(c.times_average)
  const calm = band === 'low' || band === 'normal'
  const reasons = c.reasons ?? []

  return (
    <article className="space-y-10">
      <nav><Link to="/" className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-3 hover:text-ink">← Watchlist</Link></nav>

      <header className="border-b border-rule-strong pb-8">
        <p className="eyebrow">
          {formatOrgNr(c.org_nr)}
          {c.legal_form ? ` · ${LEGAL_FORM[c.legal_form] ?? c.legal_form}` : ''}
          {c.city ? ` · ${c.city}` : ''}
        </p>
        <div className="mt-3 flex flex-wrap items-start justify-between gap-6">
          <div className="min-w-0">
            <h1 className="font-serif text-4xl leading-[1.05] tracking-tight sm:text-6xl">{c.name}</h1>
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <StatusStamp status={c.status} />
              {c.registered_on && <span className="font-mono text-xs text-ink-3">Registered {formatDate(c.registered_on)}</span>}
            </div>
          </div>
          <WatchButton orgNr={c.org_nr} />
        </div>
      </header>

      <div className="grid gap-12 lg:grid-cols-[1fr_320px]">
        <section aria-labelledby="risk-heading">
          <h2 id="risk-heading" className="eyebrow">Bankruptcy risk</h2>
          {known ? (
            <div className="mt-4 border-l-2 border-signal pl-5">
              <p className="font-serif text-3xl tracking-tight sm:text-4xl">Outcome known: {STATUS_LABEL[c.status].toLowerCase()}.</p>
              <p className="mt-3 max-w-xl text-[15px] leading-relaxed text-ink-2">
                There is nothing left to forecast. If you’re owed money, the administrator or liquidator is now the
                one to contact.
              </p>
            </div>
          ) : c.times_average === null ? (
            <p className="mt-4 max-w-xl text-[15px] leading-relaxed text-ink-2">
              No digitally filed annual report since 2024, so there are no figures to score. Large groups and banks
              usually file through other channels; registry changes are still tracked.
            </p>
          ) : (
            <div className="mt-4">
              <p className={`font-serif text-7xl leading-none tabular tracking-tight sm:text-8xl ${band === 'high' || band === 'severe' ? 'text-signal' : band === 'elevated' ? 'text-ochre' : 'text-ink'}`}>
                {c.times_average.toFixed(1)}<span className="text-4xl sm:text-5xl">×</span>
              </p>
              <p className="mt-2 text-[15px] text-ink-2">the average Swedish company’s risk of bankruptcy</p>
              <div className="mt-5"><RiskLadder timesAverage={c.times_average} status={c.status} size="lg" /></div>
            </div>
          )}

          {reasons.length > 0 && (
            <div className="mt-10">
              <h3 className="eyebrow border-b border-rule pb-2.5">
                {known ? 'Warning signs in its last annual report' : calm ? 'Minor notes' : 'Why, strongest sign first'}
              </h3>
              <ol className="divide-y divide-rule">
                {reasons.map((r, i) => (
                  <li key={r} className="flex gap-5 py-3.5">
                    <span className="font-mono text-xs tabular text-ink-3 pt-1">{String(i + 1).padStart(2, '0')}</span>
                    <span className={`text-[15px] leading-snug ${calm && !known ? 'text-ink-2' : 'text-ink'}`}>{r}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}
          {!known && c.times_average !== null && reasons.length === 0 && (
            <p className="mt-8 border-t border-rule pt-4 text-[15px] text-ink-2">No warning signs in the latest annual report.</p>
          )}
        </section>

        <aside className="space-y-10">
          {c.fiscal_end && (
            <section>
              <h2 className="eyebrow border-b border-rule pb-2.5">Source</h2>
              <dl className="divide-y divide-rule text-sm">
                {[
                  ['Annual report', `Year ending ${formatDate(c.fiscal_end)}`],
                  ['Filed', formatDate(c.filed_on)],
                  ['Model', c.model_version ?? '—'],
                ].map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-4 py-2.5">
                    <dt className="text-ink-3">{k}</dt>
                    <dd className="text-right font-mono text-xs leading-5 text-ink">{v}</dd>
                  </div>
                ))}
              </dl>
            </section>
          )}
          <section>
            <h2 className="eyebrow border-b border-rule pb-2.5">Registry history</h2>
            {c.events.length === 0 ? (
              <p className="pt-3 text-sm leading-relaxed text-ink-3">No changes since Bolagsvakt started watching the register.</p>
            ) : (
              <ol className="divide-y divide-rule">
                {c.events.map((e) => (
                  <li key={`${e.snapshot_date}-${e.event}-${e.detail}`} className="py-2.5">
                    <p className="font-mono text-[11px] text-ink-3">{formatDate(e.snapshot_date)}</p>
                    <p className="text-sm text-ink">{eventLabel(e.event)}</p>
                    {e.detail && <p className="text-xs text-ink-3">{e.detail}</p>}
                  </li>
                ))}
              </ol>
            )}
          </section>
          <p className="text-xs leading-relaxed text-ink-3">
            A risk signal from public filings to help you decide, not a credit rating.
          </p>
        </aside>
      </div>
    </article>
  )
}

/** Add this company to the signed-in user's watchlist, or say it's already there. */
function WatchButton({ orgNr }: { orgNr: string }) {
  const [state, setState] = useState<{ orgId: string; watching: boolean } | null>(null)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => {
    api.me().then(async (me) => {
      const org = me.organizations[0]
      if (!org) return
      const rows = await api.watchlist(org.id)
      setState({ orgId: org.id, watching: rows.some((r) => r.org_nr === orgNr) })
    }).catch(setError)
  }, [orgNr])
  if (error) return <ErrorNote error={error} />
  if (!state) return null
  if (state.watching) {
    return <span className="inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.08em] text-moss">● Watching</span>
  }
  return (
    <Button onClick={() => api.upload(state.orgId, new Blob([orgNr], { type: 'text/csv' }))
      .then(() => setState({ ...state, watching: true })).catch(setError)}>
      + Watch this company
    </Button>
  )
}
