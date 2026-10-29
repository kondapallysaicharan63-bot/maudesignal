// "Check any device type": the four detector rules, ported from src/maudesignal/monitor/live_check.py
// (classify_counts, build_window, _norm, verify_url, check_product_code). Same windows, same
// thresholds, same exact integer arithmetic. src/fixtures/liveCheckParity.json is generated from the
// Python code (python3 scripts/export_web_data.py --parity-fixtures) and liveCheck.test.ts checks
// that this file gives identical answers on every case.

export type Classification = 'new_signal' | 'severity_escalation' | 'spike' | 'stable'

export const BASELINE_WEEKS = 4
export const CURRENT_WINDOW_DAYS = 7
export const SPIKE_MULTIPLIER = 2
export const SPIKE_MIN_REPORTS = 3
export const SEVERITY_ESCALATION_PP = 15
export const SEVERE_EVENT_TYPES = ['injury', 'death']
export const UNKNOWN_EVENT_TYPE = 'unknown'
export const LOOKBACK_DAYS = 730
export const EARLIEST = '19900101'
export const OPENFDA_EVENT_ENDPOINT = 'https://api.fda.gov/device/event.json'

/** Order in which a flag outranks another (same as CLASSIFICATION_PRECEDENCE). */
export const PRECEDENCE: Classification[] = ['new_signal', 'severity_escalation', 'spike']

export const CHANGE_LABELS: Record<Classification, string> = {
  new_signal: 'new kind of problem',
  severity_escalation: 'more serious than usual',
  spike: 'reports suddenly increased',
  stable: 'no change',
}

export type TypeCounts = [string, number][]

export interface WindowCounts {
  current_total: number
  baseline_total: number
  prior_total: number
  current_types: TypeCounts
  baseline_types: TypeCounts
  prior_types: TypeCounts
}

export interface DetectionWindow {
  as_of: string
  current_start: string
  current_end: string
  baseline_start: string
  baseline_end: string
}

export interface LiveCheckResult {
  product_code: string
  as_of: string | null
  window: DetectionWindow | null
  classification: Classification
  triggers: Classification[]
  current_count: number
  current_severe_count: number
  current_severe_share: number | null
  baseline_count: number
  baseline_weekly_mean: number
  baseline_severe_count: number
  baseline_severe_share: number | null
  severe_share_delta_pp: number | null
  spike_ratio: number | null
  prior_report_count: number
  new_event_types: string[]
  current_event_type_counts: TypeCounts
  queries: [string, string][]
}

// ── dates (UTC, YYYYMMDD) ────────────────────────────────────────────────────
const DAY_MS = 86_400_000

export function parseYmd(s: string): number {
  return Date.UTC(Number(s.slice(0, 4)), Number(s.slice(4, 6)) - 1, Number(s.slice(6, 8)))
}

export function ymd(ms: number): string {
  const d = new Date(ms)
  const p = (n: number, w: number) => String(n).padStart(w, '0')
  return `${p(d.getUTCFullYear(), 4)}${p(d.getUTCMonth() + 1, 2)}${p(d.getUTCDate(), 2)}`
}

export function addDays(s: string, days: number): string {
  return ymd(parseYmd(s) + days * DAY_MS)
}

/** The 7 days ending on `asOf` against the 4 weeks before them (build_window). */
export function buildWindow(asOf: string): DetectionWindow {
  const currentStart = addDays(asOf, -(CURRENT_WINDOW_DAYS - 1))
  return {
    as_of: asOf,
    current_start: currentStart,
    current_end: asOf,
    baseline_start: addDays(currentStart, -7 * BASELINE_WEEKS),
    baseline_end: addDays(currentStart, -1),
  }
}

// ── arithmetic ───────────────────────────────────────────────────────────────
/**
 * round(x, digits) as Python does it: the exact value of the double is rounded, and an exact tie
 * goes to the even digit. toFixed rounds the exact value too (ties up), so ties are caught first.
 */
