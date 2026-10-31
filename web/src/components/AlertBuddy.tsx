// The alert buddy: a small original MaudeSignal character in the top bar. Calm and breathing when nothing needs a look;
// pulsing in the danger colour, with a short speech bubble (once per session), when alerts do. The count is shown on the alert bell's
// badge only; the buddy shows the state by expression and colour and carries the count in its label.
// Drawn with SVG and design tokens only; motion is CSS and is switched off by prefers-reduced-motion (the colour and the
// count badge still show the state).
import { useEffect, useState } from 'react'
import type { AlertItem } from '../dashboard'

/** How long the speech bubble stays; hover or keyboard focus shows it again (it is hidden on phones). */
export const BUBBLE_MS = 4000
/** The bubble opens by itself once per browser session (sessionStorage; if blocked, once per page load). */
export const BUBBLE_KEY = 'ms-buddy-bubble-seen-v1'
let shownThisLoad = false
function firstBubble(): boolean {
  if (shownThisLoad) return false
  try {
    if (sessionStorage.getItem(BUBBLE_KEY)) return false
    sessionStorage.setItem(BUBBLE_KEY, '1')
  } catch {
    /* blocked: the per-load flag below still limits it to one */
  }
  shownThisLoad = true
  return true
}
/** For tests: forget that the bubble was shown. */
export function resetBubbleSeen(): void {
  shownThisLoad = false
  try {
    sessionStorage.removeItem(BUBBLE_KEY)
  } catch {
    /* ignore */
  }
}

/** "3 alerts need a look" / "1 alert needs a look". */
export const buddyText = (n: number): string => `${n} ${n === 1 ? 'alert needs' : 'alerts need'} a look`

/** The accessible name: the state in words. */
export const buddyLabel = (n: number): string =>
  n > 0 ? `Alert buddy: ${buddyText(n)}. Open the first one.` : 'Alert buddy: calm, no alerts need a look.'

/** The character: a round signal blob with two eyes and an antenna with a signal arc. */
export function BuddyFace({ alert, size = 30 }: { alert: boolean; size?: number }) {
  return (
    <svg
      viewBox="0 0 32 32"
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
      className={alert ? 'ms-buddy-svg ms-buddy-svg--alert' : 'ms-buddy-svg'}
      data-testid="buddy-svg"
    >
      <path d="M21 5.5a5 5 0 0 1 4 4M23.5 2.5a8.5 8.5 0 0 1 6 6" className="ms-buddy-arc" fill="none" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M16 8V4.5" className="ms-buddy-line" fill="none" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="16" cy="4" r="1.6" className="ms-buddy-tip" />
      <circle cx="16" cy="19" r="11" className="ms-buddy-body" strokeWidth="1.8" />
      <circle cx="12.2" cy="17.6" r="1.7" className="ms-buddy-eye" />
      <circle cx="19.8" cy="17.6" r="1.7" className="ms-buddy-eye" />
      {alert ? (
        <ellipse cx="16" cy="24" rx="2.4" ry="2" className="ms-buddy-mouth" fill="none" strokeWidth="1.8" />
      ) : (
        <path d="M12.8 22.6q3.2 2.6 6.4 0" className="ms-buddy-mouth" fill="none" strokeWidth="1.8" strokeLinecap="round" />
      )}
    </svg>
  )
}

/**
 * `count` is the number of alerts the bell shows as unseen. With none the buddy is a calm picture (not a control);
 * with some it is a button: click or Enter opens the first alert's panel.
 */
export function AlertBuddy({ items, count, onOpen }: { items: AlertItem[]; count: number; onOpen: (a: AlertItem) => void }) {
  // 'auto': shown once on the first visit; 'user': shown on hover or focus. The page hides the 'auto' one where the
  // message box is shown (it can cover the claims strip), never the one the person asked for.
  const [bubble, setBubble] = useState<false | 'auto' | 'user'>(false)
  useEffect(() => {
    if (count <= 0) return
    if (firstBubble()) setBubble('auto')
  }, [count > 0]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!bubble) return
    const t = window.setTimeout(() => setBubble(false), BUBBLE_MS)
    return () => window.clearTimeout(t)
  }, [bubble])
  if (count <= 0)
    return (
      <span className="ms-buddy" role="img" aria-label={buddyLabel(0)} data-testid="alert-buddy" data-state="calm">
        <BuddyFace alert={false} />
      </span>
    )
  return (
    <span className="relative inline-flex" onMouseEnter={() => setBubble('user')} onMouseLeave={() => setBubble(false)} onFocus={() => setBubble('user')} onBlur={() => setBubble(false)}>
      <button
        type="button"
        className="ms-buddy ws-icon-btn"
        aria-label={buddyLabel(count)}
        onClick={() => {
          const first = items[0]
          if (first) onOpen(first)
        }}
        data-testid="alert-buddy"
        data-state="alert"
      >
        <BuddyFace alert />
      </button>
      {bubble && (
        <span className="ms-buddy-bubble" aria-hidden="true" data-testid="buddy-bubble" data-auto={bubble === 'auto' ? 'true' : undefined}>
          {buddyText(count)}
        </span>
      )}
    </span>
  )
}
