// Pure helpers for the home dashboard, the mini-dashboards and the alert bell.
// Every number is computed from the stored exports; thresholds mirror
// src/maudesignal/monitor/deterioration.py (a test fails if they drift apart).
import { capaDrafts, CLASS_LABEL, flaggedRows } from './artifacts'
import { sweepDetail, sweepLabel } from './sweepLabel'
import type { Brief, Company, CompanyDevice, Sweep, Thread, WorkflowId, WorkspaceData } from './types'

/** Mirrors SPIKE_MIN_REPORTS, SPIKE_MULTIPLIER, BASELINE_WEEKS and SEVERITY_ESCALATION_PP in deterioration.py. */
export const SWEEP_RULES = {
  spikeMinReports: 3,
  spikeMultiplier: 2,
  baselineWeeks: 4,
  severityPoints: 15,
} as const

/** The rules in plain words, built from the constants so the text cannot disagree with them. */
export function sweepRuleText(r = SWEEP_RULES): { spike: string; serious: string; newKind: string } {
  return {
    newKind:
      'A new kind of problem means reports in a code that had none before, or a kind of event never seen for that code before.',
    spike: `Reports suddenly increased needs at least ${r.spikeMinReports} reports this week and at least ${r.spikeMultiplier}x the ${r.baselineWeeks}-week weekly mean.`,
    serious: `More serious than usual needs the injury/death share to rise ${r.severityPoints} points or more.`,
  }
}

export interface SweepStats {
  total: number
  /** Codes with fewer than `spikeMinReports` reports this week. */
  fewer: number
  /** Codes with no report this week. */
  none: number
}

export function sweepStats(sweep: Sweep, minReports: number = SWEEP_RULES.spikeMinReports): SweepStats {
  const rows = sweep.rows
  return {
    total: rows.length,
    fewer: rows.filter((r) => r.current_count < minReports).length,
    none: rows.filter((r) => r.current_count === 0).length,
  }
}

export function sweepStatsText(s: SweepStats, minReports: number = SWEEP_RULES.spikeMinReports): string {
  return `${s.fewer} of ${s.total} codes had fewer than ${minReports} reports in the sweep's openFDA week (${s.none} had none).`
}

// ── Alerts ──────────────────────────────────────────────────────────────

export type AlertKind = 'new_signal' | 'severity_escalation'
export type AlertItemKind = AlertKind | 'needs_review' | 'spike'

export interface AlertItem {
  id: string
  kind: AlertItemKind
  productCode: string
  label: string
  /** Where the item comes from: the AI device sweep (real data) or the newest demo-snapshot brief. */
  source: 'sweep' | 'brief' | 'company'
  /** Company alerts: the device the alert opens. */
  deviceId?: string
  /** Company alerts: the simulated device's name. Sweep and brief alerts: the device type's name when a stored brief gives one. */
  deviceName?: string
  /** Company alerts: true when the device is in the person's own company (Make it yours). */
  mine?: boolean
  /** Sweep: the sweep date. Brief: the brief date. */
  date: string
  detail: string
}

/** DOM id of a flagged sweep row, so an alert link can scroll to it. */
export const sweepRowId = (code: string): string => `sweep-row-${code}`

const plural = (n: number, word: string): string => `${n} ${word}${n === 1 ? '' : 's'}`

const RISKY: string[] = ['new_signal', 'severity_escalation']
const isRisky = (c: string): c is AlertKind => RISKY.includes(c)

/**
 * Risky items: "new kind of problem" and "more serious than usual" from the AI device sweep and from
 * the newest brief, then the "Needs review" devices of the simulated company.
 */
