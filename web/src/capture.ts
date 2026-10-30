// Camera and mic: the browser sends one photo to POST {API}/v1/label or one recording to POST {API}/v1/voice.
// Nothing here ever invents a result. When the API base is not set, or the endpoint does not answer with a
// reading this file can parse, the outcome says why and the screen shows a recorded example, labelled as one.
// The server strips EXIF; nothing is changed in the file on the client because that cannot be verified here.
import { apiBaseFrom } from './liveCheck'
import type { LabelReading, Thread } from './types'

export type CaptureMode = 'label' | 'voice'

export const LABEL_PATH = '/v1/label'
export const VOICE_PATH = '/v1/voice'
export const CAPTURE_TIMEOUT_MS = 60_000
export const MAX_IMAGE_BYTES = 12 * 1024 * 1024
export const MAX_AUDIO_BYTES = 15 * 1024 * 1024
/** Longest recording the mic button makes before it stops by itself. */
export const MAX_RECORD_SECONDS = 60

/** Shown before any photo is chosen or sent. */
export const PHOTO_WARNING = "Don't photograph patients or patient data. Photos are not stored unless you choose to."
export const VOICE_WARNING = "Don't say patient names or patient data in a recording. Recordings are not stored unless you choose to."

export type CaptureFailure =
  | 'unconfigured'
  | 'not-found'
  | 'rate'
  | 'server'
  | 'network'
  | 'timeout'
  | 'bad-response'
  | 'too-large'
  | 'wrong-type'
  | 'empty'

/** Plain-words reason shown with the recorded example. */
export const FAILURE_TEXT: Record<CaptureFailure, string> = {
  unconfigured: 'The live API is not connected in this build, so nothing was sent.',
  'not-found': 'The live API answered 404: this reading is not available there yet.',
  rate: 'The live API answered 429: too many requests just now. Try again later.',
  server: 'The live API returned an error.',
  network: 'The live API could not be reached.',
  timeout: 'The live API did not answer in time.',
  'bad-response': 'The live API answered, but not with a reading this page can show.',
  'too-large': 'That file is too large to send.',
  'wrong-type': 'That file is not the right kind for this step.',
  empty: 'That file is empty.',
}

export interface PickedFile {
  blob: Blob
  name: string
}

/** Checks the file before anything is sent. Returns the failure, or null when it can be sent. */
export function checkFile(mode: CaptureMode, f: { size: number; type: string }): CaptureFailure | null {
  if (f.size === 0) return 'empty'
  const want = mode === 'label' ? 'image/' : 'audio/'
  // Some browsers record "video/webm" for audio-only; accept it for the mic.
  const okType = f.type.startsWith(want) || (mode === 'voice' && f.type.startsWith('video/webm'))
  if (!okType) return 'wrong-type'
  if (f.size > (mode === 'label' ? MAX_IMAGE_BYTES : MAX_AUDIO_BYTES)) return 'too-large'
  return null
}

/** A step that arrived from a streaming answer. */
export interface LiveStep {
  name: string
  summary: string
}

export type CaptureOutcome =
  | { ok: true; mode: 'label'; reading: LabelReading; steps: LiveStep[] }
  | { ok: true; mode: 'voice'; transcript: string; language: string | null; thread: Thread | null; steps: LiveStep[] }
  | { ok: false; reason: CaptureFailure; message: string }

const fail = (reason: CaptureFailure, extra?: string): CaptureOutcome => ({
  ok: false,
  reason,
  message: extra ? `${FAILURE_TEXT[reason]} ${extra}` : FAILURE_TEXT[reason],
})

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)

/** A label reading is accepted only if it has the fields the screen reads. */
export function parseLabel(body: unknown): LabelReading | null {
  const b = isObj(body) ? (isObj(body.label) ? body.label : isObj(body.reading) ? body.reading : body) : null
  if (!b) return null
  const sam = b.sam
  if (!isObj(b.fields) || !isObj(sam) || !Array.isArray(sam.boxes) || !Array.isArray(b.checks)) return null
  if (typeof b.k_status !== 'string' || typeof b.model !== 'string') return null
  return b as unknown as LabelReading
}