export function roundHalfEven(x: number, digits: number): number {
  const long = Math.abs(x).toFixed(digits + 30)
  const dot = long.indexOf('.')
  const tail = long.slice(dot + 1 + digits)
  let out: string
  if (/^50*$/.test(tail)) {
    const down = long.slice(0, dot + 1 + digits) // truncated toward zero
    const lastDigit = Number(down[down.length - 1] === '.' ? down[down.length - 2] : down[down.length - 1])
    out = lastDigit % 2 === 0 ? down : Math.abs(x).toFixed(digits)
  } else {
    out = Math.abs(x).toFixed(digits)
  }
  const v = Number(out)
  return x < 0 ? -v : v
}

/** Lower-case event types as the detector does; reports with no type count as unknown (_norm). */
export function normalizeTypes(rows: [string, number][], total: number): TypeCounts {
  const merged = new Map<string, number>()
  for (const [term, n] of rows) {
    const key = term.trim().toLowerCase() || UNKNOWN_EVENT_TYPE
    merged.set(key, (merged.get(key) ?? 0) + n)
  }
  let sum = 0
  for (const v of merged.values()) sum += v
  const missing = total - sum
  if (missing > 0) merged.set(UNKNOWN_EVENT_TYPE, (merged.get(UNKNOWN_EVENT_TYPE) ?? 0) + missing)
  return [...merged.entries()]
    .filter(([, v]) => v > 0)
    .sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] - b[1]))
}

const severe = (types: TypeCounts): number =>
  types.filter(([t]) => SEVERE_EVENT_TYPES.includes(t)).reduce((s, [, n]) => s + n, 0)

/** The detector's four rules applied to counts (classify_counts). No queries attached. */
export function classifyCounts(
  productCode: string,
  c: WindowCounts,
  w: DetectionWindow,
): Omit<LiveCheckResult, 'queries'> {
  const cur = c.current_total
  const base = c.baseline_total
  const prior = c.prior_total
  const curSev = severe(c.current_types)
  const baseSev = severe(c.baseline_types)
  const priorKinds = new Set(c.prior_types.filter(([, n]) => n > 0).map(([t]) => t))
  const curKinds = new Set(c.current_types.filter(([, n]) => n > 0).map(([t]) => t))
  const newTypes = prior ? [...curKinds].filter((t) => !priorKinds.has(t)).sort() : []

  const triggers: Classification[] = []
  if (cur && (!prior || newTypes.length > 0)) triggers.push('new_signal')

  // Injury/death share now minus before, in percentage points, compared without rounding:
  // (curSev/cur - baseSev/base) * 100 >= 15  <=>  100 * (curSev*base - baseSev*cur) >= 15 * cur * base.
  let delta: number | null = null
  if (cur && base) {
    const num = 100 * (curSev * base - baseSev * cur)
    const den = cur * base
    delta = num / den
    if (num >= SEVERITY_ESCALATION_PP * den) triggers.push('severity_escalation')
  }
  // spike: cur >= 2 * (base / 4) and cur >= 3, all in integers.
  if (cur >= SPIKE_MIN_REPORTS && cur * BASELINE_WEEKS >= SPIKE_MULTIPLIER * base) triggers.push('spike')

  const ordered = PRECEDENCE.filter((t) => triggers.includes(t))
  const mean = base / BASELINE_WEEKS
  return {
    product_code: productCode,
    as_of: w.as_of,
    window: w,
    classification: ordered[0] ?? 'stable',
    triggers: ordered,
    current_count: cur,
    current_severe_count: curSev,
    current_severe_share: cur ? roundHalfEven(curSev / cur, 4) : null,
    baseline_count: base,
    baseline_weekly_mean: mean,
    baseline_severe_count: baseSev,
    baseline_severe_share: base ? roundHalfEven(baseSev / base, 4) : null,
    severe_share_delta_pp: delta === null ? null : roundHalfEven(delta, 2),
    spike_ratio: base ? roundHalfEven((cur * BASELINE_WEEKS) / base, 2) : null,
    prior_report_count: prior,
    new_event_types: newTypes,
    current_event_type_counts: c.current_types,
  }
}