export function alertItems(sweep: Sweep, briefs: Brief[], company?: Company | null): AlertItem[] {
  const out: AlertItem[] = []
  const typeNames = new Map<string, string>()
  for (const b of briefs) for (const [c, n] of Object.entries(b.device_types ?? {})) if (!typeNames.has(c)) typeNames.set(c, n)
  const sweepDay = sweep.meta.generated_utc.slice(0, 10)
  const label = sweepLabel(sweep)
  for (const r of flaggedRows(sweep))
    if (isRisky(r.classification))
      out.push({
        id: `sweep:${r.product_code}`,
        kind: r.classification,
        productCode: r.product_code,
        label: CLASS_LABEL[r.classification],
        source: 'sweep',
        deviceName: typeNames.get(r.product_code),
        date: sweepDay,
        detail: sweepDetail(r.current_count, label),
      })
  const newest = briefs[0]
  if (newest)
    for (const s of newest.signals)
      if (isRisky(s.classification))
        out.push({
          id: `brief:${newest.date}:${s.product_code}`,
          kind: s.classification,
          productCode: s.product_code,
          label: CLASS_LABEL[s.classification],
          source: 'brief',
          deviceName: typeNames.get(s.product_code),
          date: newest.date,
          detail: `${plural(s.current_count, 'report')} in the demo-snapshot week`,
        })
  for (const d of company?.devices ?? [])
    if (d.status?.label === NEEDS_REVIEW)
      out.push({
        id: `company:${d.id}`,
        kind: 'needs_review',
        productCode: d.product_code,
        label: NEEDS_REVIEW,
        source: 'company',
        deviceId: d.id,
        deviceName: d.name,
        ...(company?.mine ? { mine: true } : {}),
        date: d.status.date,
        detail: `${d.model} · ${d.owner}`,
      })
  return sortAlerts(out)
}

const KIND_RANK: Record<string, number> = { severity_escalation: 0, new_signal: 1, needs_review: 2 }

/** Most important first (more serious, then new kind of problem, then needs review), newest date first within a kind. */
export function sortAlerts(items: AlertItem[]): AlertItem[] {
  return [...items].sort(
    (a, b) => (KIND_RANK[a.kind] ?? 9) - (KIND_RANK[b.kind] ?? 9) || b.date.localeCompare(a.date) || a.productCode.localeCompare(b.productCode),
  )
}

/** The bell's two groups: real signals, and the simulated company's devices. */
export function groupAlerts(items: AlertItem[]): { signals: AlertItem[]; devices: AlertItem[] } {
  return { signals: items.filter((a) => a.source !== 'company'), devices: items.filter((a) => a.source === 'company') }
}

/** The status every device starts in; set by a named simulated person, never by the tool. */
export const NEEDS_REVIEW = 'Needs review'

/** Devices per status, in the order of the contract's status list (a status with no device shows 0). */
export function devicesPerStatus(company: Company): { label: string; count: number }[] {
  return company.statuses.map((s) => ({
    label: s.label,
    count: company.devices.filter((d) => d.status?.label === s.label).length,
  }))
}

/** Urgency of a status for the device table: Needs review first, then Testing, Monitoring, Covered, N/A. */
export const STATUS_PRIORITY: string[] = [
  NEEDS_REVIEW,
  'Testing in progress',
  'Monitoring — nothing open',
  'Already covered',
  'Not applicable to our device',
]
const prio = (label: string | undefined): number => {
  const i = STATUS_PRIORITY.indexOf(label ?? '')
  return i < 0 ? STATUS_PRIORITY.length : i
}

/** Devices by status priority, then by when the status was set (newest first), then by name. */
export function sortedDevices(company: Company, filter: string | null = null): CompanyDevice[] {
  return company.devices
    .filter((d) => filter === null || d.status?.label === filter)
    .sort(
      (a, b) =>
        prio(a.status?.label) - prio(b.status?.label) ||
        (b.status?.date ?? '').localeCompare(a.status?.date ?? '') ||
        a.name.localeCompare(b.name),
    )
}

/** Statuses in table-priority order with their device counts (the filter chips and the mini list). */
export function statusesByPriority(company: Company): { label: string; count: number }[] {
  return [...devicesPerStatus(company)].sort((a, b) => prio(a.label) - prio(b.label))
}

// ── Recorded-run metrics ─────────────────────────────────────────────────

