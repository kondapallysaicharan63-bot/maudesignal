// "Investigate a complaint" (F25): the call to POST /v1/investigate, the parser for its answer and the plain-text
// evidence file. Contract: web/DATA_CONTRACT.md, "Investigate a complaint".
//
// URL contract for other pages (for example a simulated device profile): link to
//   /investigate?code=XXX&device=<simulated device id>
// `code` (three letters) fills the product code box; `device` is the id of a simulated device, shown as "From the
// simulated device <id>" and never sent anywhere. Neither is required. The folder the app is served from, ?layout and
// ?r= are kept as on every v2 link. Build the address with hrefFor({ page: 'investigate', code, device }).
//
// Nothing here invents a number: every figure comes from the API answer (or the recorded fixture) and keeps its openFDA
// link; an address that is not on https://api.fda.gov/ is dropped. The problem description is sent once, is never
// stored on the server or in this browser, and is not part of the answer.
import { apiBaseFrom } from '../liveCheck'

export { apiBaseFrom }

export const INVESTIGATE_PATH = '/v1/investigate'
export const MAX_DESCRIPTION = 500
export const MIN_DESCRIPTION = 5
/** Longer than the server's own time limit (about 40 s, never more than 45 s). */
export const INVESTIGATE_TIMEOUT_MS = 48_000
/** Always visible above the form. */
export const BANNER = 'Do not enter patient data. Describe the device problem only.'
/** Fixed notice, word for word; the last paragraph of the evidence text. */
export const NOTICE =
  'This is evidence assembled from public FDA data to attach to your complaint record, your MDR-reportability assessment (21 CFR 803) and your PMS board. MaudeSignal does not decide reportability, similarity, or whether a CAPA is needed; your team does.'
export const AS_ENTERED = 'as entered by the user; not stored'
export const OPENFDA_PREFIX = 'https://api.fda.gov/'

export interface Counted {
  value: number
  url: string
}
export interface MonthRow {
  month: string
  code_wide: number
  code_wide_url: string
  keyword_matched: number | null
  keyword_url: string | null
  partial: boolean
}
export interface Quote {
  report_number: string | null
  mdr_report_key: string
  date_received: string | null
  source: string
  maker: string | null
  quote: string
  truncated: boolean
  keywords_in_quote: string[]
  url: string
  gate: string
}
export interface ListedReport {
  report_number: string | null
  mdr_report_key: string
  date_received: string | null
  source: string
  maker: string | null
  url: string
}
export interface SourceBucket {
  source: string
  normalized: string
  count: number
}
export interface SourcesBlock {
  buckets: SourceBucket[]
  buckets_url: string
  manufacturer_count: number
  non_manufacturer: Counted
  no_source_count: number
  reports: ListedReport[]
  note: string | null
}
export interface RecallItem {
  recall_number: string
  firm: string | null
  status: string | null
  date_initiated: string | null
  reason: string
  url: string
}
export interface ClearanceItem {
  k_number: string
  device_name: string
  applicant: string | null
  decision_date: string | null
  url: string
}
export interface Investigation {
  mode: 'live' | 'recorded'
  product_code: string
  device_type_name: string | null
  retrieved_utc: string
  retrieved_date: string
  window_start: string
  window_end: string
  keywords: string[]
  keyword_rule: string
  months: MonthRow[]
  total_code_wide: Counted
  total_keyword_matched: Counted | null
  quotes: Quote[]
  sources: SourcesBlock | null
  recalls: { total: Counted | null; items: RecallItem[]; note: string | null }
  clearances: { total: Counted | null; items: ClearanceItem[]; note: string | null }
  dropped: { quote_not_verbatim: number; quote_personal_details: number; quote_wording: number; record_not_confirmed: number }
  own_maker_note: string
  lag_note: string
  notice: string
  source_note: string | null
  notes: string[]
}