// ── openFDA requests ─────────────────────────────────────────────────────────
export function buildQuery(code: string, start: string | null, end: string | null): string {
  const clauses = [`device.device_report_product_code:${code}`]
  if (start && end) clauses.push(`date_received:[${start}+TO+${end}]`)
  else if (start) clauses.push(`date_received:[${start}+TO+99991231]`)
  else if (end) clauses.push(`date_received:[19900101+TO+${end}]`)
  return clauses.join('+AND+')
}

/** The public openFDA URL a reader can open to see a figure (verify_url; no key in it). */
export function verifyUrl(code: string, start: string | null, end: string | null, count?: string): string {
  const p = new URLSearchParams()
  p.set('search', buildQuery(code, start, end).replace(/\+/g, ' '))
  if (count) p.set('count', count)
  else p.set('limit', '1')
  return `${OPENFDA_EVENT_ENDPOINT}?${p.toString()}`
}

/** The same request with the bucket limit the Python client sends for counts. */
function requestUrl(code: string, start: string | null, end: string | null, count?: string): string {
  return count ? `${verifyUrl(code, start, end, count)}&limit=1000` : verifyUrl(code, start, end)
}

export const PRODUCT_CODE_RE = /^[A-Z]{3}$/

export function normalizeCode(text: string): string | null {
  const code = text.trim().toUpperCase()
  return PRODUCT_CODE_RE.test(code) ? code : null
}

export type FailureKind = 'network' | 'forbidden' | 'rate' | 'server' | 'bad-response'

export class LiveCheckFailure extends Error {
  constructor(
    public kind: FailureKind,
    message: string,
  ) {
    super(message)
  }
}

type Fetcher = (url: string) => Promise<Response>

async function getJson(fetcher: Fetcher, url: string): Promise<Record<string, unknown> | null> {
  let res: Response
  try {
    res = await fetcher(url)
  } catch {
    // CORS blocks and offline both surface as a TypeError with no detail.
    throw new LiveCheckFailure('network', 'The browser could not reach openFDA (offline, or the browser blocked the cross-origin request).')
  }
  if (res.status === 404) return null // openFDA answers 404 when nothing matches
  if (res.status === 403) throw new LiveCheckFailure('forbidden', 'openFDA refused the request (403).')
  if (res.status === 429) throw new LiveCheckFailure('rate', "openFDA's rate limit was reached (429).")
  if (!res.ok) throw new LiveCheckFailure('server', `openFDA returned HTTP ${res.status}.`)
  try {
    return (await res.json()) as Record<string, unknown>
  } catch {
    throw new LiveCheckFailure('bad-response', 'openFDA sent an answer that could not be read.')
  }
}

async function countField(
  f: Fetcher,
  code: string,
  field: string,
  start: string | null,
  end: string | null,
): Promise<[string, number][]> {
  const payload = await getJson(f, requestUrl(code, start, end, field))
  const rows = Array.isArray(payload?.results) ? (payload?.results as Record<string, unknown>[]) : []
  return rows
    .map((r): [string, number] => [String(r.term ?? r.time), Number(r.count)])
    .sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
}

async function total(f: Fetcher, code: string, start: string | null, end: string | null): Promise<number> {
  const payload = await getJson(f, requestUrl(code, start, end))
  const meta = payload?.meta as { results?: { total?: number } } | undefined
  return Number(meta?.results?.total ?? 0)
}

/**
 * One product code, as of its latest report (check_product_code with as_of=None): per-day counts
 * for the last 730 days, event-type counts per window, and the total before the window.
 */
