// Real FDA alerts for the v2 layout (Home, Signals, the bell), never mixed with the simulated company's devices.
// Every number is read from alerts.json (stored, recomputed by scripts/export_alerts.py); nothing is computed here
// except ordering. Without alerts.json the risky sweep and brief items from the stored exports are used.
import type { AlertDetail } from '../alerts'
import { alertItems, groupAlerts, NEEDS_REVIEW, type AlertItem, type AlertItemKind } from '../dashboard'
import { labelForWeek, sweepDetail, weekRange } from '../sweepLabel'
import type { WorkspaceData } from '../types'

const KIND_OF_RULE: Record<string, AlertItemKind> = {
  'more serious than usual': 'severity_escalation',
  'new kind of problem': 'new_signal',
  'reports suddenly increased': 'spike',
}
const LABEL_OF_KIND: Record<string, string> = {
  severity_escalation: 'More serious than usual',
  new_signal: 'New kind of problem',
  spike: 'Reports suddenly increased',
}
const RANK: Record<string, number> = { severity_escalation: 0, new_signal: 1, spike: 2 }

/** True for an alert about real FDA data (the AI device sweep or a stored brief), false for a simulated device. */
export const isReal = (d: Pick<AlertDetail, 'source'>): boolean => d.source.kind !== 'company'

/** The stored real alerts (sweep and brief), with their detail. */
export function realDetails(data: Pick<WorkspaceData, 'alerts'>): AlertDetail[] {
  return (data.alerts?.alerts ?? []).filter(isReal)
}

const plural = (n: number, w: string): string => `${n} ${w}${n === 1 ? '' : 's'}`

/**
 * One stored alert as a list item (same shape the bell and the alert lists use). `label` is the stored sweep's
 * "Latest sweep · <run day> (openFDA week ...)" (see sweepLabel), given only when the alert's week is the sweep's
 * week; otherwise the alert's own stored week is named. The sweep is never called "this week".
 */
export function itemOf(d: AlertDetail, label: string | null = null): AlertItem {
  const kind = KIND_OF_RULE[d.rule ?? ''] ?? 'new_signal'
  const n = d.window?.this_week.count
  const w = d.window?.this_week
  const detail =
    n == null
      ? d.source.label
      : d.source.kind === 'brief'
        ? `${plural(n, 'report')} in the demo-snapshot week`
        : sweepDetail(n, label, weekRange(w?.from, w?.to))
  return {
    id: d.id,
    kind,
    productCode: d.product_code,
    label: LABEL_OF_KIND[kind],
    source: d.source.kind === 'brief' ? 'brief' : 'sweep',
    ...(d.device_type ? { deviceName: d.device_type } : {}),
    date: d.source.as_of ?? '',
    detail,
  }
}

/** Most important first: more serious, then a new kind of problem, then a rise; newest first; then the larger rise. */
export function rankReal(details: AlertDetail[]): AlertDetail[] {
  const ratio = (d: AlertDetail): number => {
    const w = d.window
    if (!w || w.this_week.count == null || !w.baseline_4wk.weekly_mean) return 0
    return w.this_week.count / w.baseline_4wk.weekly_mean
  }
  return [...details].sort((a, b) => {
    const ka = RANK[KIND_OF_RULE[a.rule ?? ''] ?? 'new_signal'] ?? 9
    const kb = RANK[KIND_OF_RULE[b.rule ?? ''] ?? 'new_signal'] ?? 9
    return ka - kb || (b.source.as_of ?? '').localeCompare(a.source.as_of ?? '') || ratio(b) - ratio(a) || a.product_code.localeCompare(b.product_code)
  })
}

/** The latest sweep's real alerts: the AI device sweep only (the stored brief is a demo snapshot, listed apart). */
export function sweepDetails(data: Pick<WorkspaceData, 'alerts'>): AlertDetail[] {
  return realDetails(data).filter((d) => d.source.kind === 'sweep')
}

/** The demo-snapshot brief's alerts: real FDA reports, but from the demo database, not the latest sweep. */
export function demoDetails(data: Pick<WorkspaceData, 'alerts'>): AlertDetail[] {
  return realDetails(data).filter((d) => d.source.kind === 'brief')
}

/** The latest sweep's real alerts as list items, ranked (the bell, Home, Signals). Without alerts.json: the risky sweep items. */
export function realAlertItems(data: Pick<WorkspaceData, 'alerts' | 'sweep' | 'briefs'>): AlertItem[] {
  const details = sweepDetails(data)
  if (details.length > 0) return rankReal(details).map((d) => itemOf(d, labelForWeek(data.sweep, d.window?.this_week)))
  return groupAlerts(alertItems(data.sweep, data.briefs, null)).signals.filter((a) => a.source === 'sweep')
}

/** Devices of the simulated (or the person's own) company that need review. Never a real alert. */
export function devicesToReview(data: Pick<WorkspaceData, 'company'>): number {
  return (data.company?.devices ?? []).filter((d) => d.status?.label === NEEDS_REVIEW).length
}

/** "Stored · AI device sweep, 2026-09-30" or "Stored · demo snapshot brief, 2026-08-31". */
export function sourceLine(d: AlertDetail): string {
  return `Stored · ${d.source.label}${d.source.as_of ? `, ${d.source.as_of}` : ''}`
}
