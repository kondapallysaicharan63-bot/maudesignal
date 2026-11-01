// The v2 layout's pages as addresses (history API): back, forward and refresh work, and a saved chat has its own
// address /chat/<id>. The query string (?layout=v2, ?r=CODE, ?composer=classic) is kept on every move.
import { useCallback, useEffect, useState } from 'react'
import type { CaptureMode } from '../capture'
import { V2_SEGMENTS } from '../layoutFlag'
import type { WorkflowId } from '../types'

export const SIGNALS_TABS = ['ranked', 'trend', 'unfiled', 'alerts'] as const
export const DEVICES_TABS = ['apply', 'yours'] as const
export const EVIDENCE_TABS = ['capa', 'review', 'approve', 'audit'] as const
export const CONNECT_TABS = ['muse', 'claude', 'api'] as const
/** The tabs of a simulated device's lifecycle profile (/devices/<id>, /devices/<id>/<tab>). */
export const PROFILE_TABS = ['overview', 'design', 'vv', 'regulatory', 'market', 'postmarket', 'people'] as const
export type SignalsTab = (typeof SIGNALS_TABS)[number]
export type DevicesTab = (typeof DEVICES_TABS)[number]
export type EvidenceTab = (typeof EVIDENCE_TABS)[number]
export type ConnectTab = (typeof CONNECT_TABS)[number]
export type ProfileTab = (typeof PROFILE_TABS)[number]

export type Route =
  | { page: 'home' }
  /** id null: a new, empty chat (it gets an id with its first question). */
  | { page: 'chat'; id: string | null }
  | { page: 'signals'; tab: SignalsTab }
  | { page: 'devices'; tab: DevicesTab; device?: string }
  /** A simulated device's lifecycle profile. */
  | { page: 'profile'; id: string; tab: ProfileTab }
  | { page: 'evidence'; tab: EvidenceTab }
  | { page: 'connect'; tab: ConnectTab }
  | { page: 'workflow'; id: WorkflowId; code?: string }
  | { page: 'thread'; id: string }
  | { page: 'run'; id: string }
  | { page: 'capture'; mode: CaptureMode }
  /** F26: current PMS workflow vs MaudeSignal. */
  | { page: 'pms' }
  /** F27: time and cost, measured not claimed. */
  | { page: 'roi' }

export type Section = 'signals' | 'devices' | 'evidence' | 'connect'

const WORKFLOW_IDS: WorkflowId[] = [
  'ai-sweep',
  'check-device',
  'weekly-signals',
  'ask-copilot',
  'capa-need-evidence',
  'weekly-investigator',
  'recall-sweep',
  'our-devices',
  'vision',
]
const CAPTURE_MODES: CaptureMode[] = ['label', 'voice']

const SEG_RE = new RegExp(`^(.*?/)(${V2_SEGMENTS.join('|')})(?:/|$)`)

/** The folder the app is served from ("/" on Vercel), read from the address so a v2 page address is not mistaken for it. */
export function appRoot(pathname: string): string {
  const m = SEG_RE.exec(pathname)
  if (m) return m[1]
  const i = pathname.lastIndexOf('/')
  return i >= 0 ? pathname.slice(0, i + 1) : '/'
}

const pick = <T extends string>(list: readonly T[], v: string | undefined, fallback: T): T =>
  list.includes(v as T) ? (v as T) : fallback

const dec = (s: string | undefined): string => {
  try {
    return decodeURIComponent(s ?? '')
  } catch {
    return s ?? ''
  }
}

/** The page an address shows. Anything unknown is Home. */
export function parseRoute(pathname: string): Route {
  const rest = pathname.slice(appRoot(pathname).length)
  const [seg, a, b] = rest.split('/').filter((x) => x !== '')
  switch (seg) {
    case 'chat':
      return { page: 'chat', id: a ? dec(a) : null }
    case 'signals':
      return { page: 'signals', tab: pick(SIGNALS_TABS, a, 'ranked') }
    case 'devices': {
      if (a && !DEVICES_TABS.includes(a as DevicesTab)) return { page: 'profile', id: dec(a), tab: pick(PROFILE_TABS, b, 'overview') }
      const tab = pick(DEVICES_TABS, a, 'apply')
      return tab === 'apply' && b ? { page: 'devices', tab, device: dec(b) } : { page: 'devices', tab }
    }
    case 'evidence':
      return { page: 'evidence', tab: pick(EVIDENCE_TABS, a, 'capa') }
    case 'connect':
      return { page: 'connect', tab: pick(CONNECT_TABS, a, 'muse') }
    case 'workflow':
      if (WORKFLOW_IDS.includes(a as WorkflowId))
        return b ? { page: 'workflow', id: a as WorkflowId, code: dec(b) } : { page: 'workflow', id: a as WorkflowId }
      return { page: 'home' }
    case 'thread':
      return a ? { page: 'thread', id: dec(a) } : { page: 'home' }
    case 'run':
      return a ? { page: 'run', id: dec(a) } : { page: 'home' }
    case 'capture':
      return { page: 'capture', mode: pick(CAPTURE_MODES, a, 'label') }
    case 'pms-workflow':
      return { page: 'pms' }
    case 'roi':
      return { page: 'roi' }
    default:
      return { page: 'home' }
  }
}

