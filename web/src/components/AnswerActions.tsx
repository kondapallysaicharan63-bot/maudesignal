import { useEffect, useId, useRef, useState } from 'react'
import { ANSWER_REASON_MAX, buildAnswerRating, submitAnswerRating, type FetchLike, type Thumb } from '../feedback'
import { fmtClock } from '../live/answerMeta'
import { currentSpeakingKey, startReading, stopReading, useCanReadAloud, useSpeakingKey } from '../live/readAloud'

// Small stroke icons drawn here (currentColor), so the action bar needs no icon font or network.
const ICON = {
  copy: 'M9 9h10v11H9zM5 15V4h10',
  check: 'm5 12.5 4.5 4.5L19 7.5',
  speaker: 'M4 9.5h3.5L12 5.5v13l-4.5-4H4zM15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11',
  stop: 'M7 7h10v10H7z',
  up: 'M7 11v9H4v-9zM7 11l4-7c1.4 0 2.3 1 2 2.4L12.5 10H19a1.8 1.8 0 0 1 1.8 2.1l-1.2 6.3A2 2 0 0 1 17.6 20H7',
  down: 'M7 13V4H4v9zM7 13l4 7c1.4 0 2.3-1 2-2.4l-.5-3.6H19a1.8 1.8 0 0 0 1.8-2.1l-1.2-6.3A2 2 0 0 0 17.6 4H7',
  info: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 11v5M12 8v.01',
} as const

function Svg({ d }: { d: string }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={d} />
    </svg>
  )
}

/** Puts text on the clipboard: the async Clipboard API, else a hidden textarea and execCommand. */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    /* fall back below */
  }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = typeof document.execCommand === 'function' && document.execCommand('copy')
    ta.remove()
    return ok
  } catch {
    return false
  }
}

export interface RatingSink {
  apiBase: string | null
  refCode: string | null
  fetcher: (url: string, init: RequestInit) => Promise<FetchLike>
}

interface Props {
  answerId: string
  /** What Copy puts on the clipboard (answer and FDA links; never the question). */
  copy: string
  /** What Read aloud speaks; empty hides the button. */
  readable: string
  /** When the answer arrived (shown as local time). */
  at: Date
  rating: RatingSink
  details: { open: boolean; onToggle: () => void; panelId: string }
}

