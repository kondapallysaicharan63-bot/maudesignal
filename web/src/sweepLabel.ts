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

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$|^(\d{4})(\d{2})(\d{2})$/
const UTC_STAMP = /^(\d{4})-(\d{2})-(\d{2})T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?Z$/

/** True when y-m-d is a real calendar day (no Feb 31). */
function real({ y, m, d }: Ymd): boolean {
  const t = new Date(Date.UTC(y, m - 1, d))
  return t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d
}

/**
 * "2026-09-24", "20260924" or a UTC timestamp "2026-10-30T02:55:38Z" as calendar parts (the UTC day as written).
 * Anything else ("2026-0924", a timestamp with an offset, Feb 31) is null.
 */
export function ymdParts(raw: string | null | undefined): Ymd | null {
  const s = (raw ?? '').trim()
  const m = DATE_ONLY.exec(s) ?? UTC_STAMP.exec(s)
  if (!m) return null
  const out = { y: Number(m[1] ?? m[4]), m: Number(m[2] ?? m[5]), d: Number(m[3] ?? m[6]) }
  return real(out) ? out : null
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
export function sweepDetail(n: number, label: string | null | undefined, week: string | null = null): string {
  const reports = `${n} report${n === 1 ? '' : 's'}`
  if (label) return `${reports} · ${label}`
  return week ? `${reports} in the week ${week}` : `${reports} in the stored week`
}

/** True when an alert's stored week (from/to) is the very week of the sweep's window. */
export function sameWeek(
  sweep: Pick<Sweep, 'meta'> | null | undefined,
  from: string | null | undefined,
  to: string | null | undefined,
): boolean {
  const w = sweep?.meta?.window
  const a = [ymdParts(from), ymdParts(to), ymdParts(w?.current_start), ymdParts(w?.current_end)]
  if (a.some((x) => x === null)) return false
  const k = (x: Ymd | null) => `${x!.y}-${x!.m}-${x!.d}`
  return k(a[0]) === k(a[2]) && k(a[1]) === k(a[3])
}

/** The sweep's label for an alert, only when the alert's own week is the sweep's week; else null. */
export function labelForWeek(
  sweep: Pick<Sweep, 'meta'> | null | undefined,
  win: { from?: string | null; to?: string | null } | null | undefined,
): string | null {
  return win && sameWeek(sweep, win.from, win.to) ? sweepLabel(sweep) : null
}

/** "Latest sweep · Oct 30 (openFDA week Sep 24–30)" from the stored sweep; null when a field is missing. */
export function sweepLabel(sweep: Pick<Sweep, 'meta'> | null | undefined): string | null {
  const run = monDay(sweep?.meta?.generated_utc)
  const week = sweepWeek(sweep)
  if (!run || !week) return null
  return `Latest sweep · ${run} (${week})`
}
