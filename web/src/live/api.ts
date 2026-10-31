// The live API: POST /v1/live/ask, /v1/live/voice and /v1/live/label (contract in web/DATA_CONTRACT.md, "Live API").
// Everything here is plain functions: payload builders, history trimming, response parsing and error mapping, so the
// network layer can be tested with a fake fetch. Nothing is invented: a field the server did not send is absent here.
import { apiBaseFrom } from '../liveCheck'
import { buildMentionsBody, MENTIONS_PATH, parseMentions, type MentionsResult } from '../mentions'

export { apiBaseFrom }

export const ASK_PATH = '/v1/live/ask'
export const VOICE_PATH = '/v1/live/voice'
export const LABEL_PATH = '/v1/live/label'

export const MIN_QUESTION = 3
export const MAX_QUESTION = 500
export const MAX_HISTORY = 4
export const MAX_HISTORY_ANSWER = 600
/** The server takes at most 4 MB of image (Vercel rejects larger bodies before the app runs, with no CORS headers). */
export const MAX_IMAGE_BYTES = 4 * 1024 * 1024
/** A chosen file may be larger than that (phone photos are); it is shrunk in the browser before upload. */
export const MAX_SOURCE_BYTES = 30 * 1024 * 1024
/** A live answer may take a while (a model call plus the gate); the label path stays under 55 s on the server. */
export const ASK_TIMEOUT_MS = 70_000
/** The label path (SAM, Spark, openFDA, gate) is held to under 55 s on the server; the page gives up a little after that. */
export const LABEL_TIMEOUT_MS = 60_000

export const NOT_MEDICAL_ADVICE = 'Not medical advice. Signals for a person to review; nothing is filed with FDA.'
export const VOICE_NOTE = 'Audio is sent once for transcription and not stored. Do not say patient details.'
export const PHOTO_NOTE = 'Photo is read once and not stored. Do not photograph patient details.'
export const LIMIT_TEXT = 'Daily live limit reached - showing recorded runs'

export type TraceStatus = 'ok' | 'skipped' | 'failed'
export interface LiveTraceStep {
  step: string
  model?: string | null
  ms: number
  status: TraceStatus
  note?: string
}
export interface LiveLimits {
  remaining_today: number
  resets_utc: string
}
export interface Link {
  label: string
  url: string
}
export interface Speakable {
  text: string
  links: Link[]
}
export interface Withheld {
  reason: string
}
export interface LiveAnswer {
  speakable: Speakable[]
  withheld: Withheld[]
  spoken_text: string
}
interface Common {
  mode: 'live' | 'recorded'
  recorded_note?: string
  not_medical_advice: boolean
  trace: LiveTraceStep[]
  cost_usd: number | null
  limits: LiveLimits | null
}
export interface AskResponse extends Common {
  heard?: string
  answer: LiveAnswer
}
export interface LiveField {
  value?: string | null
  legibility?: string
}
export interface LiveReading {
  legibility: string
  fields: Record<string, LiveField | string | null>
  values_withheld?: string[] | boolean | null
}
export interface Candidate {
  k_number: string
  device_name: string
  applicant: string
  product_code: string
  why_matched: string[]
  why_not_matched: string[]
  links: Link[]
}
export interface LiveMatchesBlock {
  status: 'needs_person_to_confirm' | 'no_match_found'
  candidates: Candidate[]
  /** True when openFDA could not be searched: an empty list then means "not searched", not "nothing matched". */
  search_failed?: boolean
  note?: string
}
export interface LabelResponse extends Common {
  reading: LiveReading
  matches: LiveMatchesBlock
  confirmed: null
}

export interface Turn {
  question: string
  answer: string
}

/** The last MAX_HISTORY turns, each answer cut to MAX_HISTORY_ANSWER characters; blank turns are dropped. */
export function trimHistory(turns: Turn[]): Turn[] {
  return turns
    .filter((t) => t.question.trim() && t.answer.trim())
    .slice(-MAX_HISTORY)
    .map((t) => ({ question: t.question.trim().slice(0, MAX_QUESTION), answer: t.answer.trim().slice(0, MAX_HISTORY_ANSWER) }))
}

/** The plain text of an answer (the sentences that passed), used as the "answer" of a history turn. */
export const answerText = (a: LiveAnswer): string => a.speakable.map((s) => s.text).join(' ')

export type FailKind = 'invalid_input' | 'patient_data' | 'rate_limited' | 'too_large' | 'server' | 'network' | 'timeout' | 'bad_response' | 'not_configured'

export class LiveError extends Error {
  constructor(
    public kind: FailKind,
    message: string,
    public retryAfterS?: number,
  ) {
    super(message)
    this.name = 'LiveError'
  }
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)

