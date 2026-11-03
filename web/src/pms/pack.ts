// Evidence pack (PRD-20/21/25): the evidence behind one flagged code, built from a stored real alert (alerts.json)
// or from an Investigate answer, plus the checklists a person answers. Mirrors src/maudesignal/pms/checklists.py.
// Nothing here decides: no risk score, no "increased device risk", no "recall needed", no reportability finding.
// Occurrence is counts, never a rate (MAUDE has no denominator).
import type { AlertDetail } from '../alerts'
import type { Investigation } from '../investigate/api'
import { asOfText, type AsOf } from './DataAsOf'

export interface PackReport {
  report_id: string
  date_received: string | null
  event_type: string | null
  source: string | null
  url: string
}
export interface PackRecall {
  id: string
  firm: string | null
  status: string | null
  date: string | null
  reason: string | null
  url: string | null
}
export interface EvidencePack {
  id: string
  origin: 'alert' | 'investigation'
  product_code: string
  device_type: string | null
  why: string
  counts: { label: string; value: number | string; url: string | null }[]
  reports: PackReport[]
  /** Reports not filed by a manufacturer, listed first (check against your complaint log). */
  non_manufacturer: PackReport[]
  recalls: PackRecall[]
  recalls_total: number | null
  failure_terms: string[]
  as_of: AsOf
  /** True when the event type of the listed reports is known (alerts); Investigate answers do not carry it. */
  event_types_known: boolean
}

export const HUMAN_DECIDES = 'Human decides — record the answer in your own QMS.'
export const FORBIDDEN_DECISIONS = [
  'recall needed',
  'recall is needed',
  'recall is required',
  'is reportable',
  'must be reported',
  'increased device risk',
  'capa is required',
  'capa is needed',
  'risk score',
]

/** True when text holds a tool-made decision sentence (the report-mix limitation itself is allowed). */
export function hasDecisionSentence(text: string): boolean {
  const low = text.toLowerCase().replace(/not proof of increased device risk/g, '')
  return FORBIDDEN_DECISIONS.some((f) => low.includes(f))
}

/** A plain-words "why flagged" line with counts for a stored alert. */
export function whyFlagged(a: Pick<AlertDetail, 'rule' | 'mix_sentence' | 'window' | 'numbers'>): string {
  const now = a.window?.this_week.count
  const base = a.window?.baseline_4wk.weekly_mean
  const rule = a.rule ? a.rule[0].toUpperCase() + a.rule.slice(1) : 'No weekly rule fired'
  if (a.rule === 'report mix changed' && a.mix_sentence) return `${rule}. ${a.mix_sentence}`
  if (now != null && base != null) return `${rule}: ${now} reports in the week vs a weekly average of ${base} in the 4 weeks before.`
  if (now != null) return `${rule}: ${now} reports in the week.`
  return `${rule}.`
}

export function packFromAlert(a: AlertDetail, asOf: AsOf): EvidencePack {
  const reports = a.reports.map((r) => ({
    report_id: r.report_id,
    date_received: r.date_received,
    event_type: r.event_type,
    source: null,
    url: r.maude_url || r.openfda_url,
  }))
  return {
    id: `alert:${a.id}`,
    origin: 'alert',
    product_code: a.product_code,
    device_type: a.device_type,
    why: whyFlagged(a),
    counts: a.numbers.map((n) => ({ label: n.label, value: n.value, url: n.openfda_url ?? null })),
    reports,
    non_manufacturer: [],
    recalls: a.recalls.map((r) => ({ id: r.id, firm: null, status: null, date: r.date, reason: r.reason, url: r.url })),
    recalls_total: a.recalls_total,
    failure_terms: [],
    as_of: asOf,
    event_types_known: true,
  }
}

const isMaker = (s: string | null): boolean => /manufacturer/i.test(s ?? '')