export interface RunMetric {
  id: string
  recordedAt: string
  /** Sentences shown in the final answer (all passed the gate). */
  answers: number
  sentences: number
  /** passed / (passed + blocked) on the first pass; null when not stored. */
  firstPass: number | null
  /** Final sentences that passed / all final sentences; null when there are none. */
  finalPass: number | null
  costUsd: number | null
  durationS: number | null
}

export function runMetrics(threads: Thread[]): RunMetric[] {
  return [...threads]
    .sort((a, b) => a.recorded_at_utc.localeCompare(b.recorded_at_utc))
    .map((t) => {
      const passed = t.sentences.filter((s) => s.status === 'pass').length
      const fp = t.first_pass
      const fpTotal = fp ? fp.passed + fp.blocked : 0
      return {
        id: t.id,
        recordedAt: t.recorded_at_utc,
        answers: passed,
        sentences: t.sentences.length,
        firstPass: fp && fpTotal > 0 ? fp.passed / fpTotal : null,
        finalPass: t.sentences.length > 0 ? passed / t.sentences.length : null,
        costUsd: typeof t.usage?.cost_usd === 'number' ? t.usage.cost_usd : null,
        durationS: typeof t.usage?.duration_s === 'number' ? t.usage.duration_s : null,
      }
    })
}

export const pct = (x: number): string => `${Math.round(x * 1000) / 10}%`
export const usd = (x: number): string => `$${x.toFixed(x < 1 ? 3 : 2)}`

// ── Mini-dashboards ───────────────────────────────────────────────────────

export interface MiniStat {
  label: string
  value: string
  note?: string
}

export function workflowThreads(data: WorkspaceData, id: string): Thread[] {
  const group = data.threads.workflows.find((w) => w.id === id)
  return group ? data.threads.threads.filter((t) => group.thread_ids.includes(t.id)) : []
}

export interface RecentItem {
  id: string
  kind: 'thread' | 'run'
  label: string
  /** Sentences shown (all passed the gate). */
  shown: number
  withheld: number
  /** "$0.012" or "not recorded". */
  cost: string
}

/** The workflow's recorded answers (newest first): stored threads, or stored investigation runs. */
export function recentItems(workflow: WorkflowId, data: WorkspaceData): RecentItem[] {
  if (workflow === 'weekly-investigator' || workflow === 'recall-sweep')
    return data.investigations.investigations
      .filter((r) => r.kind === workflow)
      .sort((a, b) => b.recorded_at_utc.localeCompare(a.recorded_at_utc))
      .map((r) => ({
        id: r.id,
        kind: 'run' as const,
        label: `${r.product_code} · ${r.recorded_at_utc.slice(0, 10)}`,
        shown: r.sentences.filter((s) => s.status === 'pass').length,
        withheld: r.sentences.filter((s) => s.status === 'block').length,
        cost: 'not recorded',
      }))
  return workflowThreads(data, workflow)
    .filter(isAnswer)
    .sort((a, b) => b.recorded_at_utc.localeCompare(a.recorded_at_utc))
    .map((t) => ({
      id: t.id,
      kind: 'thread' as const,
      label: t.question,
      shown: t.sentences.filter((s) => s.status === 'pass').length,
      withheld: t.sentences.filter((s) => s.status === 'block').length,
      cost: typeof t.usage?.cost_usd === 'number' ? usd(t.usage.cost_usd) : 'not recorded',
    }))
}

/** A greeting has no tool step and no claim, so it is not an answer. */
const isAnswer = (t: Thread) => t.tool_steps.length > 0 || t.sentences.some((s) => s.claims.length > 0)

