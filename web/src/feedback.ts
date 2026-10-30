// Private feedback and personal ref codes. Everything here is plain functions so it can be tested
// without a browser. Nothing about the visitor is sent except what the person types in the panel,
// the ref code from their link, the page name and a client timestamp.

export const REF_PATTERN = /^[A-Za-z0-9_-]{1,32}$/
const REF_KEY = 'ms-ref'
const VISITED_KEY = 'ms-visited'

export type Consent = 'quote_name_role' | 'quote_anonymous' | 'no_quote'

export const CONSENT_OPTIONS: { value: Consent; label: string }[] = [
  { value: 'quote_name_role', label: 'Quote me by name and role' },
  { value: 'quote_anonymous', label: 'Quote me anonymously' },
  { value: 'no_quote', label: "Don't quote me" },
]

/** Minimal session-storage surface (the real one, or a fake in tests). */
export interface KeyValueStore {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

export function sessionStore(): KeyValueStore | null {
  try {
    return typeof sessionStorage === 'undefined' ? null : sessionStorage
  } catch {
    return null
  }
}

/** A ref code from the ?r= parameter, or null when absent or not matching the allowed pattern. */
export function parseRef(search: string): string | null {
  let value: string | null = null
  try {
    value = new URLSearchParams(search).get('r')
  } catch {
    return null
  }
  return value !== null && REF_PATTERN.test(value) ? value : null
}

/** Reads ?r= and keeps it for the session; a later view without ?r= keeps the stored code. */
export function resolveRef(search: string, store: KeyValueStore | null): string | null {
  const fromUrl = parseRef(search)
  try {
    if (fromUrl) {
      store?.setItem(REF_KEY, fromUrl)
      return fromUrl
    }
    const kept = store?.getItem(REF_KEY) ?? null
    return kept !== null && REF_PATTERN.test(kept) ? kept : null
  } catch {
    return fromUrl
  }
}

export function apiBaseOrNull(raw: unknown): string | null {
  if (typeof raw !== 'string') return null
  const base = raw.trim().replace(/\/+$/, '')
  return /^https?:\/\//.test(base) ? base : null
}

// ---- visits -------------------------------------------------------------------------------

/** Cross-origin visit ping: fetch with keepalive and credentials 'omit' only. */
export interface VisitSender {
  fetcher?: (url: string, init: RequestInit) => Promise<unknown>
}

const sent = new Set<string>()

/** Forget which views were pinged (tests). */
export function resetVisits(): void {
  sent.clear()
}

/**
 * One ping per view per session: {ref?, page, client_ts}. Needs an API base; the ref code is
 * optional and is left out of the body when absent (the server labels codeless visits). Failures
 * are silent. Returns true when a ping was handed to the browser.
 */
export function sendVisit(
  apiBase: string | null,
  ref: string | null,
  page: string,
  store: KeyValueStore | null,
  sender: VisitSender,
  now: () => Date = () => new Date(),
): boolean {
  if (!apiBase) return false
  let seen: string[] = []
  try {
    const raw = JSON.parse(store?.getItem(VISITED_KEY) ?? '[]') as unknown
    if (Array.isArray(raw)) seen = raw.filter((x): x is string => typeof x === 'string')
  } catch {
    /* ignore */
  }
  if (sent.has(page) || seen.includes(page)) return false
  sent.add(page)
  try {
    store?.setItem(VISITED_KEY, JSON.stringify([...seen, page]))
  } catch {
    /* ignore */
  }
  const url = `${apiBase}/v1/visit`
  const body = JSON.stringify(
    ref ? { ref, page, client_ts: now().toISOString() } : { page, client_ts: now().toISOString() },
  )
  try {
    // Never navigator.sendBeacon: it always sends credentials, and the API (another origin) answers
    // the CORS preflight without Allow-Credentials, so the browser would drop the POST silently.
    void Promise.resolve(
      sender.fetcher?.(url, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body,
        keepalive: true,
        credentials: 'omit',
      }),
    ).catch(() => undefined)
  } catch {
    /* silent */
  }
  return true
}

// ---- feedback -----------------------------------------------------------------------------

export interface FeedbackForm {
  rating: number | null
  comment: string
  blocker: string
  one_thing: string
  name: string
  role: string
  consent: Consent
}

