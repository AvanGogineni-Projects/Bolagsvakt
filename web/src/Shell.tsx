import { useEffect, useRef, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { api, formatOrgNr, type SearchHit } from './api'
import { signOut, useSignedIn } from './auth'
import { formatDate } from './labels'
import { StatusStamp, ThemeToggle, Wordmark } from './ui'

/** The frame around every signed-in page: masthead with search, then the page. */
export function Shell({ children }: { children: React.ReactNode }) {
  const signedIn = useSignedIn()
  const [snapshot, setSnapshot] = useState<string | null>(null)
  useEffect(() => {
    api.health().then((h) => setSnapshot(h.last_publish?.registry_snapshot ?? null)).catch(() => setSnapshot(null))
  }, [])
  if (signedIn === undefined) return null
  if (!signedIn) return <Navigate to="/login" />
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-rule bg-paper/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3 sm:gap-6 sm:px-6">
          <Link to="/" aria-label="Bolagsvakt home" className="shrink-0"><Wordmark /></Link>
          <Search />
          <div className="ml-auto flex shrink-0 items-center gap-4 sm:gap-5">
            {snapshot && (
              <span className="hidden items-center gap-1.5 font-mono text-[11px] uppercase tracking-[0.08em] text-ink-3 md:inline-flex"
                    title="Date of the Bolagsverket registry snapshot the data comes from">
                <span className="h-1.5 w-1.5 rounded-full bg-moss" aria-hidden="true" />
                Registry {formatDate(snapshot)}
              </span>
            )}
            <span className="hidden sm:inline"><ThemeToggle /></span>
            <button
              className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-3 hover:text-ink"
              onClick={() => signOut().then(() => window.location.assign('/login'))}
            >
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 pb-24 pt-8 sm:px-6 sm:pt-12">{children}</main>
    </div>
  )
}

/** Search all companies by name or org number. "/" focuses it from anywhere. */
function Search() {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<SearchHit[]>([])
  const [active, setActive] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === '/' && document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA') {
        e.preventDefault()
        input.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (q.trim().length < 2) return
    const t = setTimeout(() => api.search(q).then((h) => { setHits(h); setActive(0) }).catch(() => setHits([])), 180)
    return () => clearTimeout(t)
  }, [q])

  const shown = q.trim().length < 2 ? [] : hits
  const go = (h: SearchHit) => { setQ(''); input.current?.blur(); navigate(`/company/${h.org_nr}`) }

  return (
    <div className="relative min-w-0 flex-1 sm:max-w-md">
      <input
        ref={input}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, shown.length - 1)) }
          if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
          if (e.key === 'Enter' && shown[active]) go(shown[active])
          if (e.key === 'Escape') setQ('')
        }}
        role="combobox"
        aria-expanded={shown.length > 0}
        aria-controls="search-results"
        aria-label="Search companies by name or organisation number"
        placeholder="Search companies"
        className="w-full rounded-[4px] border border-rule bg-card px-3 py-1.5 pr-8 text-sm text-ink placeholder:text-ink-3 focus:border-ink-3 focus:outline-none"
      />
      <kbd className="pointer-events-none absolute right-2 top-1/2 hidden -translate-y-1/2 rounded-[3px] border border-rule px-1 font-mono text-[10px] text-ink-3 sm:block">/</kbd>
      {shown.length > 0 && (
        <ul id="search-results" role="listbox"
            className="absolute z-30 mt-1 w-full overflow-hidden rounded-[4px] border border-rule bg-card shadow-[0_12px_32px_-12px_rgba(26,23,20,0.35)]">
          {shown.map((h, i) => (
            <li key={h.org_nr} role="option" aria-selected={i === active}>
              <button
                onMouseEnter={() => setActive(i)}
                onClick={() => go(h)}
                className={`flex w-full items-center gap-3 px-3 py-2.5 text-left ${i === active ? 'bg-paper' : ''}`}
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-ink">{h.name}</span>
                  <span className="block font-mono text-[11px] text-ink-3">{formatOrgNr(h.org_nr)}{h.city ? ` · ${h.city}` : ''}</span>
                </span>
                {h.status !== 'active' && <StatusStamp status={h.status} />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