export type Failure = 'unconfigured' | 'timeout' | 'patient_data' | 'invalid' | 'rate' | 'unavailable' | 'network' | 'bad-response'
export type Outcome = { ok: true; answer: Investigation } | { ok: false; kind: Failure; message: string }

// ── parsing ──────────────────────────────────────────────────────────────────
type Rec = Record<string, unknown>
const rec = (v: unknown): Rec | null => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Rec) : null)
const str = (v: unknown): string => (typeof v === 'string' ? v : '')
const strOrNull = (v: unknown): string | null => (typeof v === 'string' && v !== '' ? v : null)
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const list = (v: unknown): unknown[] => (Array.isArray(v) ? v : [])

/** An address on openFDA, or '' (never a link to anywhere else). */
export const fdaUrl = (v: unknown): string => (typeof v === 'string' && v.startsWith(OPENFDA_PREFIX) ? v : '')

function counted(v: unknown): Counted | null {
  const r = rec(v)
  const value = r ? num(r.value) : null
  return r && value !== null ? { value, url: fdaUrl(r.url) } : null
}

/** Reads an API answer (or the recorded fixture's `answer`); null when the main figures are missing. */
export function parseInvestigation(body: unknown): Investigation | null {
  const r = rec(body)
  if (!r) return null
  const total = counted(r.total_code_wide)
  const code = str(r.product_code)
  if (!total || !/^[A-Z]{3}$/.test(code)) return null
  const months: MonthRow[] = []
  for (const m of list(r.months)) {
    const o = rec(m)
    const cw = o ? num(o.code_wide) : null
    if (!o || cw === null || !/^\d{4}-\d{2}$/.test(str(o.month))) return null
    months.push({
      month: str(o.month),
      code_wide: cw,
      code_wide_url: fdaUrl(o.code_wide_url),
      keyword_matched: num(o.keyword_matched),
      keyword_url: fdaUrl(o.keyword_url) || null,
      partial: o.partial === true,
    })
  }
  const quotes: Quote[] = []
  for (const q of list(r.quotes)) {
    const o = rec(q)
    if (!o || !str(o.quote) || !str(o.mdr_report_key)) continue
    quotes.push({
      report_number: strOrNull(o.report_number),
      mdr_report_key: str(o.mdr_report_key),
      date_received: strOrNull(o.date_received),
      source: str(o.source),
      maker: strOrNull(o.maker),
      quote: str(o.quote),
      truncated: o.truncated === true,
      keywords_in_quote: list(o.keywords_in_quote).map(str),
      url: fdaUrl(o.url),
      gate: str(o.gate),
    })
  }
  let sources: SourcesBlock | null = null
  const s = rec(r.sources)
  const nm = s ? counted(s.non_manufacturer) : null
  if (s && nm) {
    sources = {
      buckets: list(s.buckets).flatMap((b) => {
        const o = rec(b)
        const c = o ? num(o.count) : null
        return o && c !== null ? [{ source: str(o.source), normalized: str(o.normalized), count: c }] : []
      }),
      buckets_url: fdaUrl(s.buckets_url),
      manufacturer_count: num(s.manufacturer_count) ?? 0,
      non_manufacturer: nm,
      no_source_count: num(s.no_source_count) ?? 0,
      reports: list(s.reports).flatMap((x) => {
        const o = rec(x)
        if (!o || !str(o.mdr_report_key)) return []
        return [
          {
            report_number: strOrNull(o.report_number),
            mdr_report_key: str(o.mdr_report_key),
            date_received: strOrNull(o.date_received),
            source: str(o.source),
            maker: strOrNull(o.maker),
            url: fdaUrl(o.url),
          },
        ]
      }),
      note: strOrNull(s.note),
    }
  }
  const rc = rec(r.recalls)
  const cl = rec(r.clearances)
  const dr = rec(r.dropped) ?? {}
  return {
    mode: r.mode === 'recorded' ? 'recorded' : 'live',
    product_code: code,
    device_type_name: strOrNull(r.device_type_name),
    retrieved_utc: str(r.retrieved_utc),
    retrieved_date: str(r.retrieved_date),
    window_start: str(r.window_start),
    window_end: str(r.window_end),
    keywords: list(r.keywords).map(str).filter(Boolean),
    keyword_rule: str(r.keyword_rule),
    months,
    total_code_wide: total,
    total_keyword_matched: counted(r.total_keyword_matched),
    quotes,
    sources,
    recalls: {
      total: rc ? counted(rc.total) : null,
      items: list(rc?.items).flatMap((x) => {
        const o = rec(x)
        if (!o || !str(o.recall_number)) return []
        return [
          {
            recall_number: str(o.recall_number),
            firm: strOrNull(o.firm),
            status: strOrNull(o.status),
            date_initiated: strOrNull(o.date_initiated),
            reason: str(o.reason),
            url: fdaUrl(o.url),
          },
        ]
      }),
      note: rc ? strOrNull(rc.note) : null,
    },
    clearances: {
      total: cl ? counted(cl.total) : null,
      items: list(cl?.items).flatMap((x) => {
        const o = rec(x)
        if (!o || !str(o.k_number)) return []
        return [
          {
            k_number: str(o.k_number),
            device_name: str(o.device_name),
            applicant: strOrNull(o.applicant),
            decision_date: strOrNull(o.decision_date),
            url: fdaUrl(o.url),
          },
        ]
      }),
      note: cl ? strOrNull(cl.note) : null,
    },
    dropped: {
      quote_not_verbatim: num(dr.quote_not_verbatim) ?? 0,
      quote_personal_details: num(dr.quote_personal_details) ?? 0,
      quote_wording: num(dr.quote_wording) ?? 0,
      record_not_confirmed: num(dr.record_not_confirmed) ?? 0,
    },
    own_maker_note: str(r.own_maker_note),
    lag_note: str(r.lag_note),
    notice: NOTICE, // fixed text; the server's copy is the same words
    source_note: strOrNull(r.source_note),
    notes: list(r.notes).map(str).filter(Boolean),
  }
}