export function packFromInvestigation(a: Investigation, asOf: AsOf, terms: string[] = a.keywords): EvidencePack {
  const seen = new Set<string>()
  const rows: PackReport[] = []
  for (const r of [...(a.sources?.reports ?? []), ...a.quotes]) {
    if (seen.has(r.mdr_report_key)) continue
    seen.add(r.mdr_report_key)
    rows.push({ report_id: r.report_number ?? r.mdr_report_key, date_received: r.date_received, event_type: null, source: r.source, url: r.url })
  }
  const kw = a.total_keyword_matched
  return {
    id: `inv:${a.product_code}:${a.retrieved_utc}`,
    origin: 'investigation',
    product_code: a.product_code,
    device_type: a.device_type_name,
    why:
      `Complaint investigation: ${a.total_code_wide.value} reports for ${a.product_code} in the 12-month window` +
      (kw ? `; ${kw.value} of them mention a keyword (${a.keywords.join(', ')}). The two counts are never added.` : '.'),
    counts: [
      { label: `All reports for ${a.product_code}, 12 months`, value: a.total_code_wide.value, url: a.total_code_wide.url || null },
      ...(kw ? [{ label: 'Of those, narrative mentions a keyword', value: kw.value, url: kw.url || null }] : []),
      ...(a.sources ? [{ label: 'Not filed by a manufacturer', value: a.sources.non_manufacturer.value, url: a.sources.non_manufacturer.url || null }] : []),
    ],
    reports: rows,
    non_manufacturer: rows.filter((r) => r.source && !isMaker(r.source)),
    recalls: a.recalls.items.map((r) => ({ id: r.recall_number, firm: r.firm, status: r.status, date: r.date_initiated, reason: r.reason, url: r.url || null })),
    recalls_total: a.recalls.total?.value ?? null,
    failure_terms: terms,
    as_of: asOf,
    event_types_known: false,
  }
}

// ── checklists (pms/checklists.py) ───────────────────────────────────────────
const norm = (et: string | null): string => {
  const e = (et ?? '').trim().toLowerCase()
  return e === 'death' || e === 'injury' || e === 'malfunction' ? e : 'other / not stated'
}

export interface MixRow {
  event_type: string
  count: number
  share: number | null
  of: number
}

export function severityMix(p: EvidencePack): MixRow[] {
  const order = ['death', 'injury', 'malfunction', 'other / not stated']
  const c: Record<string, number> = Object.fromEntries(order.map((k) => [k, 0]))
  for (const r of p.reports) c[norm(r.event_type)] += 1
  const n = p.reports.length
  return order.map((k) => ({ event_type: k, count: c[k], share: n ? c[k] / n : null, of: n }))
}

export interface CheckItem {
  item: string
  basis: string
  evidence: string[]
  question: string
}

export function escalationChecklist(p: EvidencePack): CheckItem[] {
  const ids = p.reports.map((r) => r.report_id)
  const severe = p.reports.filter((r) => ['death', 'injury'].includes(norm(r.event_type))).map((r) => r.report_id)
  return [
    {
      item: 'MDR reportability assessment',
      basis: '21 CFR 803.50 (30 calendar days) / 21 CFR 803.53 (5 work days) — clock is advisory, from the awareness date your team records',
      evidence: severe.length ? severe : ids,
      question: 'Does any event your company is aware of meet the MDR reporting criteria?',
    },
    {
      item: 'Recall / correction-and-removal assessment',
      basis: '21 CFR 806; 21 CFR 7 Subpart C',
      evidence: p.recalls.map((r) => r.id),
      question: 'Does this need a correction or removal under your recall procedure?',
    },
    {
      item: 'Field safety action assessment',
      basis: 'Your field action / customer notification procedure',
      evidence: ids,
      question: 'Is a field safety action or customer notification warranted?',
    },
  ]
}

export const OCCURRENCE_NOTE =
  'These are counts of reports received by FDA, not rates: MAUDE has no denominator (units in use are not known), so no incidence or probability is stated.'
export const DETECTABILITY_QUESTION =
  'Could your existing controls (labelling, alarms, service checks, complaint trending) detect this failure mode before harm? — human answers in the risk file.'

export function recallCheck(p: EvidencePack): { rows: (PackRecall & { hits: string[] })[]; matched: string[]; summary: string } {
  const terms = p.failure_terms.map((t) => t.trim().toLowerCase()).filter((t) => t.length >= 3)
  const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const rows = p.recalls.map((r) => ({ ...r, hits: terms.filter((t) => new RegExp(`\\b${esc(t)}`).test((r.reason ?? '').toLowerCase())) }))
  const matched = rows.filter((r) => r.hits.length).map((r) => r.id)
  return {
    rows,
    matched,
    summary: terms.length
      ? `${matched.length} of ${rows.length} listed recall(s) name the flagged failure-mode term(s) (${terms.join(', ')}) in the recall reason (a text match, not a finding).`
      : 'No failure-mode term was given, so recall reasons were not matched.',
  }
}

// ── note to file + export (pms/note_to_file.py) ──────────────────────────────
export const NOTE_LABEL = 'Draft note to file for your QMS; not filed with FDA.'
export const BLANK_FIELD = '____________________'
export const DECISIONS = { note_to_file: 'Note to file', capa: 'Open a CAPA (in your QMS)', escalate: 'Escalate' } as const
export type Decision = keyof typeof DECISIONS

export interface Note {
  pack: EvidencePack
  decision: Decision
  rationale: string
  approver: string
  decided_utc: string
  audit_seq: number
  version: string
  commit: string
}

