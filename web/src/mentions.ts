// Outside mentions: news and public web pages that talk about a device type. Kept apart from the gated FDA facts:
// nothing here is checked against FDA records, and every mention says so. The live search runs on the API
// (POST /v1/live/mentions, contract in web/DATA_CONTRACT.md); this file validates what comes back and never trusts it
// further than the page can see: the quote must be a non-empty sentence without a person's details, the link must be
// https, the badge is always the fixed text, and "Official source" is shown only for a fda.gov address.
import { hasPersonalDetails } from './alerts'
import type { LiveLimits, LiveTraceStep } from './live/api'

export const MENTIONS_PATH = '/v1/live/mentions'
export const MENTION_BADGE = 'Unverified — not checked against FDA records'
export const MENTIONS_TITLE = 'News and public web (unverified)'
export const NO_STORED_SEARCH = 'No stored search yet'
export const MAX_MENTIONS = 10
export const MAX_TERMS = 5
export const MAX_TERM_CHARS = 60

export type SourceKind = 'official' | 'news' | 'web'

export interface Mention {
  source_name: string
  source_kind: SourceKind
  date: string | null
  url: string
  /** The exact sentence found on the fetched page. */
  quote: string
  /** One deterministic line: which terms matched. */
  why_matched: string
  badge: string
}
export interface SourceTried {
  name: string
  url: string
  status: string
  n: number
}
export interface Dropped {
  quote_not_found: number
  personal_details: number
  off_topic: number
}
export interface MentionsResult {
  product_code: string
  searched_utc: string
  sources_tried: SourceTried[]
  mentions: Mention[]
  dropped: Dropped
  trace: LiveTraceStep[]
  limits: LiveLimits | null
  mode: 'live' | 'recorded'
  recorded_note?: string
}
export interface MentionsFile {
  schema_version: string
  codes: Record<string, MentionsResult>
  notes: string[]
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const int = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? Math.floor(v) : 0)

/** True for fda.gov and its sub-domains over https. */
export function isOfficialUrl(u: string): boolean {
  try {
    const url = new URL(u)
    return url.protocol === 'https:' && (url.hostname === 'fda.gov' || url.hostname.endsWith('.fda.gov'))
  } catch {
    return false
  }
}

/** A three-letter product code in capitals, or null. */
export function cleanCode(code: string): string | null {
  const c = code.trim().toUpperCase()
  return /^[A-Z]{3}$/.test(c) ? c : null
}

/** The terms the API gets: trimmed, non-empty, at most 5 of at most 60 characters, no duplicates. */
export function cleanTerms(terms: string[] | undefined): string[] {
  const out: string[] = []
  for (const t of terms ?? []) {
    const s = String(t).replace(/\s+/g, ' ').trim().slice(0, MAX_TERM_CHARS)
    if (s && !out.some((x) => x.toLowerCase() === s.toLowerCase())) out.push(s)
    if (out.length >= MAX_TERMS) break
  }
  return out
}

/** The JSON body of POST /v1/live/mentions. Only the code and short device terms; no key, no question text. */
export function buildMentionsBody(code: string, terms?: string[]): Record<string, unknown> {
  const c = cleanCode(code)
  if (!c) throw new Error('A product code is three letters.')
  const t = cleanTerms(terms)
  return t.length ? { product_code: c, device_terms: t } : { product_code: c }
}

function parseMention(v: unknown): Mention | 'personal' | null {
  if (!isObj(v)) return null
  const url = typeof v.url === 'string' && /^https:\/\//.test(v.url) ? v.url : null
  const quote = typeof v.quote === 'string' ? v.quote.replace(/\s+/g, ' ').trim() : ''
  if (!url || !quote) return null
  if (hasPersonalDetails(quote)) return 'personal'
  // "Official source" only for a fda.gov address, whatever the server called it.
  const kind: SourceKind = isOfficialUrl(url) ? 'official' : v.source_kind === 'news' ? 'news' : 'web'
  return {
    source_name: typeof v.source_name === 'string' && v.source_name.trim() ? v.source_name.trim().slice(0, 120) : new URL(url).hostname,
    source_kind: kind,
    date: typeof v.date === 'string' && v.date.trim() ? v.date.trim().slice(0, 40) : null,
    url,
    quote,
    why_matched: typeof v.why_matched === 'string' ? v.why_matched.trim().slice(0, 300) : '',
    badge: MENTION_BADGE, // fixed; whatever the server wrote is not shown
  }
}

const traceOf = (v: unknown): LiveTraceStep[] =>
  Array.isArray(v)
    ? v.filter(isObj).map((s) => ({
        step: String(s.step ?? ''),
        model: typeof s.model === 'string' ? s.model : null,
        ms: typeof s.ms === 'number' && Number.isFinite(s.ms) ? s.ms : 0,
        status: s.status === 'skipped' || s.status === 'failed' ? s.status : 'ok',
        ...(typeof s.note === 'string' ? { note: s.note } : {}),
      }))
    : []

/** A mentions answer (live or stored); null when it lacks the mentions list. Mentions the page cannot vouch for are dropped and counted. */
export function parseMentions(body: unknown): MentionsResult | null {
  if (!isObj(body) || !Array.isArray(body.mentions)) return null
  const d = isObj(body.dropped) ? body.dropped : {}
  const dropped: Dropped = { quote_not_found: int(d.quote_not_found), personal_details: int(d.personal_details), off_topic: int(d.off_topic) }
  const mentions: Mention[] = []
  for (const m of body.mentions) {
    const p = parseMention(m)
    if (p === 'personal') dropped.personal_details += 1
    else if (p && mentions.length < MAX_MENTIONS) mentions.push(p)
  }
  const tried = (Array.isArray(body.sources_tried) ? body.sources_tried : []).filter(isObj).map((s) => ({
    name: String(s.name ?? ''),
    url: typeof s.url === 'string' && /^https:\/\//.test(s.url) ? s.url : '',
    status: String(s.status ?? ''),
    n: int(s.n),
  }))
  const lim = isObj(body.limits) && typeof body.limits.remaining_today === 'number' ? { remaining_today: body.limits.remaining_today, resets_utc: String(body.limits.resets_utc ?? '') } : null
  return {
    product_code: typeof body.product_code === 'string' ? body.product_code.toUpperCase() : '',
    searched_utc: typeof body.searched_utc === 'string' ? body.searched_utc : '',
    sources_tried: tried,
    mentions,
    dropped,
    trace: traceOf(body.trace),
    limits: lim,
    mode: body.mode === 'recorded' ? 'recorded' : 'live',
    ...(typeof body.recorded_note === 'string' && body.recorded_note.trim() ? { recorded_note: body.recorded_note.trim().slice(0, 400) } : {}),
  }
}

/** The stored search for a code (mentions.json), or null. */
export function storedMentions(file: MentionsFile | null | undefined, code: string): MentionsResult | null {
  const raw = file?.codes?.[code.toUpperCase()]
  if (!raw) return null
  const r = parseMentions(raw)
  return r ? { ...r, mode: 'recorded' } : null
}

/** "3 found, 2 dropped because the quote was not on the page, 1 dropped for personal details" */
export function droppedLine(found: number, d: Dropped): string {
  return `${found} found, ${d.quote_not_found} dropped because the quote was not on the page, ${d.personal_details} dropped for personal details`
}

export const KIND_LABEL: Record<SourceKind, string> = { official: 'Official source', news: 'News', web: 'Public web' }
