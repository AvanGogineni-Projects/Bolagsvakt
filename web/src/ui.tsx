import { useState } from 'react'
import type { Status } from './api'
import { BANDS, STATUS_LABEL, outcomeKnown, riskBand, type Band } from './labels'

/** A document with a red "watch light": what Bolagsvakt is, a file someone keeps an eye on. */
export function Wordmark({ size = 'md' }: { size?: 'md' | 'lg' }) {
  const box = size === 'lg' ? 'h-7 w-7' : 'h-5 w-5'
  return (
    <span className="inline-flex items-center gap-2">
      <svg viewBox="0 0 32 32" className={box} aria-hidden="true">
        <rect x="5" y="4" width="22" height="24" rx="3" fill="none" stroke="currentColor" strokeWidth="2.5" />
        <path d="M10 12h12M10 17h12M10 22h7" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
        <circle cx="25" cy="7" r="4.5" className="fill-signal" />
      </svg>
      <span className={`font-serif tracking-tight ${size === 'lg' ? 'text-2xl' : 'text-lg'}`}>Bolagsvakt</span>
    </span>
  )
}

const STAMP: Record<Status, string> = {
  active: 'text-moss border-moss/40',
  in_bankruptcy: 'text-signal border-signal bg-signal-soft',
  in_liquidation: 'text-ochre border-ochre bg-ochre-soft',
  in_reconstruction: 'text-ochre border-ochre bg-ochre-soft',
  deregistered: 'text-ink-3 border-rule',
}

/** Registry status as a rubber stamp: square, uppercase, outlined. */
export function StatusStamp({ status }: { status: Status }) {
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-[3px] border px-1.5 py-0.5 font-mono text-[10.5px] font-medium uppercase tracking-[0.08em] ${STAMP[status]}`}
    >
      {STATUS_LABEL[status]}
    </span>
  )
}

const BAND_COLOR: Record<Band, string> = {
  low: 'bg-moss',
  normal: 'bg-moss',
  elevated: 'bg-ochre',
  high: 'bg-signal',
  severe: 'bg-signal',
}
const BAND_TEXT: Record<Band, string> = {
  low: 'text-moss',
  normal: 'text-ink-2',
  elevated: 'text-ochre',
  high: 'text-signal',
  severe: 'text-signal',
}

/** Risk as a five-step ladder: the steps up to the company's band are filled. For a company whose
 *  outcome is already known, a forecast would be misleading, so the ladder says so instead. */
export function RiskLadder({ timesAverage, status, size = 'sm' }: {
  timesAverage: number | null; status: Status; size?: 'sm' | 'lg'
}) {
  if (outcomeKnown(status)) {
    return <span className="font-mono text-xs uppercase tracking-[0.06em] text-ink-3">Outcome known</span>
  }
  const band = riskBand(timesAverage)
  if (band === null || timesAverage === null) {
    return <span className="font-mono text-xs uppercase tracking-[0.06em] text-ink-3">No report</span>
  }
  const level = BANDS.findIndex((b) => b.band === band)
  const label = BANDS[level].label
  const step = size === 'lg' ? 'h-2.5 w-9' : 'h-1.5 w-4'
  return (
    <span
      className="inline-flex items-center gap-3"
      title={`${label}: ${timesAverage.toFixed(1)}× the average company's risk`}
    >
      <span className="flex gap-[3px]" aria-hidden="true">
        {BANDS.map((b, i) => (
          <span key={b.band} className={`${step} rounded-[1px] ${i <= level ? BAND_COLOR[band] : 'bg-rule'}`} />
        ))}
      </span>
      <span className={`whitespace-nowrap font-mono tabular ${size === 'lg' ? 'text-sm' : 'text-xs'} ${BAND_TEXT[band]}`}>
        {label} · {timesAverage.toFixed(1)}×
      </span>
    </span>
  )
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null
  return (
    <p role="alert" className="border-l-2 border-signal bg-signal-soft px-3 py-2 text-sm text-ink">
      {error instanceof Error ? error.message : 'Something went wrong'}
    </p>
  )
}

export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="divide-y divide-rule" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-6 py-4">
          <div className="h-4 w-48 animate-pulse rounded-sm bg-rule/70" />
          <div className="h-4 w-20 animate-pulse rounded-sm bg-rule/70" />
          <div className="h-4 w-28 animate-pulse rounded-sm bg-rule/70" />
          <div className="h-4 flex-1 animate-pulse rounded-sm bg-rule/50" />
        </div>
      ))}
    </div>
  )
}

type Theme = 'light' | 'dark'

function currentTheme(): Theme {
  const set = document.documentElement.dataset.theme
  if (set === 'light' || set === 'dark') return set
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(currentTheme)
  const next: Theme = theme === 'dark' ? 'light' : 'dark'
  return (
    <button
      type="button"
      onClick={() => {
        document.documentElement.dataset.theme = next
        try { localStorage.setItem('bolagsvakt_theme', next) } catch { /* private mode: theme just isn't remembered */ }
        setTheme(next)
      }}
      className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-3 hover:text-ink"
      aria-label={`Switch to ${next} theme`}
    >
      {theme === 'dark' ? 'Light' : 'Dark'}
    </button>
  )
}

export function Button({ variant = 'primary', className = '', ...props }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'quiet' }) {
  const look = variant === 'primary'
    ? 'bg-ink text-paper hover:bg-ink-2 disabled:opacity-40'
    : 'border border-rule text-ink hover:border-ink-3 disabled:opacity-40'
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-2 rounded-[4px] px-3.5 py-2 text-sm font-medium transition-colors ${look} ${className}`}
    />
  )
}