const enc = encodeURIComponent

/** The address of a page, relative to the app folder ("" for Home). */
export function formatRoute(r: Route): string {
  switch (r.page) {
    case 'home':
      return ''
    case 'chat':
      return r.id ? `chat/${enc(r.id)}` : 'chat'
    case 'signals':
      return `signals/${r.tab}`
    case 'devices':
      return r.device ? `devices/${r.tab}/${enc(r.device)}` : `devices/${r.tab}`
    case 'profile':
      return r.tab === 'overview' ? `devices/${enc(r.id)}` : `devices/${enc(r.id)}/${r.tab}`
    case 'evidence':
      return `evidence/${r.tab}`
    case 'connect':
      return `connect/${r.tab}`
    case 'workflow':
      return r.code ? `workflow/${r.id}/${enc(r.code)}` : `workflow/${r.id}`
    case 'thread':
      return `thread/${enc(r.id)}`
    case 'run':
      return `run/${enc(r.id)}`
    case 'capture':
      return `capture/${r.mode}`
    case 'pms':
      return 'pms-workflow'
    case 'roi':
      return 'roi'
  }
}

/** The full address of a page, keeping the folder and the query string. */
export function hrefFor(
  r: Route,
  loc: { pathname: string; search: string } = window.location,
  flag: string | undefined = import.meta.env.VITE_LAYOUT_DEFAULT as string | undefined,
): string {
  return `${appRoot(loc.pathname)}${formatRoute(r)}${withLayout(loc.search, flag)}`
}

/**
 * The query string with layout=v2 added when the build default is not v2 and the address does not say, so Home, a
 * refresh or a new tab stays in v2 after it was opened from a v2-only path. Other parameters are kept as they are.
 */
export function withLayout(search: string, flag: string | undefined): string {
  if ((flag ?? '').trim().toLowerCase() === 'v2') return search
  try {
    const q = new URLSearchParams(search)
    if (q.has('layout')) return search
    q.append('layout', 'v2')
    return `?${q.toString()}`
  } catch {
    return search
  }
}

/** A short name for the page (feedback and visit pings), e.g. "signals:trend" or "chat". Never carries a chat id. */
export function routeName(r: Route): string {
  switch (r.page) {
    case 'home':
      return 'home'
    case 'chat':
      return 'chat'
    case 'signals':
    case 'evidence':
    case 'connect':
      return `${r.page}:${r.tab}`
    case 'devices':
      return r.device ? `devices:${r.tab}:${r.device}` : `devices:${r.tab}`
    case 'profile':
      return `devices:profile:${r.tab}`
    case 'workflow':
      return `workflow:${r.id}`
    case 'thread':
    case 'run':
      return `${r.page}:${r.id}`
    case 'capture':
      return `capture:${r.mode}`
    case 'pms':
      return 'pms-workflow'
    case 'roi':
      return 'roi'
  }
}

export const sameRoute = (a: Route, b: Route): boolean => formatRoute(a) === formatRoute(b)

/** The current page and a way to move: push (a new history entry) or replace. */
export function useRoute(): { route: Route; navigate: (r: Route, o?: { replace?: boolean }) => void } {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.pathname))
  useEffect(() => {
    const onPop = () => setRoute(parseRoute(window.location.pathname))
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  const navigate = useCallback((r: Route, o?: { replace?: boolean }) => {
    const href = hrefFor(r)
    const cur = `${window.location.pathname}${window.location.search}`
    try {
      if (o?.replace) window.history.replaceState({ ms: 'v2' }, '', href)
      else if (href !== cur) window.history.pushState({ ms: 'v2' }, '', href)
    } catch {
      // a sandboxed frame can refuse history changes; the page still changes
    }
    setRoute(r)
  }, [])
  return { route, navigate }
}
