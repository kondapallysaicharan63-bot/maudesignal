// PRD-34 companion movement: Noctua docks bottom-right of the web app (inside the browser only). Silent: no speech, no
// chat, no network, no cursor following, no roaming. With `onOpen` it is one safe control: a click opens the PMS board,
// and a fixed caption shows the number of board rows to review (nothing else is ever written). Hover or focus: the owl
// looks around. Without `onOpen` it is decorative (only the 44px "Hide Noctua" button).
// - Hero walk: on Home, once per session, it walks a short way into its dock spot, then idles.
// - Idle glide: a slow 12 px drift inside its dock area every ~25 s (CSS only).
// - Paused (frozen in place) on reduced motion, while a modal / alert panel / menu is open, while a person types, and on
//   the decision pages (Signals, Investigate, Evidence, Board, Validation).
// - Ducks away (hidden) whenever something it would cover is under it: a button, link, input, table, figure or text.
// - Hidden everywhere when "Hide Noctua" is on; and on Home when Home's own calm owl is shown (never two owls there).
import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { MascotOwl, setNoctuaHidden, useNoctuaHidden } from '../components/mascot/MascotOwl'

export const DOCK_SIZE = 64
export const DOCK_SIZE_PHONE = 48
export const GLIDE_PX = 12
export const WALK_PX = 96
export const MIN_WALK_PX = 24
export const WALK_KEY = 'ms-noctua-walk-seen-v1'
export const OVERLAY_SELECTOR = '[data-popover-open], [role=dialog][aria-modal=true], dialog[open], [role=menu]'
export const FROZEN_PAGES = ['signals', 'investigate', 'evidence', 'board', 'validation'] as const

let walkedThisLoad = false
/** True the first time per browser session (sessionStorage; if blocked, once per page load). */
export function firstWalk(): boolean {
  if (walkedThisLoad) return false
  walkedThisLoad = true
  try {
    if (sessionStorage.getItem(WALK_KEY)) return false
    sessionStorage.setItem(WALK_KEY, '1')
  } catch {
    /* blocked: the per-load flag still limits it to one */
  }
  return true
}
/** For tests. */
export function resetWalk(): void {
  walkedThisLoad = false
  try {
    sessionStorage.removeItem(WALK_KEY)
  } catch {
    /* ignore */
  }
}

const COVERED = new Set(['BUTTON', 'A', 'INPUT', 'TEXTAREA', 'SELECT', 'LABEL', 'SUMMARY', 'TABLE', 'THEAD', 'TBODY', 'TR', 'TD', 'TH', 'IMG', 'SVG', 'CANVAS', 'VIDEO', 'FIGURE', 'PRE', 'CODE', 'LI'])

/** True when an element would be covered by the dock: anything interactive, a figure, or an element with its own text. */
export function wouldCover(el: Element): boolean {
  if (COVERED.has(el.tagName.toUpperCase())) return true
  if (el.closest('button, a, input, textarea, select, label, table, figure, [role=button], [role=tab], [role=dialog]')) return true
  for (const n of Array.from(el.childNodes)) if (n.nodeType === 3 && (n.textContent ?? '').trim()) return true
  return false
}

/** True when any point of the rect has something under it (outside `self`) that the dock would cover. */
export function rectCollides(r: { left: number; top: number; right: number; bottom: number }, self: Element | null, doc: Document = document): boolean {
  if (typeof doc.elementsFromPoint !== 'function') return false
  const xs = [r.left + 2, (r.left + r.right) / 2, r.right - 2]
  const ys = [r.top + 2, (r.top + r.bottom) / 2, r.bottom - 2]
  for (const x of xs)
    for (const y of ys)
      for (const el of doc.elementsFromPoint(x, y)) {
        if (self && self.contains(el)) continue
        if (el === doc.documentElement || el === doc.body) continue
        if (wouldCover(el)) return true
      }
  return false
}

/** The longest clear walk (12 px steps, up to WALK_PX) to the left of the dock spot. */
export function freeWalk(r: { left: number; top: number; right: number; bottom: number }, self: Element | null, doc: Document = document): number {
  let free = 0
  for (let d = 12; d <= WALK_PX; d += 12) {
    if (rectCollides({ left: r.left - d, top: r.top, right: r.left - d + 12, bottom: r.bottom }, self, doc)) break
    free = d
  }
  return free
}

export interface DockProps {
  /** The current page (route.page). */
  page: string
  /** A modal, alert panel, palette, drawer or menu is open: all movement pauses. */
  modalOpen: boolean
  /** Home is showing its own calm owl (no real alerts): the dock stays away so there are never two owls on Home. */
  homeCalmOwl: boolean
  /** Board rows a person still has to review (New, Under review): the fixed caption "N to review". */
  count?: number
  /** Opens the PMS board. Without it the dock is decorative. */
  onOpen?: () => void
}

/** The only words the dock ever shows. */
export const dockCaption = (n: number): string => `${n} to review`
export const dockLabel = (n: number): string => `Noctua: open the PMS board, ${dockCaption(n)}`

