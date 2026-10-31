// "Connect to Muse": what a reviewer needs to add MaudeSignal as a custom connector in Muse. GET /v1/connect on the API
// gives the live values; without it the page shows fixed text with the same addresses. No OAuth (not available): the
// key goes in the X-API-Key header.

export const CONNECT_PATH = '/v1/connect'
export const API_ROOT = 'https://maudesignal-api.vercel.app'
export const FALLBACK = {
  mcp_url: `${API_ROOT}/mcp`,
  openapi_url: `${API_ROOT}/openapi.json`,
  privacy_url: `${API_ROOT}/privacy`,
  terms_url: `${API_ROOT}/terms`,
  key_header: 'X-API-Key',
} as const
export const ASK_FOR_KEY = 'Ask Charan for a key.'
export const DEFAULT_LIMITS_TEXT = 'The demo key is read-only, has no live Spark answers and is rate-limited.'

export interface ConnectInfo {
  mcp_url: string
  openapi_url: string
  privacy_url: string
  terms_url: string
  key_header: string
  /** The demo key when the API hands one out; null otherwise (then: ask Charan). */
  demo_key: string | null
  limits: { read_only: boolean; live_spark: boolean; note: string }
  /** True when these values came from the API, false for the fixed fallback. */
  fromApi: boolean
}

export const FALLBACK_INFO: ConnectInfo = {
  ...FALLBACK,
  demo_key: null,
  limits: { read_only: true, live_spark: false, note: DEFAULT_LIMITS_TEXT },
  fromApi: false,
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const https = (v: unknown, fallback: string): string => (typeof v === 'string' && /^https:\/\//.test(v) ? v : fallback)

/** The connect answer; each address falls back to the fixed one when missing or not https. Null when the body is not an object. */
export function parseConnect(body: unknown): ConnectInfo | null {
  if (!isObj(body)) return null
  const lim = isObj(body.limits) ? body.limits : {}
  const readOnly = lim.read_only !== false
  const spark = lim.live_spark === true
  const note =
    typeof lim.note === 'string' && lim.note.trim()
      ? lim.note.trim().slice(0, 300)
      : `The demo key is ${readOnly ? 'read-only' : 'not read-only'}, ${spark ? 'can ask live Spark' : 'has no live Spark answers'} and is rate-limited.`
  return {
    mcp_url: https(body.mcp_url, FALLBACK.mcp_url),
    openapi_url: https(body.openapi_url, FALLBACK.openapi_url),
    privacy_url: https(body.privacy_url, FALLBACK.privacy_url),
    terms_url: https(body.terms_url, FALLBACK.terms_url),
    key_header: typeof body.key_header === 'string' && /^[A-Za-z0-9-]{1,40}$/.test(body.key_header) ? body.key_header : FALLBACK.key_header,
    demo_key: typeof body.demo_key === 'string' && body.demo_key.trim() ? body.demo_key.trim() : null,
    limits: { read_only: readOnly, live_spark: spark, note },
    fromApi: true,
  }
}

type Fetcher = (url: string, init?: RequestInit) => Promise<Response>

/** GET /v1/connect. Any failure (no address, network, error status, odd body) gives the fixed fallback, so the page always has the addresses. */
export async function fetchConnect(apiBase: string | null, fetcher: Fetcher = (u, i) => fetch(u, i)): Promise<ConnectInfo> {
  if (!apiBase) return FALLBACK_INFO
  const ctl = new AbortController()
  const timer = setTimeout(() => ctl.abort(), 10_000)
  try {
    const res = await fetcher(`${apiBase}${CONNECT_PATH}`, { method: 'GET', credentials: 'omit', signal: ctl.signal })
    if (!res.ok) return FALLBACK_INFO
    let body: unknown = null
    try {
      body = await res.json()
    } catch {
      body = null
    }
    return parseConnect(body) ?? FALLBACK_INFO
  } catch {
    return FALLBACK_INFO
  } finally {
    clearTimeout(timer)
  }
}

/** The three steps, with the addresses filled in. */
export function connectSteps(i: ConnectInfo): { n: number; text: string }[] {
  return [
    { n: 1, text: 'Open Muse and go to its connectors (custom connectors).' },
    { n: 2, text: `Add a connector and paste the MCP address ${i.mcp_url}` },
    { n: 3, text: `Paste the key into the ${i.key_header} header field. There is no sign-in with an account (OAuth is not available).` },
  ]
}
