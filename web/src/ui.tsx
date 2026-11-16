import type { Status } from './api'

const STATUS: Record<Status, { label: string; className: string }> = {
  active: { label: 'Active', className: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20' },
  in_bankruptcy: { label: 'In bankruptcy', className: 'bg-red-50 text-red-700 ring-red-600/20' },
  in_liquidation: { label: 'In liquidation', className: 'bg-orange-50 text-orange-700 ring-orange-600/20' },
  in_reconstruction: { label: 'In reconstruction', className: 'bg-amber-50 text-amber-800 ring-amber-600/20' },
  deregistered: { label: 'Deregistered', className: 'bg-slate-100 text-slate-600 ring-slate-500/20' },
}

export function StatusBadge({ status }: { status: Status }) {
  const s = STATUS[status]
  return (
    <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${s.className}`}>
      {s.label}
    </span>
  )
}

// Risk as "times the average company", the number a non-analyst can act on.
export function RiskLevel({ timesAverage }: { timesAverage: number | null }) {
  if (timesAverage === null) return <span className="text-sm text-slate-400">No report</span>
  const level = timesAverage >= 5 ? 'High' : timesAverage >= 2 ? 'Elevated' : 'Normal'
  const color = level === 'High' ? 'bg-red-500' : level === 'Elevated' ? 'bg-amber-400' : 'bg-emerald-500'
  const width = Math.min(100, (Math.log10(Math.max(timesAverage, 0.1)) + 1) * 40)
  return (
    <div className="flex items-center gap-2" title={`${timesAverage.toFixed(1)}× the average risk`}>
      <div className="h-1.5 w-16 rounded-full bg-slate-100">
        <div className={`h-1.5 rounded-full ${color}`} style={{ width: `${width}%` }} />
      </div>
      <span className="whitespace-nowrap text-sm tabular-nums text-slate-700">
        {level} · {timesAverage.toFixed(1)}×
      </span>
    </div>
  )
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null
  return (
    <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
      {error instanceof Error ? error.message : 'Something went wrong'}
    </p>
  )
}