export const EMPTY_FORM: FeedbackForm = {
  rating: null,
  comment: '',
  blocker: '',
  one_thing: '',
  name: '',
  role: '',
  consent: 'no_quote',
}

export interface FeedbackPayload {
  rating: number
  comment: string
  blocker: string
  one_thing: string
  name: string
  role: string
  consent: Consent
  ref: string | null
  page: string
  client_ts: string
}

export function buildPayload(
  form: FeedbackForm,
  ref: string | null,
  page: string,
  now: () => Date = () => new Date(),
): FeedbackPayload | null {
  if (form.rating === null || form.rating < 1 || form.rating > 5) return null
  return {
    rating: form.rating,
    comment: form.comment.trim(),
    blocker: form.blocker.trim(),
    one_thing: form.one_thing.trim(),
    name: form.name.trim(),
    role: form.role.trim(),
    consent: form.consent,
    ref,
    page,
    client_ts: now().toISOString(),
  }
}

export type SubmitResult =
  | { ok: true }
  | {
      ok: false
      kind: 'invalid' | 'unavailable' | 'patient_data' | 'rate_limited' | 'network' | 'server'
      message: string
    }

export const MESSAGES = {
  invalid: 'Please choose a rating from 1 to 5.',
  unavailable: 'Feedback is not available on this copy of the site.',
  patient_data: 'The server found what looks like patient details. Please remove them and send again.',
  rate_limited: 'Too many submissions, try later',
  network: 'Could not send; please try again later',
  server: 'Could not send; please try again later',
} as const

/** The part of a fetch Response this module reads. */
export interface FetchLike {
  ok: boolean
  status: number
  json?: () => Promise<unknown>
}

/** The server's short 422 message when it sent one, else the fixed patient-data text. */
async function serverMessage(res: FetchLike): Promise<string> {
  try {
    const body = (await res.json?.()) as { detail?: unknown; message?: unknown } | null
    for (const v of [body?.detail, body?.message]) {
      if (typeof v === 'string' && v.trim() !== '' && v.length <= 200) return v.trim()
    }
  } catch {
    /* fall through */
  }
  return MESSAGES.patient_data
}

/** Sends the feedback. Only a 2xx answer is reported as sent. */
export async function submitFeedback(
  apiBase: string | null,
  form: FeedbackForm,
  ref: string | null,
  page: string,
  fetcher: (url: string, init: RequestInit) => Promise<FetchLike>,
  now: () => Date = () => new Date(),
): Promise<SubmitResult> {
  const payload = buildPayload(form, ref, page, now)
  if (!payload) return { ok: false, kind: 'invalid', message: MESSAGES.invalid }
  if (!apiBase) return { ok: false, kind: 'unavailable', message: MESSAGES.unavailable }
  try {
    const res = await fetcher(`${apiBase}/v1/feedback`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload),
      credentials: 'omit',
    })
    if (res.ok) return { ok: true }
    if (res.status === 422) {
      return { ok: false, kind: 'patient_data', message: await serverMessage(res) }
    }
    if (res.status === 429) return { ok: false, kind: 'rate_limited', message: MESSAGES.rate_limited }
    return { ok: false, kind: 'server', message: MESSAGES.server }
  } catch {
    return { ok: false, kind: 'network', message: MESSAGES.network }
  }
}

// ---- dialog keyboard ----------------------------------------------------------------------

export interface KeyLike {
  key: string
  shiftKey: boolean
  preventDefault(): void
}

/**
 * Tab and Shift+Tab wrap inside the dialog (Esc is the document listener's job). `focusables` are the dialog's focusable
 * elements in order and `active` the element that has focus now.
 */
export function dialogKey<T>(
  e: KeyLike,
  focusables: T[],
  active: T | null,
  focus: (el: T) => void,
): void {
  // Esc is handled by the dialog's document listener, so it is not handled twice here.
  if (e.key !== 'Tab' || focusables.length === 0) return
  const first = focusables[0]
  const last = focusables[focusables.length - 1]
  if (e.shiftKey && (active === first || active === null)) {
    e.preventDefault()
    focus(last)
  } else if (!e.shiftKey && active === last) {
    e.preventDefault()
    focus(first)
  }
}