/** Checks a question the way the server does (3..500 characters after trimming). Returns the trimmed text, or throws. */
export function checkQuestion(q: string): string {
  const t = q.trim()
  if (t.length < MIN_QUESTION) throw new LiveError('invalid_input', `Type at least ${MIN_QUESTION} characters.`)
  if (t.length > MAX_QUESTION) throw new LiveError('invalid_input', `Questions are limited to ${MAX_QUESTION} characters (this one has ${t.length}).`)
  return t
}

export interface AskOptions {
  history?: Turn[]
  productCode?: string | null
  ref?: string | null
}

/** The JSON body of POST /v1/live/ask. Optional keys are left out when empty. */
export function buildAskBody(question: string, o: AskOptions = {}): Record<string, unknown> {
  const body: Record<string, unknown> = { question: checkQuestion(question) }
  const history = trimHistory(o.history ?? [])
  if (history.length) body.history = history
  if (o.productCode) body.product_code = o.productCode
  if (o.ref) body.ref = o.ref
  return body
}

/** The multipart body of POST /v1/live/voice: part "audio" (the WAV) and, when there is something to say, part "meta" (JSON). */
export function buildVoiceForm(wav: Blob, o: Pick<AskOptions, 'history' | 'productCode'> = {}): FormData {
  const form = new FormData()
  form.append('audio', wav, 'question.wav')
  const meta: Record<string, unknown> = {}
  const history = trimHistory(o.history ?? [])
  if (history.length) meta.history = history
  if (o.productCode) meta.product_code = o.productCode
  if (Object.keys(meta).length) form.append('meta', new Blob([JSON.stringify(meta)], { type: 'application/json' }), 'meta.json')
  return form
}

/** The multipart body of POST /v1/live/label: part "image" (a JPEG or PNG). */
export function buildLabelForm(image: Blob): FormData {
  const form = new FormData()
  form.append('image', image, image.type === 'image/png' ? 'label.png' : 'label.jpg')
  return form
}