/** The small action bar under an answer: Copy, Read aloud / Stop, thumbs up / down (down asks an optional reason), Details, time. */
export function AnswerActions({ answerId, copy, readable, at, rating, details }: Props) {
  const canRead = useCanReadAloud() && readable.trim() !== ''
  const speaking = useSpeakingKey() === answerId
  const [copied, setCopied] = useState<'idle' | 'ok' | 'fail'>('idle')
  const [thumb, setThumb] = useState<Thumb | null>(null)
  const [reasonOpen, setReasonOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [status, setStatus] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const reasonId = useId()
  const box = useRef<HTMLTextAreaElement>(null)
  const downBtn = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (copied === 'idle') return
    const t = window.setTimeout(() => setCopied('idle'), 2000)
    return () => window.clearTimeout(t)
  }, [copied])
  useEffect(() => {
    if (reasonOpen) box.current?.focus()
  }, [reasonOpen])
  // Stop reading when this answer leaves the page.
  useEffect(() => () => {
    if (currentSpeakingKey() === answerId) stopReading()
  }, [answerId])

  const send = async (t: Thumb, why: string) => {
    setSending(true)
    const r = await submitAnswerRating(rating.apiBase, buildAnswerRating(answerId, t, why, rating.refCode), rating.fetcher)
    setSending(false)
    if (r.ok) {
      setThumb(t)
      setReasonOpen(false)
      setStatus(t === 'up' ? 'Thanks for the rating.' : 'Thanks. Your rating was sent.')
    } else setStatus(r.message)
  }

  return (
    <>
      <span className="ans-actions" role="group" aria-label="Answer actions">
        <button
          type="button"
          className="ans-ib"
          aria-label={copied === 'ok' ? 'Copied' : 'Copy answer and FDA links'}
          title={copied === 'ok' ? 'Copied' : 'Copy answer and FDA links'}
          data-testid="action-copy"
          onClick={async () => setCopied((await copyToClipboard(copy)) ? 'ok' : 'fail')}
        >
          <Svg d={copied === 'ok' ? ICON.check : ICON.copy} />
        </button>
        {canRead && (
          <button
            type="button"
            className="ans-ib"
            aria-label={speaking ? 'Stop reading aloud' : 'Read aloud'}
            title={speaking ? 'Stop reading aloud' : 'Read aloud'}
            aria-pressed={speaking}
            data-testid="action-read"
            onClick={() => (speaking ? stopReading() : startReading(answerId, readable))}
          >
            <Svg d={speaking ? ICON.stop : ICON.speaker} />
          </button>
        )}
        <button
          type="button"
          className="ans-ib"
          aria-label="Good answer"
          title="Good answer"
          aria-pressed={thumb === 'up'}
          disabled={sending}
          data-testid="action-up"
          onClick={() => {
            setReasonOpen(false)
            void send('up', '')
          }}
        >
          <Svg d={ICON.up} />
        </button>
        <button
          ref={downBtn}
          type="button"
          className="ans-ib"
          aria-label="Bad answer"
          title="Bad answer"
          aria-pressed={thumb === 'down'}
          aria-expanded={reasonOpen}
          aria-controls={reasonOpen ? reasonId : undefined}
          disabled={sending}
          data-testid="action-down"
          onClick={() => {
            setStatus(null)
            setReasonOpen((o) => !o)
          }}
        >
          <Svg d={ICON.down} />
        </button>
        <button
          type="button"
          className="ans-ib"
          aria-label="Details"
          title="Details: steps, timings, cost"
          aria-expanded={details.open}
          aria-controls={details.open ? details.panelId : undefined}
          data-testid="details-toggle"
          onClick={details.onToggle}
        >
          <Svg d={ICON.info} />
        </button>
        <time className="ans-time ms-num" dateTime={at.toISOString()} data-testid="answer-time">
          {fmtClock(at)}
        </time>
      </span>
      <span className="sr-only" role="status" aria-live="polite">
        {copied === 'ok' ? 'Copied the answer and its FDA links.' : copied === 'fail' ? 'Could not copy.' : ''}
      </span>
      {status && (
        <p className="ans-status m-0 w-full" role="status" data-testid="rating-status">
          {status}
        </p>
      )}
      {reasonOpen && (
        <form
          className="ans-reason w-full"
          id={reasonId}
          data-testid="rating-reason"
          onSubmit={(e) => {
            e.preventDefault()
            void send('down', reason)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              setReasonOpen(false)
              downBtn.current?.focus()
            }
          }}
        >
          <label htmlFor={`${reasonId}-t`}>What was wrong? (optional)</label>
          <textarea
            id={`${reasonId}-t`}
            ref={box}
            maxLength={ANSWER_REASON_MAX}
            value={reason}
            onChange={(e) => setReason(e.target.value.slice(0, ANSWER_REASON_MAX))}
            aria-describedby={`${reasonId}-c`}
            placeholder="Do not include patient details."
          />
          <div className="ans-reason-row">
            <span className="ans-count ms-num" id={`${reasonId}-c`}>
              {reason.length}/{ANSWER_REASON_MAX}
            </span>
            <button
              type="button"
              className="ms-btn ms-btn--secondary ms-btn--sm"
              onClick={() => {
                setReasonOpen(false)
                downBtn.current?.focus()
              }}
            >
              Cancel
            </button>
            <button type="submit" className="ms-btn ms-btn--primary ms-btn--sm" disabled={sending} data-testid="rating-send">
              Send rating
            </button>
          </div>
        </form>
      )}
    </>
  )
}
