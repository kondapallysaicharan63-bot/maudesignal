// Noctua, MaudeSignal's watchful owl. SVG + CSS only (mascot.css); colours come from design tokens.
// Branding only: never import this into the dossier, artifacts, PdfView, audit export or connector API.
// Mascot state changes are not audit events. In-UI instances are aria-hidden; the paired text or badge carries the meaning.
import { useEffect, useState } from 'react'
import { MASCOT_SIZES, WINGS_MAX_DROP_PX, type MascotState } from './mascotStates'

export const NOCTUA_TITLE = "Noctua, MaudeSignal's watchful owl mark"

/** The bubble opens by itself once per browser session (sessionStorage; if blocked, once per page load). */
export const MASCOT_BUBBLE_KEY = 'ms-noctua-bubble-seen-v1'
export const MASCOT_BUBBLE_MS = 4000
let shownThisLoad = false
export function mascotBubbleFirst(): boolean {
  if (shownThisLoad) return false
  try {
    if (sessionStorage.getItem(MASCOT_BUBBLE_KEY)) return false
    sessionStorage.setItem(MASCOT_BUBBLE_KEY, '1')
  } catch {
    /* blocked: the per-load flag still limits it to one */
  }
  shownThisLoad = true
  return true
}
/** For tests: forget that the bubble was shown. */
export function resetMascotBubble(): void {
  shownThisLoad = false
  try {
    sessionStorage.removeItem(MASCOT_BUBBLE_KEY)
  } catch {
    /* ignore */
  }
}

/** 'auto' once per session while `active`; 'user' on hover or focus (set by the caller). Cleared after MASCOT_BUBBLE_MS. */
export function useMascotBubble(active: boolean): [false | 'auto' | 'user', (v: false | 'user') => void] {
  const [bubble, setBubble] = useState<false | 'auto' | 'user'>(false)
  useEffect(() => {
    if (active && mascotBubbleFirst()) setBubble('auto')
  }, [active])
  useEffect(() => {
    if (!bubble) return
    const t = window.setTimeout(() => setBubble(false), MASCOT_BUBBLE_MS)
    return () => window.clearTimeout(t)
  }, [bubble])
  return [bubble, setBubble]
}

export interface MascotOwlProps {
  state?: MascotState
  /** Rendered size in px: 24 inline, 32 headers, 48 empty states, 96 Home hero at most. */
  size?: number
  /** The logo mark: gets a <title> and role="img". Every other instance is aria-hidden. */
  logo?: boolean
  /** Proof screenshots and evidence views: render nothing. */
  hideMascot?: boolean
  className?: string
}

export function MascotOwl({ state = 'idle', size = MASCOT_SIZES.header, logo = false, hideMascot = false, className }: MascotOwlProps) {
  if (hideMascot) return null
  const cls = ['ms-noctua', size <= WINGS_MAX_DROP_PX ? 'ms-noctua--tiny' : '', className ?? ''].filter(Boolean).join(' ')
  return (
    <svg
      viewBox="0 0 64 64"
      width={size}
      height={size}
      className={cls}
      data-testid="noctua"
      data-mascot="noctua"
      data-state={state}
      focusable="false"
      {...(logo ? { role: 'img' } : { 'aria-hidden': true })}
    >
      {logo && <title>{NOCTUA_TITLE}</title>}
      <g className="ms-noctua-all">
        <path className="ms-noctua-body" d="M11 17 12 6l11 4h18l11-4 1 11v23q0 12-21 14Q11 52 11 40Z" />
        <g className="ms-noctua-wings">
          <path className="ms-noctua-wing ms-noctua-wing--l" d="M6 38q-1 9 4 15 3-2 3-7V38Z" />
          <path className="ms-noctua-wing ms-noctua-wing--r" d="M58 38q1 9-4 15-3-2-3-7V38Z" />
        </g>
        <circle className="ms-noctua-eye" cx="23" cy="29" r="9" />
        <circle className="ms-noctua-eye" cx="41" cy="29" r="9" />
        <g className="ms-noctua-pupils">
          <circle className="ms-noctua-pupil" cx="23" cy="29" r="4" />
          <circle className="ms-noctua-pupil" cx="41" cy="29" r="4" />
        </g>
        <rect className="ms-noctua-lid" x="13" y="20" width="20" height="18" />
        <rect className="ms-noctua-lid" x="31" y="20" width="20" height="18" />
        <path className="ms-noctua-beak" d="M29 40h6l-3 6Z" />
      </g>
      <circle className="ms-noctua-ring" cx="32" cy="33" r="30" />
      <g className="ms-noctua-dots">
        <circle cx="26" cy="3" r="2" />
        <circle cx="32" cy="3" r="2" />
        <circle cx="38" cy="3" r="2" />
      </g>
    </svg>
  )
}

export default MascotOwl

/** "Hide Noctua" lasts for the session (sessionStorage; if blocked, until the page reloads). "Show Noctua" is in the Theme menu. */
export const NOCTUA_HIDDEN_KEY = 'ms-noctua-hidden-v1'
const HIDDEN_EVENT = 'ms-noctua-visibility'
let hiddenThisLoad = false
export function noctuaHidden(): boolean {
  try {
    return sessionStorage.getItem(NOCTUA_HIDDEN_KEY) === '1' || hiddenThisLoad
  } catch {
    return hiddenThisLoad
  }
}
export function setNoctuaHidden(v: boolean): void {
  hiddenThisLoad = v
  try {
    if (v) sessionStorage.setItem(NOCTUA_HIDDEN_KEY, '1')
    else sessionStorage.removeItem(NOCTUA_HIDDEN_KEY)
  } catch {
    /* blocked: the per-load flag still applies */
  }
  window.dispatchEvent(new Event(HIDDEN_EVENT))
}
export function useNoctuaHidden(): boolean {
  const [h, setH] = useState(noctuaHidden)
  useEffect(() => {
    const on = () => setH(noctuaHidden())
    window.addEventListener(HIDDEN_EVENT, on)
    return () => window.removeEventListener(HIDDEN_EVENT, on)
  }, [])
  return h
}
