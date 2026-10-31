// Alert detail (web/public/data/alerts.json): types, lookup and the plain-words lines of the panel.
// Every number in the file was recomputed from stored rows by scripts/export_alerts.py; nothing here adds one.
import type { AlertItem } from './dashboard'

export type AlertRule = 'reports suddenly increased' | 'more serious than usual' | 'new kind of problem'

export interface AlertNumber {
  label: string
  value: number | string
  openfda_url: string
}
export interface AlertReport {
  report_id: string
  date_received: string | null
  event_type: string | null
  /** A sentence copied word for word from the stored report and passed by the claim gate; null when none could be quoted. */
  quote: string | null
  quote_note?: string | null
  openfda_url: string
  maude_url?: string
}
export interface AlertRecall {
  id: string
  date: string | null
  reason: string | null
  reason_truncated?: boolean
  url: string | null
}
export interface AlertK510 {
  k_number: string
  applicant: string
  decision_date: string
  url: string | null
}
export interface WindowPart {
  from: string
  to: string
  count: number | null
}
export interface AlertWindow {
  this_week: WindowPart
  baseline_4wk: WindowPart & { weekly_mean: number | null }
}
export interface AlertGate {
  checked: number
  passed: number
  withheld: number
}
export interface AlertOwner {
  name: string
  status: string | null
  device_id?: string
  device_name?: string
}
export interface AlertDetail {
  id: string
  product_code: string
  device_type: string | null
  rule: AlertRule | null
  rule_words: string
  source: { kind: 'sweep' | 'brief' | 'company'; label: string; as_of: string | null }
  window: AlertWindow | null
  numbers: AlertNumber[]
  reports: AlertReport[]
  reports_total: number | null
  reports_stored: number | null
  recalls: AlertRecall[]
  recalls_total: number
  k510: AlertK510[]
  k510_total: number
  who_filed: { manufacturer: number; user_facility: number; other: number } | null
  next_steps: string[]
  owner: AlertOwner | null
  gate: AlertGate
  notes: string[]
}
export interface AlertsFile {
  schema_version: string
  generated_utc: string
  banner: string
  alerts: AlertDetail[]
  notes: string[]
}

/** The banner printed over the simulated company's devices (the contract string). */
export const SIMULATED_BANNER = 'Simulated company — sample data. Problem evidence is real FDA data.'

export const NO_DETAIL_TEXT = 'No stored detail exists for this alert yet.'

/** The alert with this id; when the id is not stored, the first stored alert for the same product code. */
export function findAlert(file: AlertsFile | null | undefined, id: string, code?: string): AlertDetail | null {
  if (!file || !Array.isArray(file.alerts)) return null
  const exact = file.alerts.find((a) => a.id === id)
  if (exact) return exact
  if (!code) return null
  return file.alerts.find((a) => a.product_code === code) ?? null
}

/** The stored detail for a bell/dashboard item. */
export const detailFor = (file: AlertsFile | null | undefined, a: AlertItem): AlertDetail | null => findAlert(file, a.id, a.productCode)

/** "13 facts checked, 12 passed, 1 held back" */
export function gateLine(g: AlertGate): string {
  return `${g.checked} ${g.checked === 1 ? 'fact' : 'facts'} checked, ${g.passed} passed, ${g.withheld} held back`
}

/** "showing 10 of 21" (of the total the rule counted). */
export const showingLine = (shown: number, total: number | null): string => `showing ${shown} of ${total ?? shown}`

/** Only https links are ever rendered as links. */
export const safeUrl = (u: string | null | undefined): string | null => (u && /^https:\/\//.test(u) ? u : null)

/** "2026-09-24 to 2026-09-30" */
export const rangeLine = (p: { from: string; to: string }): string => `${p.from} to ${p.to}`

/** The question "Open in chat" sends: the code and the alert's rule in words. Nothing else leaves the page. */
export function chatQuestion(a: Pick<AlertDetail, 'product_code' | 'rule'>): string {
  return a.rule
    ? `Why was ${a.product_code} flagged as "${a.rule}" this week, and what changed?`
    : `What changed for ${a.product_code} this week?`
}

/** Light check of the file's shape; null when it is not an alerts file. */
export function parseAlerts(raw: unknown): AlertsFile | null {
  if (typeof raw !== 'object' || raw === null) return null
  const o = raw as Record<string, unknown>
  if (!Array.isArray(o.alerts)) return null
  const alerts = o.alerts.filter((a): a is AlertDetail => {
    if (typeof a !== 'object' || a === null) return false
    const x = a as Partial<AlertDetail>
    return typeof x.id === 'string' && typeof x.product_code === 'string' && Array.isArray(x.next_steps)
  })
  return { ...(o as unknown as AlertsFile), alerts }
}

// A person's details inside a quoted sentence (mirrors has_personal_details in scripts/export_alerts.py).
// A name must start with a capital letter, so the two name patterns have no i flag.
const NOT_A_NAME =
  'was|is|has|had|did|who|with|and|in|on|the|a|an|experienced|reported|stated|states|developed|presented|underwent|were|information|identifier|identification|outcome|problem|age|weight|sex|gender|date|code|condition|death|safety|care|harm|injury|impact'
const PERSONAL: RegExp[] = [
  /\b(?:Dr|Mr|Mrs|Ms|Miss|Prof)\.?\s+[A-Z][a-z]+/,
  new RegExp(String.raw`\b[Pp]atient\s+(?!(?:${NOT_A_NAME})\b)[A-Z][a-z]+`),
  /\b\d{1,3}[- ]?(?:year|yr)s?[- ]?old\b/i,
  /\bage[d]?\s*:?\s*\d{1,3}\b/i,
  /[\w.+-]+@[\w-]+\.[\w.-]+/,
  /(?<!\d)(?:\+?1[ -.]?)?\(?\d{3}\)?[ -.]\d{3}[ -.]\d{4}(?!\d)/,
]

/** True when a sentence holds a title + name, "patient <Name>", an age, an email or a phone number. */
export const hasPersonalDetails = (text: string): boolean => PERSONAL.some((r) => r.test(text))
