// Data-as-of + reporting-delay banner (PRD-23, reviewer desktop check). Shown at the top of Signals, Investigate,
// Copilot answers and the sweep, and printed on every evidence export. Every date comes from the stored exports
// (manifest.data_as_of) or from the live answer itself; nothing here is "today".
import type { Manifest } from '../types'

export const DELAY_SENTENCE =
  'OpenFDA republishes weekly and reports arrive with delay — recent months may show few or no reports because of reporting delay, not because risk is zero.'

export interface AsOf {
  /** Latest report date behind the figures on this page (ISO day). */
  latest: string | null
  /** Stored snapshot window, e.g. "2006-05-18 to 2026-08-31 (137 reports)". */
  snapshot: string | null
  /** When a live openFDA query was made for this page, or null when nothing live was asked. */
  live: string | null
}

const day = (s: string | null | undefined): string | null => {
  const m = /^(\d{4})-?(\d{2})-?(\d{2})/.exec((s ?? '').trim())
  return m ? `${m[1]}-${m[2]}-${m[3]}` : null
}

/** The snapshot window line from the manifest; null when the manifest has no dates. */
export function snapshotLine(m: Pick<Manifest, 'data_as_of'> | null | undefined): string | null {
  const s = m?.data_as_of?.stored
  if (!s || !s.earliest || !s.latest) return null
  return `${s.earliest} to ${s.latest} (${s.reports.toLocaleString('en-US')} stored MAUDE reports)`
}

/** The latest date the stored figures reach: the later of the stored reports and the latest sweep week's end. */
export function latestStored(m: Pick<Manifest, 'data_as_of'> | null | undefined): string | null {
  const a = day(m?.data_as_of?.stored.latest)
  const b = day(m?.data_as_of?.sweep.week_end)
  if (a && b) return a > b ? a : b
  return a ?? b
}

/** The banner sentence as plain text (exports print exactly this). */
export function asOfText(a: AsOf): string {
  return [
    `Data as of: ${a.latest ?? 'not stated'}.`,
    DELAY_SENTENCE,
    `Stored snapshot: ${a.snapshot ?? 'not stated'}.`,
    `Live check: ${a.live ?? 'none on this page'}.`,
  ].join(' ')
}

/** The page's AsOf from the stored manifest (no live query). */
export function storedAsOf(m: Pick<Manifest, 'data_as_of'> | null | undefined, live: string | null = null): AsOf {
  const sweep = m?.data_as_of?.sweep
  const snap = snapshotLine(m)
  const week = sweep?.week_start && sweep.week_end ? `latest AI device sweep week ${sweep.week_start} to ${sweep.week_end}, checked ${day(sweep.checked_utc) ?? 'date not stated'}` : null
  return { latest: latestStored(m), snapshot: [snap, week].filter(Boolean).join('; ') || null, live }
}

/** True when a month (YYYY-MM) ends within `days` of the reference day: reports for it are still arriving. */
export function inDelayWindow(month: string, reference: string | null, days = 62): boolean {
  const r = day(reference)
  const mm = /^(\d{4})-(\d{2})$/.exec(month)
  if (!r || !mm) return false
  const end = Date.UTC(Number(mm[1]), Number(mm[2]), 0)
  const ref = Date.parse(`${r}T00:00:00Z`)
  return ref - end <= days * 86400000
}

export function DataAsOfBanner({ asOf, testid = 'data-as-of' }: { asOf: AsOf; testid?: string }) {
  return (
    <p className="ms-banner ms-banner--info ms2-asof" role="note" data-testid={testid}>
      <span>
        <strong data-testid={`${testid}-latest`}>Data as of: {asOf.latest ?? 'not stated'}.</strong> {DELAY_SENTENCE}{' '}
        <span className="ms2-nowrap">Stored snapshot:</span> <span data-testid={`${testid}-snapshot`}>{asOf.snapshot ?? 'not stated'}</span>.{' '}
        <span className="ms2-nowrap">Live check:</span> <span data-testid={`${testid}-live`}>{asOf.live ?? 'none on this page'}</span>.
      </span>
    </p>
  )
}

/** An Investigate answer's dates: the newest report date it shows, its 12-month window, and when openFDA was asked. */
export function investigationAsOf(a: {
  mode: 'live' | 'recorded'
  retrieved_utc: string
  retrieved_date: string
  window_start: string
  window_end: string
  quotes: { date_received: string | null }[]
  sources: { reports: { date_received: string | null }[] } | null
}): AsOf {
  const dates = [...a.quotes.map((q) => q.date_received), ...(a.sources?.reports ?? []).map((r) => r.date_received)]
    .map((d) => day(d))
    .filter((d): d is string => d !== null)
    .sort()
  const newest = dates.length ? dates[dates.length - 1] : null
  const ws = day(a.window_start) ?? a.window_start
  const we = day(a.window_end) ?? a.window_end
  return {
    latest: newest ? `${newest} (newest report shown)` : `${we} (end of the query window; no dated report shown)`,
    snapshot: a.mode === 'recorded' ? `recorded copy of ${a.retrieved_date}, openFDA window ${ws} to ${we}` : `none, live openFDA window ${ws} to ${we}`,
    live: a.mode === 'recorded' ? `none (recorded example; openFDA was asked on ${a.retrieved_date})` : `${day(a.retrieved_utc) ?? a.retrieved_utc} (${a.retrieved_utc})`,
  }
}

/** The AI device sweep's dates, from the stored sweep file only. */
export function sweepAsOf(meta: { generated_utc?: string | null; window?: { current_start?: string; current_end?: string } | null } | null | undefined): AsOf {
  const w = meta?.window
  const checked = day(meta?.generated_utc ?? null)
  return {
    latest: day(w?.current_end ?? null),
    snapshot: w?.current_start && w.current_end ? `stored sweep file, openFDA week ${day(w.current_start)} to ${day(w.current_end)}, checked ${checked ?? 'date not stated'}` : null,
    live: checked ? `${checked} (when the sweep queried openFDA; Stored since then)` : null,
  }
}