/** A voice answer needs the transcript; a full thread is optional and accepted only with sentences and tool steps. */
export function parseVoice(body: unknown): { transcript: string; language: string | null; thread: Thread | null } | null {
  if (!isObj(body)) return null
  const t = body.transcript_text ?? (isObj(body.voice) ? body.voice.transcript_text : undefined)
  if (typeof t !== 'string' || !t.trim()) return null
  const th = body.thread
  const thread =
    isObj(th) && Array.isArray(th.sentences) && Array.isArray(th.tool_steps) && typeof th.id === 'string'
      ? (th as unknown as Thread)
      : null
  const language = typeof body.language === 'string' ? body.language : null
  return { transcript: t.trim(), language, thread }
}

type Fetcher = (url: string, init?: RequestInit) => Promise<Response>

export interface SendOptions {
  apiBase: string | null
  fetcher: Fetcher
  /** Called for each step of a streamed answer (application/x-ndjson: {"type":"step","name","summary"} lines, then {"type":"result",...}). */
  onStep?: (s: LiveStep) => void
  timeoutMs?: number
}

const toStep = (o: Record<string, unknown>): LiveStep | null =>
  typeof o.name === 'string' ? { name: o.name, summary: typeof o.summary === 'string' ? o.summary : '' } : null

/** Reads a streamed answer line by line; returns the steps and the result object. */
async function readStream(res: Response, onStep?: (s: LiveStep) => void): Promise<{ steps: LiveStep[]; result: unknown }> {
  const steps: LiveStep[] = []
  let result: unknown = null
  const handle = (line: string) => {
    if (!line.trim()) return
    let o: unknown
    try {
      o = JSON.parse(line)
    } catch {
      return
    }
    if (!isObj(o)) return
    if (o.type === 'step') {
      const s = toStep(o)
      if (s) {
        steps.push(s)
        onStep?.(s)
      }
    } else if (o.type === 'result') result = o.result ?? o
  }
  if (!res.body) {
    ;(await res.text()).split('\n').forEach(handle)
    return { steps, result }
  }
  const reader = res.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    const lines = buf.split('\n')
    buf = lines.pop() ?? ''
    lines.forEach(handle)
  }
  handle(buf)
  return { steps, result }
}

/** Sends the file to the API. No fetch happens when the API base is not set or the file is not acceptable. */
export async function sendCapture(mode: CaptureMode, file: PickedFile, o: SendOptions): Promise<CaptureOutcome> {
  const bad = checkFile(mode, { size: file.blob.size, type: file.blob.type })
  if (bad) return fail(bad)
  if (!o.apiBase) return fail('unconfigured')
  const form = new FormData()
  form.append(mode === 'label' ? 'image' : 'audio', file.blob, file.name)
  const ctl = new AbortController()
  const timer = setTimeout(() => ctl.abort(), o.timeoutMs ?? CAPTURE_TIMEOUT_MS)
  try {
    const res = await o.fetcher(`${o.apiBase}${mode === 'label' ? LABEL_PATH : VOICE_PATH}`, {
      method: 'POST',
      body: form,
      signal: ctl.signal,
    })
    if (res.status === 404) return fail('not-found')
    if (res.status === 429) return fail('rate')
    if (!res.ok) return fail('server', `(HTTP ${res.status})`)
    let steps: LiveStep[] = []
    let body: unknown
    if ((res.headers.get('content-type') ?? '').includes('x-ndjson')) {
      const r = await readStream(res, o.onStep)
      steps = r.steps
      body = r.result
    } else {
      try {
        body = await res.json()
      } catch {
        return fail('bad-response')
      }
    }
    if (mode === 'label') {
      const reading = parseLabel(body)
      return reading ? { ok: true, mode, reading, steps } : fail('bad-response')
    }
    const v = parseVoice(body)
    return v ? { ok: true, mode, ...v, steps } : fail('bad-response')
  } catch (e) {
    return (e as { name?: string })?.name === 'AbortError' ? fail('timeout') : fail('network')
  } finally {
    clearTimeout(timer)
  }
}

export { apiBaseFrom }