function threadStats(ts: Thread[]): MiniStat[] {
  const answers = ts.filter(isAnswer)
  // Only claims inside sentences that were shown (a withheld sentence's passing claims are not on screen).
  const claims = answers
    .flatMap((t) => t.sentences.filter((s) => s.status === 'pass').flatMap((s) => s.claims))
    .filter((c) => c.status === 'pass').length
  const withheld = answers.flatMap((t) => t.sentences).filter((s) => s.status === 'block').length
  const costs = runMetrics(answers)
    .map((x) => x.costUsd)
    .filter((x): x is number => x !== null)
  return [
    { label: 'Recorded answers', value: `${answers.length}` },
    { label: 'Claims in shown sentences', value: `${claims}` },
    { label: 'Sentences withheld', value: `${withheld}` },
    {
      label: 'Cost of these runs',
      value: costs.length > 0 ? usd(costs.reduce((a, b) => a + b, 0)) : 'not recorded',
      note: costs.length > 0 && costs.length < answers.length ? `${costs.length} of ${answers.length} runs recorded a cost` : undefined,
    },
  ]
}

export function miniStats(workflow: WorkflowId, data: WorkspaceData): MiniStat[] {
  switch (workflow) {
    case 'ai-sweep': {
      const st = sweepStats(data.sweep)
      return [
        { label: 'Codes checked', value: `${data.sweep.meta.codes_checked} of ${data.sweep.meta.codes_on_list}` },
        { label: 'Flagged', value: `${flaggedRows(data.sweep).length}` },
        { label: `Fewer than ${SWEEP_RULES.spikeMinReports} reports`, value: `${st.fewer}`, note: `${st.none} had none` },
        { label: 'Checked on', value: data.sweep.meta.generated_utc.slice(0, 10) },
      ]
    }
    case 'check-device':
      return [
        { label: 'Codes on the AI list', value: `${data.sweep.meta.codes_on_list}` },
        { label: 'Reports needed to flag a rise', value: `${SWEEP_RULES.spikeMinReports}` },
        { label: 'Weeks in the baseline', value: `${SWEEP_RULES.baselineWeeks}` },
        { label: 'Injury/death share rise', value: `${SWEEP_RULES.severityPoints} points` },
      ]
    case 'weekly-signals': {
      const b = data.briefs[0]
      return [
        ...threadStats(workflowThreads(data, workflow)),
        ...(b
          ? [
              {
                label: 'Newest brief',
                value: b.date,
                note: `${b.counts.new} new kind, ${b.counts.more_serious_than_usual} more serious, ${b.counts.reports_suddenly_increased} rise`,
              },
            ]
          : []),
      ]
    }
    case 'ask-copilot':
      return threadStats(workflowThreads(data, workflow))
    case 'capa-need-evidence':
      return [
        ...threadStats(workflowThreads(data, workflow)),
        { label: 'Drafts in the audit trail', value: `${capaDrafts(data.audit).length}` },
      ]
    case 'weekly-investigator':
    case 'recall-sweep': {
      const runs = data.investigations.investigations.filter((r) => r.kind === workflow)
      return [
        { label: 'Recorded runs', value: `${runs.length}` },
        { label: 'Groups of reports', value: `${runs.reduce((n, r) => n + r.groups.length, 0)}` },
        {
          label: 'Sentences shown',
          value: `${runs.reduce((n, r) => n + r.sentences.filter((s) => s.status === 'pass').length, 0)}`,
        },
      ]
    }
    case 'our-devices': {
      const per = devicesPerStatus(data.company)
      return [
        { label: 'Devices (simulated)', value: `${data.company.devices.length}` },
        ...per.map((x) => ({ label: x.label, value: `${x.count}` })),
      ]
    }
    case 'vision': {
      const k = data.vision.k510
      const count = (s: 'VERIFIED' | 'CONFLICT' | 'UNVERIFIABLE') => k.reduce((n, r) => n + (r.counts[s] ?? 0), 0)
      return [
        { label: '510(k) pages read', value: `${k.length}` },
        { label: 'Label photos read', value: `${data.vision.labels.length}` },
        { label: 'Fields verified', value: `${count('VERIFIED')}` },
        { label: 'Conflicts / unverifiable', value: `${count('CONFLICT')} / ${count('UNVERIFIABLE')}` },
      ]
    }
  }
}