export function NoctuaDock({ page, modalOpen, homeCalmOwl, count = 0, onOpen }: DockProps) {
  const hidden = useNoctuaHidden()
  const ref = useRef<HTMLDivElement>(null)
  const [covering, setCovering] = useState(false)
  const [typing, setTyping] = useState(false)
  const [walk, setWalk] = useState(false)
  const [look, setLook] = useState(false)
  const [phone, setPhone] = useState(() => typeof window !== 'undefined' && !!window.matchMedia?.('(max-width: 767px)').matches)
  const show = !hidden && !(page === 'home' && homeCalmOwl)

  // Hero walk: once per session, on Home only, after the page has rendered. The walk is as long as the free space to the
  // left of the dock (up to 96 px, at least 24 px, or no walk), so it never passes over text or a control. Stops on scroll.
  const [walkPx, setWalkPx] = useState(0)
  useEffect(() => {
    if (!show || page !== 'home') return
    let stopT = 0
    const stop = () => setWalk(false)
    const startT = window.setTimeout(() => {
      const el = ref.current
      const r = el?.getBoundingClientRect()
      const free = r ? freeWalk(r, el) : 0
      if (free < MIN_WALK_PX) return
      if (!firstWalk()) return
      setWalkPx(free)
      setWalk(true)
      stopT = window.setTimeout(stop, 3200)
      window.addEventListener('scroll', stop, { capture: true, once: true })
    }, 900)
    return () => {
      window.clearTimeout(startT)
      window.clearTimeout(stopT)
      window.removeEventListener('scroll', stop, { capture: true })
    }
  }, [show, page])

  // Any open popover, menu or modal dialog (the alert bell list, the theme menu, the alert panel) pauses movement too.
  const [overlay, setOverlay] = useState(false)
  useEffect(() => {
    const check = () => setOverlay(!!document.querySelector(OVERLAY_SELECTOR))
    check()
    const mo = new MutationObserver(check)
    mo.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-popover-open', 'open', 'aria-modal'] })
    return () => mo.disconnect()
  }, [])

  // Typing anywhere pauses movement.
  useEffect(() => {
    const on = () => {
      const a = document.activeElement
      setTyping(!!a && (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA' || (a as HTMLElement).isContentEditable))
    }
    document.addEventListener('focusin', on)
    document.addEventListener('focusout', on)
    return () => {
      document.removeEventListener('focusin', on)
      document.removeEventListener('focusout', on)
    }
  }, [])

  // Ducks away when it would cover something; re-checked on scroll, resize and page change (one check per frame).
  useEffect(() => {
    if (!show) return
    let raf = 0
    const check = () => {
      raf = 0
      const el = ref.current
      if (!el) return
      const r = el.getBoundingClientRect()
      // Include the 12 px idle-glide drift to the left.
      setCovering(rectCollides({ left: r.left - GLIDE_PX, top: r.top, right: r.right, bottom: r.bottom }, el))
    }
    const queue = () => {
      if (!raf) raf = window.requestAnimationFrame(check)
    }
    const mq = window.matchMedia?.('(max-width: 767px)')
    const onMq = () => setPhone(!!mq?.matches)
    queue()
    const t = window.setTimeout(queue, 600)
    window.addEventListener('scroll', queue, true)
    window.addEventListener('resize', queue)
    mq?.addEventListener?.('change', onMq)
    return () => {
      if (raf) window.cancelAnimationFrame(raf)
      window.clearTimeout(t)
      window.removeEventListener('scroll', queue, true)
      window.removeEventListener('resize', queue)
      mq?.removeEventListener?.('change', onMq)
    }
  }, [show, page])

  if (!show) return null
  const frozen = modalOpen || overlay || typing || (FROZEN_PAGES as readonly string[]).includes(page)
  const cls = ['ms-noctua-dock', frozen ? 'is-paused' : '', walk && !frozen ? 'is-walk' : '', covering ? 'is-away' : ''].filter(Boolean).join(' ')
  return (
    <div ref={ref} className={cls} style={walk ? ({ '--ms-walk': `${-walkPx}px` } as CSSProperties) : undefined} data-testid="noctua-dock" data-frozen={frozen ? 'true' : 'false'} data-away={covering ? 'true' : 'false'}>
      {onOpen && count > 0 && (
        <span className="ms-noctua-dock-caption" aria-hidden="true" data-testid="noctua-dock-caption">
          {dockCaption(count)}
        </span>
      )}
      {onOpen ? (
        <button
          type="button"
          className="ms-noctua-dock-body ms-noctua-dock-open"
          aria-label={dockLabel(count)}
          title={dockLabel(count)}
          onClick={onOpen}
          onMouseEnter={() => setLook(true)}
          onMouseLeave={() => setLook(false)}
          onFocus={() => setLook(true)}
          onBlur={() => setLook(false)}
          data-testid="noctua-dock-open"
        >
          <MascotOwl state={look && !frozen ? 'watching' : 'idle'} size={phone ? DOCK_SIZE_PHONE : DOCK_SIZE} />
        </button>
      ) : (
        <div className="ms-noctua-dock-body" aria-hidden="true">
          <MascotOwl state="idle" size={phone ? DOCK_SIZE_PHONE : DOCK_SIZE} />
        </div>
      )}
      <button type="button" className="ms-noctua-dock-hide" aria-label="Hide Noctua" title="Hide Noctua (Show Noctua is in the Theme menu)" onClick={() => setNoctuaHidden(true)} data-testid="noctua-dock-hide">
        <span aria-hidden="true">×</span>
      </button>
    </div>
  )
}
