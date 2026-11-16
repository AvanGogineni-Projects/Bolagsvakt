// What the numbers mean, in words a customer reads. Pure functions: the same rules decide the
// watchlist row, the company page and the summary counts.
import type { Status } from './api'

export const STATUS_LABEL: Record<Status, string> = {
  active: 'Active',
  in_bankruptcy: 'In bankruptcy',
  in_liquidation: 'In liquidation',
  in_reconstruction: 'In reconstruction',
  deregistered: 'Deregistered',
}

export type Band = 'low' | 'normal' | 'elevated' | 'high' | 'severe'

export const BANDS: { band: Band; label: string; from: number }[] = [
  { band: 'low', label: 'Low', from: 0 },
  { band: 'normal', label: 'Normal', from: 0.7 },
  { band: 'elevated', label: 'Elevated', from: 2 },
  { band: 'high', label: 'High', from: 5 },
  { band: 'severe', label: 'Severe', from: 12 },
]

/** Risk band from "times the average risk"; null when there is no annual report to score. */
export function riskBand(timesAverage: number | null): Band | null {
  if (timesAverage === null) return null
  return [...BANDS].reverse().find((b) => timesAverage >= b.from)!.band
}

/** A forecast only means something for a company that is still trading. Once it is in
 *  bankruptcy, liquidation or reconstruction, or deregistered, the outcome is known. */
export const outcomeKnown = (status: Status) => status !== 'active'

/** Whether a company needs the reader's attention: an outcome already happened, or high risk. */
export function needsAttention(status: Status, timesAverage: number | null): boolean {
  const band = riskBand(timesAverage)
  return outcomeKnown(status) || band === 'high' || band === 'severe'
}

/** The one-line reason for a list. Low and normal risk get no alarm: a single loss year on an
 *  otherwise healthy company is a note for the company page, not a headline. */
export function mainReason(status: Status, timesAverage: number | null, reasons: string[] | null): string {
  if (outcomeKnown(status)) return STATUS_LABEL[status]
  if (timesAverage === null) return 'No digital annual report to read'
  const band = riskBand(timesAverage)
  const signs = reportSigns(reasons)
  if (band === 'low' || band === 'normal' || !signs.length) return 'No major warning signs'
  return signs[0]
}

// risk.py puts a company's ongoing proceedings first in its reasons. They come from the
// register, not the annual report, and the status stamp already shows them.
const PROCEEDING_REASONS = new Set(['In bankruptcy', 'In liquidation', 'In company reconstruction'])

/** The warning signs that come from the annual report itself. */
export const reportSigns = (reasons: string[] | null) => (reasons ?? []).filter((r) => !PROCEEDING_REASONS.has(r))

// The event names the pipeline writes (history.py).
const EVENT_LABELS: Record<string, string> = {
  registered: 'Registered',
  removed_from_register: 'Removed from the register',
  deregistered: 'Deregistered',
  name_changed: 'Name changed',
  legal_form_changed: 'Legal form changed',
  address_changed: 'Address changed',
  description_changed: 'Business description changed',
  proceeding_started: 'Proceedings started',
  proceeding_ended: 'Proceedings ended',
}

export const eventLabel = (e: string) => EVENT_LABELS[e] ?? e

/** Real companies picked to show every state on the first visit: in bankruptcy, in
 *  liquidation, high risk, elevated, and healthy. */
export const SAMPLE_COMPANIES = [
  '5594457854', '5566546775', '5593755969', '5593926834',
  '5593650921', '5593659922', '5593643140', '5593666299',
]

export const formatDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : '—'