export async function runLiveCheck(codeIn: string, todayYmd: string, f: Fetcher): Promise<LiveCheckResult> {
  const code = normalizeCode(codeIn)
  if (!code) throw new Error('A product code is three letters, for example LLZ or QIH.')
  const lookFrom = addDays(todayYmd, -LOOKBACK_DAYS)
  const days = (await countField(f, code, 'date_received', lookFrom, todayYmd)).filter(([, n]) => n > 0)
  if (days.length === 0) {
    const all = await total(f, code, null, null)
    return {
      product_code: code,
      as_of: null,
      window: null,
      classification: 'stable',
      triggers: [],
      current_count: 0,
      current_severe_count: 0,
      current_severe_share: null,
      baseline_count: 0,
      baseline_weekly_mean: 0,
      baseline_severe_count: 0,
      baseline_severe_share: null,
      severe_share_delta_pp: null,
      spike_ratio: null,
      prior_report_count: all,
      new_event_types: [],
      current_event_type_counts: [],
      queries: [['Reports, all dates', verifyUrl(code, null, null)]],
    }
  }
  const asOf = days.reduce((m, [d]) => (d > m ? d : m), days[0][0])
  const w = buildWindow(asOf)
  const cs = w.current_start
  const ce = w.current_end
  const bs = w.baseline_start
  const be = w.baseline_end
  const before = addDays(cs, -1)
  const inRange = (a: string, b: string) => days.filter(([d]) => d >= a && d <= b).reduce((s, [, n]) => s + n, 0)

  let curTotal: number
  let baseTotal: number
  if (bs >= lookFrom) {
    curTotal = inRange(cs, ce)
    baseTotal = inRange(bs, be)
  } else {
    curTotal = await total(f, code, cs, ce)
    baseTotal = await total(f, code, bs, be)
  }
  const priorTotal = await total(f, code, EARLIEST, before)
  const types = async (a: string, b: string, n: number, needed: boolean): Promise<TypeCounts> =>
    needed && n ? normalizeTypes(await countField(f, code, 'event_type.exact', a, b), n) : []
  const counts: WindowCounts = {
    current_total: curTotal,
    baseline_total: baseTotal,
    prior_total: priorTotal,
    current_types: await types(cs, ce, curTotal, true),
    baseline_types: await types(bs, be, baseTotal, true),
    prior_types: await types(EARLIEST, before, priorTotal, curTotal > 0),
  }
  return {
    ...classifyCounts(code, counts, w),
    queries: [
      ['Reports per day (latest date, both windows)', verifyUrl(code, lookFrom, todayYmd, 'date_received')],
      ['This week, by event type', verifyUrl(code, cs, ce, 'event_type.exact')],
      ['4 weeks before, by event type', verifyUrl(code, bs, be, 'event_type.exact')],
      ['Everything before this week', verifyUrl(code, EARLIEST, before)],
      ['Everything before this week, by event type', verifyUrl(code, EARLIEST, before, 'event_type.exact')],
    ],
  }
}

// ── plain words (dashboard/live_check_ui.reason) ─────────────────────────────
const pct = (x: number | null): string => (x === null ? '—' : `${(x * 100).toFixed(0)}%`)

export function reasonText(r: LiveCheckResult): string {
  if (r.as_of === null) return 'No report in the last two years, so there is no current week to compare.'
  if (r.classification === 'new_signal') {
    if (!r.prior_report_count) return `First reports ever for this device type: ${r.current_count} this week.`
    return `A kind of report never seen before for this device type: ${r.new_event_types.join(', ')}.`
  }
  if (r.classification === 'severity_escalation')
    return (
      `Injury or death in ${pct(r.current_severe_share)} of this week's reports against ` +
      `${pct(r.baseline_severe_share)} in the 4 weeks before (+${(r.severe_share_delta_pp ?? 0).toFixed(0)} points).`
    )
  if (r.classification === 'spike')
    return (
      `${r.current_count} reports this week against a weekly mean of ${r.baseline_weekly_mean.toFixed(2)} ` +
      `in the 4 weeks before (${(r.spike_ratio ?? 0).toFixed(2)}×).`
    )
  return `No rule fired: ${r.current_count} report(s) this week against a weekly mean of ${r.baseline_weekly_mean.toFixed(2)} before.`
}

