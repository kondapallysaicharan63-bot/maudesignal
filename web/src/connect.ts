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

const posInt = (v: unknown): number | null => (typeof v === 'number' && Number.isInteger(v) && v >= 0 && v < 1_000_000 ? v : null)
const originOf = (u: string): string | null => {
  try {
    return new URL(u).origin
  } catch {
    return null
  }
}

/**
 * The connect answer. The real API body is {mcp_url, openapi_url, docs_url, auth_header, demo_key, demo_limits:{per_minute, per_day,
 * live_model, note}, steps}; the older names (key_header, privacy_url, terms_url, limits:{read_only, live_spark, note}) still work as a
 * fallback. Each address falls back to the fixed one when missing or not https. Null when the body is not an object.
 */
export function parseConnect(body: unknown): ConnectInfo | null {
  if (!isObj(body)) return null
  const dl = isObj(body.demo_limits) ? body.demo_limits : null
  const lim = isObj(body.limits) ? body.limits : {}
  const readOnly = lim.read_only !== false
  const spark = dl ? dl.live_model === true : lim.live_spark === true
  const perMin = dl ? posInt(dl.per_minute) : null
  const perDay = dl ? posInt(dl.per_day) : null
  const rawNote = dl ? dl.note : lim.note
  let note: string
  if (dl) {
    const parts = [typeof rawNote === 'string' ? rawNote.trim().slice(0, 300) : '', spark ? 'Live Spark answers are on for this key.' : 'No live Spark answers.']
    if (perMin !== null || perDay !== null) {
      const lims = [perMin !== null ? `${perMin} calls a minute` : '', perDay !== null ? `${perDay} a day` : ''].filter(Boolean).join(', ')
      parts.push(`Rate limit: ${lims}.`)
    }
    note = parts.filter(Boolean).join(' ')
  } else if (typeof rawNote === 'string' && rawNote.trim()) {
    note = rawNote.trim().slice(0, 300)
  } else {
    note = `The demo key is ${readOnly ? 'read-only' : 'not read-only'}, ${spark ? 'can ask live Spark' : 'has no live Spark answers'} and is rate-limited.`
  }
  const mcp = https(body.mcp_url, FALLBACK.mcp_url)
  const root = originOf(mcp) ?? API_ROOT
  const header = [body.auth_header, body.key_header].find((h) => typeof h === 'string' && /^[A-Za-z0-9-]{1,40}$/.test(h)) as string | undefined
  return {
    mcp_url: mcp,
    openapi_url: https(body.openapi_url, `${root}/openapi.json`),
    privacy_url: https(body.privacy_url, `${root}/privacy`),
    terms_url: https(body.terms_url, `${root}/terms`),
    key_header: header ?? FALLBACK.key_header,
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

export const KEY_PLACEHOLDER = '<your key>'

export interface Snippet {
  id: 'claude-desktop' | 'cursor' | 'muse'
  title: string
  /** One line: which file or screen to paste it into. */
  where: string
  /** The text to copy. JSON for Claude Desktop and Cursor, plain lines for Muse. */
  text: string
  isJson: boolean
}

/** The three copy-paste snippets. The key is the demo key when the API gave one, else the placeholder. */
export function configSnippets(i: ConnectInfo): Snippet[] {
  const key = i.demo_key ?? KEY_PLACEHOLDER
  const header = i.key_header
  const desktop = { mcpServers: { maudesignal: { command: 'npx', args: ['mcp-remote', i.mcp_url, '--header', `${header}:${key}`] } } }
  const cursor = { mcpServers: { maudesignal: { url: i.mcp_url, headers: { [header]: key } } } }
  return [
    {
      id: 'claude-desktop',
      title: 'Claude Desktop',
      where: 'Paste into claude_desktop_config.json (Settings, Developer, Edit Config), or merge the maudesignal entry into your existing mcpServers, then restart Claude Desktop. Needs Node.js for npx.',
      text: JSON.stringify(desktop, null, 2),
      isJson: true,
    },
    {
      id: 'cursor',
      title: 'Cursor',
      where: 'Paste into .cursor/mcp.json in your project (or ~/.cursor/mcp.json for all projects), or merge the maudesignal entry into your existing mcpServers.',
      text: JSON.stringify(cursor, null, 2),
      isJson: true,
    },
    {
      id: 'muse',
      title: 'Meta Muse',
      where: 'In Muse, add a custom connector and enter these values.',
      text: `MCP URL: ${i.mcp_url}\nHeader: ${header}\nValue: ${key}`,
      isJson: false,
    },
  ]
}

/** Example questions to try once connected, one line each; each maps to an existing connector tool. */
export const EXAMPLE_QUESTIONS: { id: string; title: string; line: string }[] = [
  { id: 'what-changed', title: 'What changed this week for LLZ?', line: 'Uses what_changed_this_week: the latest stored week for a product code, labelled with its dates.' },
  { id: 'check-device-type', title: 'Check product code QAS on openFDA.', line: 'Uses check_device_type: live openFDA report counts for any product code.' },
  { id: 'recalls', title: 'Show recalls for LLZ.', line: 'Uses recalls: stored openFDA recalls for a product code, newest first.' },
]
