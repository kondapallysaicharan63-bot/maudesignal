// The AI device sweep's label, from the stored sweep data only: "Latest sweep · Oct 30 (openFDA week Sep 24–30)".
// The run date is the sweep's generated_utc (UTC day); the week is its window.current_start..current_end. Nothing is
// hardcoded: a newer sweep file gives a newer label. openFDA lags real time, so the sweep is never called "this week".
import type { Sweep } from './types'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

interface Ymd {
  y: number
  m: number
  d: number
}

/** "2026-09-24", "20260924" or "2026-10-30T02:55:38Z" as calendar parts (the UTC day as written); null otherwise. */
export function ymdParts(raw: string | null | undefined): Ymd | null {
  const s = (raw ?? '').trim()
  const m = /^(\d{4})-?(\d{2})-?(\d{2})/.exec(s)
  if (!m) return null
  const y = Number(m[1])
  const mo = Number(m[2])
  const d = Number(m[3])
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return null
  return { y, m: mo, d }
}

/** "Oct 30". */
export function monDay(raw: string | null | undefined): string | null {
  const p = ymdParts(raw)
  return p ? `${MONTHS[p.m - 1]} ${p.d}` : null
}

/** "Sep 24–30", or "Sep 28–Oct 4" across a month, or "Dec 29, 2025–Jan 4, 2026" across a year. */
export function weekRange(start: string | null | undefined, end: string | null | undefined): string | null {
  const a = ymdParts(start)
  const b = ymdParts(end)
  if (!a || !b) return null
  if (a.y !== b.y) return `${MONTHS[a.m - 1]} ${a.d}, ${a.y}–${MONTHS[b.m - 1]} ${b.d}, ${b.y}`
  if (a.m !== b.m) return `${MONTHS[a.m - 1]} ${a.d}–${MONTHS[b.m - 1]} ${b.d}`
  return `${MONTHS[a.m - 1]} ${a.d}–${b.d}`
}

/** "openFDA week Sep 24–30" from the stored sweep; null when its window is missing. */
export function sweepWeek(sweep: Pick<Sweep, 'meta'> | null | undefined): string | null {
  const w = sweep?.meta?.window
  const r = w ? weekRange(w.current_start, w.current_end) : null
  return r ? `openFDA week ${r}` : null
}

/** Item detail for a sweep alert: "10 reports · Latest sweep · Oct 30 (openFDA week Sep 24–30)". */
export function sweepDetail(n: number, label: string | null | undefined): string {
  const reports = `${n} report${n === 1 ? '' : 's'}`
  return label ? `${reports} · ${label}` : `${reports} in the latest sweep`
}

/** "Latest sweep · Oct 30 (openFDA week Sep 24–30)" from the stored sweep; null when a field is missing. */
export function sweepLabel(sweep: Pick<Sweep, 'meta'> | null | undefined): string | null {
  const run = monDay(sweep?.meta?.generated_utc)
  const week = sweepWeek(sweep)
  if (!run || !week) return null
  return `Latest sweep · ${run} (${week})`
}