// ── client-side limits: 10 checks per browser session, 6-hour cache per code ─
export const SESSION_CHECKS = 10
export const CACHE_MS = 6 * 3600 * 1000
const COUNT_KEY = 'ms-live-checks'
const CACHE_PREFIX = 'ms-live-cache:'

/** Minimal Storage shape so tests can pass a fake (and a throwing one). */
export interface KeyStore {
  getItem(k: string): string | null
  setItem(k: string, v: string): void
}

/** Used when sessionStorage / localStorage is blocked, so the limit still holds for this page. */
const memory = { used: 0, cache: new Map<string, { at: number; result: LiveCheckResult }>() }

export function checksUsed(session: KeyStore | null): number {
  try {
    const v = Number(session?.getItem(COUNT_KEY) ?? 0)
    return Math.max(Number.isFinite(v) ? v : 0, memory.used)
  } catch {
    return memory.used
  }
}

export function recordCheck(session: KeyStore | null): number {
  const n = checksUsed(session) + 1
  memory.used = n
  try {
    session?.setItem(COUNT_KEY, String(n))
  } catch {
    /* memory counter still holds */
  }
  return n
}

export function readCache(local: KeyStore | null, code: string, now: number): LiveCheckResult | null {
  const hit = memory.cache.get(code)
  if (hit && now - hit.at < CACHE_MS) return hit.result
  try {
    const raw = local?.getItem(CACHE_PREFIX + code)
    if (!raw) return null
    const v = JSON.parse(raw) as { at: number; result: LiveCheckResult }
    return typeof v.at === 'number' && now - v.at < CACHE_MS && v.result?.product_code === code ? v.result : null
  } catch {
    return null
  }
}

export function writeCache(local: KeyStore | null, code: string, now: number, result: LiveCheckResult): void {
  memory.cache.set(code, { at: now, result })
  try {
    local?.setItem(CACHE_PREFIX + code, JSON.stringify({ at: now, result }))
  } catch {
    /* ignore */
  }
}

/** For tests: forget the in-memory fallbacks. */
export function resetLiveCheckMemory(): void {
  memory.used = 0
  memory.cache.clear()
}

export function browserStore(kind: 'session' | 'local'): KeyStore | null {
  try {
    return kind === 'session' ? window.sessionStorage : window.localStorage
  } catch {
    return null
  }
}

export type CheckOutcome =
  | { ok: true; result: LiveCheckResult; cached: boolean; used: number }
  | { ok: false; kind: 'limit' | 'invalid' | FailureKind; message: string; used: number }

/** Limit, cache, then openFDA. A failure is returned, never replaced by a made-up result. */
export async function checkDevice(
  text: string,
  deps: { fetcher: Fetcher; session: KeyStore | null; local: KeyStore | null; now?: number },
): Promise<CheckOutcome> {
  const now = deps.now ?? Date.now()
  const code = normalizeCode(text)
  const used = checksUsed(deps.session)
  if (!code) return { ok: false, kind: 'invalid', message: 'A product code is three letters, for example LLZ or QIH.', used }
  const cached = readCache(deps.local, code, now)
  if (cached) return { ok: true, result: cached, cached: true, used }
  if (used >= SESSION_CHECKS)
    return {
      ok: false,
      kind: 'limit',
      message: `This browser session has used its ${SESSION_CHECKS} live checks. Use the Streamlit app for more checks.`,
      used,
    }
  try {
    const result = await runLiveCheck(code, ymd(now), deps.fetcher)
    writeCache(deps.local, code, now, result)
    return { ok: true, result, cached: false, used: recordCheck(deps.session) }
  } catch (e) {
    if (e instanceof LiveCheckFailure) return { ok: false, kind: e.kind, message: e.message, used }
    return { ok: false, kind: 'bad-response', message: e instanceof Error ? e.message : String(e), used }
  }
}