// ── the call ─────────────────────────────────────────────────────────────────
export type Fetcher = (url: string, init?: RequestInit) => Promise<Response>

/** The error code of an API error body: `code` or `error.code`. */
function errorOf(body: unknown): { code: string; message: string } {
  const r = rec(body)
  const e = rec(r?.error)
  return { code: str(r?.code) || str(e?.code), message: (str(r?.message) || str(e?.message)).slice(0, 400) }
}

/** Asks the API. Only the product code and the description are sent; nothing is kept. */
export async function investigate(
  code: string,
  description: string,
  deps: { fetcher: Fetcher; apiBase: string | null; timeoutMs?: number },
): Promise<Outcome> {
  if (!deps.apiBase) return { ok: false, kind: 'unconfigured', message: 'This site is not connected to the MaudeSignal API.' }
  const ctl = new AbortController()
  const timer = setTimeout(() => ctl.abort(), deps.timeoutMs ?? INVESTIGATE_TIMEOUT_MS)
  let res: Response
  try {
    res = await deps.fetcher(`${deps.apiBase}${INVESTIGATE_PATH}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ product_code: code, description }),
      credentials: 'omit',
      signal: ctl.signal,
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError')
      return { ok: false, kind: 'timeout', message: 'The search took too long and was stopped. Nothing is shown. Try again, or try a narrower description.' }
    return { ok: false, kind: 'network', message: 'The service could not be reached. Nothing was investigated; try again later.' }
  } finally {
    clearTimeout(timer)
  }
  let body: unknown = null
  try {
    body = await res.json()
  } catch {
    body = null
  }
  if (res.status === 200) {
    const answer = parseInvestigation(body)
    return answer
      ? { ok: true, answer }
      : { ok: false, kind: 'bad-response', message: 'The answer could not be read, so nothing is shown.' }
  }
  const e = errorOf(body)
  if (res.status === 422 && e.code === 'patient_data') return { ok: false, kind: 'patient_data', message: e.message || 'Please remove patient details and send again.' }
  if (res.status === 422) return { ok: false, kind: 'invalid', message: e.message || 'The product code or the description could not be used.' }
  if (res.status === 429) return { ok: false, kind: 'rate', message: e.message || 'Limit reached. Try again later.' }
  if (res.status === 502 || res.status === 503) return { ok: false, kind: 'unavailable', message: e.message || 'openFDA could not be reached just now. Nothing was investigated.' }
  return { ok: false, kind: 'bad-response', message: 'The service returned an error. Nothing is shown.' }
}

// ── the evidence text ────────────────────────────────────────────────────────
const ymd = (s: string): string => (/^\d{8}$/.test(s) ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}` : s)
const n = (x: number): string => x.toLocaleString('en-US')
const SOURCE_NAMES: Record<string, string> = { manufacturer: 'manufacturer', 'user facility': 'user facility', voluntary: 'voluntary reporter', distributor: 'distributor' }
export const sourceName = (s: string): string => SOURCE_NAMES[s] ?? (s || 'not stated')

/** When the search ran, to the minute, in UTC: "2026-11-01 14:05 UTC". */
export const stamp = (iso: string): string => (iso.length >= 16 ? `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC` : iso)

/**
 * Plain text for the complaint file: what was searched, every count with its openFDA query, the quotes, the recalls and
 * 510(k)s, and the fixed notice. The description is printed as entered and marked as not stored.
 */
export function evidenceText(a: Investigation, description: string): string {
  const L: string[] = []
  const h = (t: string) => L.push('', t.toUpperCase(), '')
  L.push('EVIDENCE FOR THE COMPLAINT FILE')
  L.push(a.mode === 'recorded' ? 'RECORDED EXAMPLE (a stored copy of FDA data, not a live search)' : 'Real FDA data (openFDA), retrieved live')
  L.push('')
  L.push(a.mode === 'recorded' ? `Stored copy date: ${a.retrieved_date} (no live search was made)` : `Search date and time: ${stamp(a.retrieved_utc)}`)
  L.push(`Product code: ${a.product_code}`)
  L.push(`FDA device type name: ${a.device_type_name ?? 'not available'}`)
  L.push(`Window: reports received ${ymd(a.window_start)} to ${ymd(a.window_end)} (12 calendar months)`)
  L.push(`Problem description (${AS_ENTERED}):`)
  L.push(`  ${description.replace(/\s+/g, ' ').trim()}`)
  L.push(`Keywords taken from it: ${a.keywords.length ? a.keywords.join(', ') : 'none'}`)
  if (a.source_note) L.push(a.source_note)

  h('1. MAUDE reports for this product code (any maker), by month')
  L.push('Two different counts, never added together:')
  L.push('  A = reports for the whole product code')
  L.push('  B = of those, reports whose narrative mentions at least one keyword (a text match; not a finding of similarity)')
  L.push('')
  for (const m of a.months) {
    L.push(`${m.month}${m.partial ? ' (partial month)' : ''}  A: ${n(m.code_wide)}${m.keyword_matched === null ? '' : `  B: ${n(m.keyword_matched)}`}`)
    if (m.code_wide_url) L.push(`  A query: ${m.code_wide_url}`)
    if (m.keyword_url) L.push(`  B query: ${m.keyword_url}`)
  }
  L.push('')
  L.push(`Total A, 12 months: ${n(a.total_code_wide.value)}`)
  if (a.total_code_wide.url) L.push(`  Query: ${a.total_code_wide.url}`)
  if (a.total_keyword_matched) {
    L.push(`Total B, 12 months: ${n(a.total_keyword_matched.value)}`)
    if (a.total_keyword_matched.url) L.push(`  Query: ${a.total_keyword_matched.url}`)
  }
  L.push(a.lag_note)
  L.push(`Reports of your own company: ${a.own_maker_note}`)

  h('Quotes from report narratives (text as filed, not edited; each checked against its own report)')
  if (a.quotes.length === 0) L.push('None shown.')
  a.quotes.forEach((q, i) => {
    L.push(`${i + 1}. Report ${q.report_number ?? q.mdr_report_key} (MDR report key ${q.mdr_report_key}), received ${q.date_received ? ymd(q.date_received) : 'date not stated'}`)
    L.push(`   Filed by: ${sourceName(q.source)}; maker as written: ${q.maker ?? 'not stated'}`)
    L.push(`   "${q.quote}"${q.truncated ? ' [sentence continues in the report]' : ''}`)
    if (q.url) L.push(`   Report query: ${q.url}`)
  })

  h('2. Reports about this product code not filed by a manufacturer')
  if (!a.sources) L.push('Could not be read.')
  else {
    for (const b of a.sources.buckets) L.push(`${b.source}: ${n(b.count)}`)
    if (a.sources.no_source_count > 0) L.push(`No filer type on the report: ${n(a.sources.no_source_count)}`)
    if (a.sources.buckets_url) L.push(`  Query: ${a.sources.buckets_url}`)
    L.push(`Not filed by a manufacturer: ${n(a.sources.non_manufacturer.value)}`)
    if (a.sources.non_manufacturer.url) L.push(`  Query: ${a.sources.non_manufacturer.url}`)
    for (const r of a.sources.reports) {
      L.push(`  Report ${r.report_number ?? r.mdr_report_key}, ${r.date_received ? ymd(r.date_received) : 'date not stated'}, ${sourceName(r.source)}${r.maker ? `, ${r.maker}` : ''}`)
      if (r.url) L.push(`    ${r.url}`)
    }
  }

  h('3. Recalls and 510(k)s for this product code')
  L.push('Recalls')
  if (!a.recalls.total) L.push(a.recalls.note ?? 'Could not be read.')
  else {
    L.push(`Recall records, all dates: ${n(a.recalls.total.value)}`)
    if (a.recalls.total.url) L.push(`  Query: ${a.recalls.total.url}`)
    for (const r of a.recalls.items) {
      L.push(`  ${r.recall_number}, ${r.firm ?? 'firm not stated'}, ${r.status ?? 'status not stated'}, started ${r.date_initiated ?? 'date not stated'}`)
      if (r.reason) L.push(`    Reason: ${r.reason}`)
      if (r.url) L.push(`    ${r.url}`)
    }
  }

  L.push('', '510(k) clearances')
  if (!a.clearances.total) L.push(a.clearances.note ?? 'Could not be read.')
  else {
    L.push(`510(k) records, all dates: ${n(a.clearances.total.value)}`)
    if (a.clearances.total.url) L.push(`  Query: ${a.clearances.total.url}`)
    for (const c of a.clearances.items) {
      L.push(`  ${c.k_number}, ${c.device_name}${c.applicant ? `, ${c.applicant}` : ''}, decision ${c.decision_date ?? 'date not stated'}`)
      if (c.url) L.push(`    ${c.url}`)
    }
  }
  const left = a.dropped
  const total = left.quote_not_verbatim + left.quote_personal_details + left.quote_wording + left.record_not_confirmed
  if (total > 0) L.push('', `Left out because they did not pass the checks: ${total}`)
  for (const note of a.notes) L.push('', note)
  L.push('', 'NOTICE', '', NOTICE, '')
  return L.join('\n')
}

/** File name for the download: product code and date, no description. */
export const evidenceFileName = (a: Investigation): string => `complaint-evidence-${a.product_code}-${a.retrieved_date || 'undated'}.txt`