/** Maps an HTTP error answer to the message the person sees. Never shows a body the server did not mean for people. */
export function mapError(status: number, body: unknown): LiveError {
  const b = isObj(body) ? body : {}
  const message = typeof b.message === 'string' && b.message.trim() ? b.message.trim().slice(0, 400) : ''
  if (status === 429) {
    const r = typeof b.retry_after_s === 'number' && Number.isFinite(b.retry_after_s) ? b.retry_after_s : undefined
    return new LiveError('rate_limited', message || LIMIT_TEXT, r)
  }
  if (status === 413) return new LiveError('too_large', message || 'That is too large to send.')
  if (status === 422) {
    if (b.code === 'patient_data') return new LiveError('patient_data', message || 'This looks like it contains patient details, so it was not sent on. Remove them and try again.')
    return new LiveError('invalid_input', message || 'The live service could not use that input.')
  }
  return new LiveError('server', `The live service returned an error (HTTP ${status}).`)
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

const common = (b: Record<string, unknown>): Common => ({
  mode: b.mode === 'recorded' ? 'recorded' : 'live',
  ...(typeof b.recorded_note === 'string' ? { recorded_note: b.recorded_note } : {}),
  not_medical_advice: true,
  trace: traceOf(b.trace),
  cost_usd: typeof b.cost_usd === 'number' ? b.cost_usd : null,
  limits:
    isObj(b.limits) && typeof b.limits.remaining_today === 'number'
      ? { remaining_today: b.limits.remaining_today, resets_utc: String(b.limits.resets_utc ?? '') }
      : null,
})

const linksOf = (v: unknown): Link[] =>
  Array.isArray(v)
    ? v
        .filter(isObj)
        .filter((l) => typeof l.url === 'string' && /^https?:\/\//.test(l.url))
        .map((l) => ({ label: String(l.label ?? 'Source'), url: String(l.url) }))
    : []

/** An ask or voice answer; null when it lacks the answer block. */
export function parseAsk(body: unknown): AskResponse | null {
  if (!isObj(body) || !isObj(body.answer)) return null
  const a = body.answer
  if (!Array.isArray(a.speakable)) return null
  const speakable = a.speakable.filter(isObj).map((s) => ({ text: String(s.text ?? ''), links: linksOf(s.links) })).filter((s) => s.text)
  const withheld = (Array.isArray(a.withheld) ? a.withheld.filter(isObj) : []).map((w) => ({ reason: String(w.reason ?? 'held back by the claim gate') }))
  const out: AskResponse = {
    ...common(body),
    answer: { speakable, withheld, spoken_text: typeof a.spoken_text === 'string' ? a.spoken_text : speakable.map((s) => s.text).join(' ') },
  }
  if (typeof body.heard === 'string' && body.heard.trim()) out.heard = body.heard.trim()
  return out
}

/** A label answer; null when it lacks the reading or the matches block. */
export function parseLabelResponse(body: unknown): LabelResponse | null {
  if (!isObj(body) || !isObj(body.reading) || !isObj(body.matches)) return null
  const r = body.reading
  const m = body.matches
  if (!isObj(r.fields) || !Array.isArray(m.candidates)) return null
  const candidates: Candidate[] = m.candidates
    .filter(isObj)
    .slice(0, 3)
    .map((c) => ({
      k_number: String(c.k_number ?? ''),
      device_name: String(c.device_name ?? ''),
      applicant: String(c.applicant ?? ''),
      product_code: String(c.product_code ?? ''),
      why_matched: Array.isArray(c.why_matched) ? c.why_matched.map(String) : [],
      why_not_matched: Array.isArray(c.why_not_matched) ? c.why_not_matched.map(String) : [],
      links: linksOf(c.links),
    }))
  return {
    ...common(body),
    reading: {
      legibility: typeof r.legibility === 'string' && r.legibility.trim() ? r.legibility.trim() : 'unknown',
      fields: r.fields as LiveReading['fields'],
      ...(r.values_withheld != null ? { values_withheld: r.values_withheld as LiveReading['values_withheld'] } : {}),
    },
    matches: {
      status: m.status === 'no_match_found' || candidates.length === 0 ? 'no_match_found' : 'needs_person_to_confirm',
      candidates,
      ...(m.search_failed === true ? { search_failed: true } : {}),
      ...(typeof m.note === 'string' && m.note.trim() ? { note: m.note.trim().slice(0, 400) } : {}),
    },
    confirmed: null,
  }
}

type Fetcher = (url: string, init?: RequestInit) => Promise<Response>

export interface Deps {
  apiBase: string | null
  fetcher: Fetcher
  timeoutMs?: number
}

async function post<T>(path: string, init: { body: BodyInit; json?: boolean }, parse: (b: unknown) => T | null, d: Deps): Promise<T> {
  if (!d.apiBase) throw new LiveError('not_configured', 'The live service is not connected in this build.')
  const ctl = new AbortController()
  const timer = setTimeout(() => ctl.abort(), d.timeoutMs ?? ASK_TIMEOUT_MS)
  try {
    const res = await d.fetcher(`${d.apiBase}${path}`, {
      method: 'POST',
      body: init.body,
      ...(init.json ? { headers: { 'content-type': 'application/json' } } : {}),
      credentials: 'omit',
      signal: ctl.signal,
    })
    let body: unknown = null
    try {
      body = await res.json()
    } catch {
      body = null
    }
    if (!res.ok) throw mapError(res.status, body)
    const parsed = parse(body)
    if (!parsed) throw new LiveError('bad_response', 'The live service answered, but not with an answer this page can show.')
    return parsed
  } catch (e) {
    if (e instanceof LiveError) throw e
    if ((e as { name?: string })?.name === 'AbortError') throw new LiveError('timeout', 'The live service did not answer in time.')
    throw new LiveError('network', 'The live service could not be reached.')
  } finally {
    clearTimeout(timer)
  }
}

export const postAsk = async (question: string, o: AskOptions, d: Deps): Promise<AskResponse> =>
  post(ASK_PATH, { body: JSON.stringify(buildAskBody(question, o)), json: true }, parseAsk, d)

export const postVoice = async (wav: Blob, o: Pick<AskOptions, 'history' | 'productCode'>, d: Deps): Promise<AskResponse> =>
  post(VOICE_PATH, { body: buildVoiceForm(wav, o) }, parseAsk, d)

/** POST /v1/live/mentions: a three-letter code and short device terms; no key, no question text, no photo. */
export const postMentions = async (code: string, terms: string[] | undefined, d: Deps): Promise<MentionsResult> => {
  let body: Record<string, unknown>
  try {
    body = buildMentionsBody(code, terms)
  } catch (e) {
    throw new LiveError('invalid_input', (e as Error).message)
  }
  return post(MENTIONS_PATH, { body: JSON.stringify(body), json: true }, parseMentions, d)
}

export function postLabel(image: Blob, d: Deps): Promise<LabelResponse> {
  if (image.size === 0) return Promise.reject(new LiveError('invalid_input', 'That image is empty.'))
  if (image.size > MAX_IMAGE_BYTES) return Promise.reject(new LiveError('too_large', 'That image is larger than 4 MB.'))
  return post(LABEL_PATH, { body: buildLabelForm(image) }, parseLabelResponse, { ...d, timeoutMs: d.timeoutMs ?? LABEL_TIMEOUT_MS })
}

/** "2 sentences held back: reason one; reason two", or null when nothing was held back. Only the reasons are shown, never the held text. */
export function heldBackLine(w: Withheld[]): string | null {
  if (w.length === 0) return null
  const reasons = [...new Set(w.map((x) => x.reason.trim()).filter(Boolean))]
  return `${w.length} ${w.length === 1 ? 'sentence' : 'sentences'} held back: ${reasons.join('; ') || 'held back by the claim gate'}`
}

/** "1.2 s" or "340 ms" */
export const fmtStepMs = (ms: number): string => (ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`)