export function headerLines(n: Pick<Note, 'pack' | 'version' | 'commit'>): string[] {
  return [
    `Build: MaudeSignal ${n.version} · commit ${n.commit}`,
    `Data as of: ${n.pack.as_of.latest ?? 'not stated'} — ${asOfText(n.pack.as_of)}`,
    `Company complaint / CAPA number: ${BLANK_FIELD} (fill in your QMS)`,
  ]
}

const pct = (x: number | null) => (x === null ? 'n/a' : `${Math.round(x * 100)}%`)

export function noteMarkdown(n: Note): string {
  const p = n.pack
  const L: string[] = [
    `# Note to file — ${p.product_code}${p.device_type ? ` (${p.device_type})` : ''}`,
    '',
    `**${NOTE_LABEL}**`,
    '',
    ...headerLines(n).map((h) => `- ${h}`),
    `- Date: ${n.decided_utc.slice(0, 10)}`,
    `- Product code: ${p.product_code}`,
    '',
    '## Why flagged',
    '',
    p.why,
    '',
    '## Counts',
    '',
    ...p.counts.map((c) => `- ${c.label}: ${c.value}${c.url ? ` · ${c.url}` : ''}`),
    '',
    '## Reports NOT filed by a manufacturer (check these against your complaint log)',
    '',
    ...(p.non_manufacturer.length
      ? p.non_manufacturer.map((r) => `- ${r.report_id} · ${r.date_received ?? 'date not stated'} · ${r.source ?? 'filer not stated'} · ${r.url}`)
      : [p.origin === 'alert' ? '- Filer type is not listed per report in this alert; see the who-filed counts on Signals.' : '- None listed in this answer.']),
    '',
    '## Reports',
    '',
    `${p.reports.length} report(s) in this pack:`,
    '',
    ...p.reports.map((r) => `- ${r.report_id} · ${r.date_received ?? 'date not stated'} · ${r.event_type ?? 'event type not in this answer'}${r.source ? ` · ${r.source}` : ''} · ${r.url}`),
    '',
    '## Recalls',
    '',
    ...(p.recalls.length
      ? p.recalls.map((r) => `- ${r.id} · ${r.date ?? 'date not stated'} · ${r.reason ?? 'reason not stored'}${r.url ? ` · ${r.url}` : ''}`)
      : ['- No recall listed in this pack.']),
    ...(p.recalls_total != null && p.recalls_total > p.recalls.length ? [`- (${p.recalls.length} of ${p.recalls_total} recall records listed; the rest are on openFDA.)`] : []),
    '',
    '## Escalation checklist (human decides)',
    '',
    ...escalationChecklist(p).map((c) => `- [ ] ${c.item} (${c.basis}): ${c.question} Evidence: ${c.evidence.join(', ') || 'none listed'}`),
    '',
    '## Risk inputs (ISO 14971; counts, not rates)',
    '',
    ...(p.event_types_known
      ? severityMix(p).map((m) => `- ${m.event_type}: ${m.count} of ${m.of} (${pct(m.share)})`)
      : ['- Event types are not in this answer; open the openFDA queries above for the Death / Injury / Malfunction split.']),
    `- ${OCCURRENCE_NOTE}`,
    `- [ ] ${DETECTABILITY_QUESTION}`,
    '',
    '## Recall check (question, not answer)',
    '',
    `- ${recallCheck(p).summary}`,
    '- [ ] Does this meet your recall procedure?',
    '',
    '## Decision (made by the person named below)',
    '',
    `- Decision: ${DECISIONS[n.decision]}`,
    `- Rationale (typed by the approver): ${n.rationale}`,
    `- Approver: ${n.approver}`,
    `- Recorded: ${n.decided_utc} (browser audit entry #${n.audit_seq})`,
    '',
    'Signature (in your QMS): ____________________   Date: __________',
    '',
    'MaudeSignal prepares evidence only. It does not decide reportability, recall or CAPA need, and nothing is filed with FDA. This build is not validated.',
  ]
  return L.join('\n') + '\n'
}

const csvCell = (v: string | null | undefined): string => {
  const s = v ?? ''
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

export function reportsCsv(n: Pick<Note, 'pack' | 'version' | 'commit'>): string {
  const rows = [
    ...headerLines(n).map((h) => [`# ${h}`]),
    ['report_id', 'date_received', 'event_type', 'source', 'not_filed_by_manufacturer', 'url'],
    ...n.pack.reports.map((r) => [
      r.report_id,
      r.date_received ?? '',
      r.event_type ?? '',
      r.source ?? '',
      r.source ? String(!isMaker(r.source)) : '',
      r.url,
    ]),
  ]
  return rows.map((r) => r.map(csvCell).join(',')).join('\r\n') + '\r\n'
}
