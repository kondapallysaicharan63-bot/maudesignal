import { useId, useMemo, useState } from 'react'
import { STREAMLIT_URL } from '../data'
import { Icon } from '../icons'
import { closestThread } from '../match'
import { exactKnownCode, moveActive, suggest, type CodeInfo, type Suggestion } from '../typeahead'
import type { Thread } from '../types'

const DISCLAIMER =
  'Signals for a person to review. Not medical advice; a named person makes every decision. Nothing is filed with FDA.'
const DISCLAIMER_SHORT = 'Signals for review. Not medical advice. Nothing is filed with FDA.'

// Recorded threads offered as starting points (ids from threads.json). Missing ids are skipped.
const SUGGESTED = ['01-what-changed', '05-capa-need-evidence', '06-trap', '10-recalls', '23-mhra']

interface Props {
  threads: Thread[]
  onThread: (id: string) => void
  /** Identifies what is on screen; a message about one screen is not shown on another. */
  viewKey: string
  /** Device codes from the stored sweep and briefs, for the type-ahead. */
  codes: CodeInfo[]
  /** Choosing a code opens "Check any device type" with it filled in. */
  onCode: (code: string) => void
  /** Camera: opens the label photo screen (live when the API answers, a recorded run otherwise). */
  onCamera: () => void
  /** Mic: opens the voice screen (live when the API answers, a recorded run otherwise). */
  onMic: () => void
}

type Notice = ({ kind: 'match'; question: string } | { kind: 'live' }) & { forKey: string }

/**
 * One input row with a type-ahead list of recorded questions (also shown on focus, as the starting points),
 * plus camera and mic buttons that open recorded runs until the live API is on.
 */
export function Composer({ threads, onThread, viewKey, codes, onCode, onCamera, onMic }: Props) {
  const [text, setText] = useState('')
  const [saved, setNotice] = useState<Notice | null>(null)
  const notice = saved && saved.forKey === viewKey ? saved : null
  const [focus, setFocus] = useState(false)
  const [active, setActive] = useState(-1)
  const listId = useId()

  const starters = useMemo(
    () => SUGGESTED.map((id) => threads.find((t) => t.id === id)).filter((t): t is Thread => !!t),
    [threads],
  )
  const typed = text.trim().length > 0
  const options = useMemo<Suggestion[]>(
    () => (typed ? suggest(text, threads, codes) : starters.map((thread) => ({ kind: 'question' as const, thread }))),
    [typed, text, threads, codes, starters],
  )
  const open = focus && options.length > 0

  const pick = (sg: Suggestion) => {
    setNotice(null)
    setText('')
    setFocus(false)
    setActive(-1)
    if (sg.kind === 'code') onCode(sg.code)
    else onThread(sg.thread.id)
  }

  const submit = () => {
    if (open && active >= 0 && options[active]) return pick(options[active])
    if (!typed) return
    const known = exactKnownCode(text, codes)
    if (known) {
      setText('')
      setFocus(false)
      return onCode(known)
    }
    const m = closestThread(text, threads)
    if (/^[A-Za-z]{3}$/.test(text.trim()) && !m) {
      const c = text.trim().toUpperCase()
      setText('')
      setFocus(false)
      return onCode(c)
    }
    if (m) {
      setNotice({ kind: 'match', question: m.thread.question, forKey: `thread:${m.thread.id}` })
      setText('')
      setFocus(false)
      onThread(m.thread.id)
    } else setNotice({ kind: 'live', forKey: viewKey })
  }

  return (
    <div className="shrink-0 border-t border-rule bg-paper px-3 pb-[calc(0.5rem+env(safe-area-inset-bottom))] pt-2 md:px-6">
      <div className="mx-auto max-w-3xl">
        {notice && (
          <div role="status" className="ms-banner ms-banner--info mb-2 text-[16px]">
            {notice.kind === 'match' ? (
              <p className="ws-wrap m-0">
                <strong>Closest recorded answer:</strong> {notice.question}
              </p>
            ) : (
              <p className="ws-wrap m-0">
                <strong>No recorded question is close to that.</strong> Live questions run in the Streamlit app, where the copilot
                asks the model in real time.{' '}
                <a href={STREAMLIT_URL} target="_blank" rel="noreferrer" className="font-semibold underline">
                  Ask live
                </a>
              </p>
            )}
          </div>
        )}
        <form
          className="relative flex items-center gap-1 rounded-md border border-rule-strong bg-surface py-1 pl-3 pr-1"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          {open && (
            <div
              data-popover-open
              className="absolute inset-x-0 bottom-full z-40 mb-1 max-h-[45dvh] overflow-y-auto rounded-md border border-rule-strong bg-surface p-1 shadow-[var(--shadow-pop)]"
            >
              <p className="m-0 px-3 pb-1 pt-2 text-[14px] font-semibold text-ink-2" id={`${listId}-h`}>
                {typed ? 'Suggestions: recorded questions and device codes' : 'Recorded questions you can open'}
              </p>
              <ul id={listId} role="listbox" aria-labelledby={`${listId}-h`} className="m-0 list-none p-0">
                {options.map((sg, i) => (
                  <li
                    key={sg.kind === 'code' ? `code-${sg.code}` : sg.thread.id}
                    id={`${listId}-${i}`}
                    role="option"
                    aria-selected={i === active}
                    // mouse down (not click) so the input keeps focus long enough for the pick to register
                    onMouseDown={(e) => {
                      e.preventDefault()
                      pick(sg)
                    }}
                    className={[
                      'flex min-h-11 cursor-pointer items-center gap-2 rounded-xs px-3 py-2 text-[17px] leading-snug text-ink hover:bg-sunk',
                      i === active ? 'bg-sunk' : '',
                    ].join(' ')}
                  >
                    {sg.kind === 'code' ? (
                      <span className="ws-wrap min-w-0 flex-1">
                        <span className="ms-code mr-2">{sg.code}</span>
                        Check any device type
                        {sg.name ? <span className="text-ink-2"> · {sg.name}</span> : null}
                      </span>
                    ) : (
                      <span className="ws-wrap line-clamp-2 min-w-0 flex-1">{sg.thread.question}</span>
                    )}
                    <Icon name="chevron" size={18} />
                  </li>
                ))}
              </ul>
            </div>
          )}
          <Icon name="search" size={18} />
          <input
            value={text}
            onChange={(e) => {
              setText(e.target.value)
              setNotice(null)
              setActive(-1)
              setFocus(true)
            }}
            onFocus={() => setFocus(true)}
            onBlur={() => setFocus(false)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown' && options.length) {
                e.preventDefault()
                setFocus(true)
                setActive((i) => moveActive(i, 'ArrowDown', options.length))
              } else if (e.key === 'ArrowUp' && options.length) {
                e.preventDefault()
                setActive((i) => moveActive(i, 'ArrowUp', options.length))
              } else if (e.key === 'Escape' && open) {
                e.stopPropagation()
                setFocus(false)
              }
            }}
            role="combobox"
            aria-expanded={open}
            aria-controls={open ? listId : undefined}
            aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : undefined}
            aria-autocomplete="list"
            aria-label="Ask a question"
            placeholder="Ask a question"
            autoComplete="off"
            className="h-11 min-w-0 flex-1 bg-transparent text-[17px] text-ink placeholder:text-ink-3 focus:outline-none"
          />
          <button
            type="button"
            className="ws-icon-btn min-h-11 min-w-11 shrink-0"
            onClick={onCamera}
            aria-label="Camera: photograph a device label"
            title="Camera: photograph a device label"
            data-testid="composer-camera"
          >
            <Icon name="camera" />
          </button>
          <button
            type="button"
            className="ws-icon-btn min-h-11 min-w-11 shrink-0"
            onClick={onMic}
            aria-label="Mic: ask by voice"
            title="Mic: ask by voice"
            data-testid="composer-mic"
          >
            <Icon name="mic" />
          </button>
          <button type="submit" className="ms-btn ms-btn--secondary shrink-0" style={{ height: 40 }}>
            Open
          </button>
        </form>
        <p className="m-0 mt-1 text-center text-[14px] leading-snug text-ink-2">
          <span className="hidden sm:inline">{DISCLAIMER}</span>
          <span className="sm:hidden">{DISCLAIMER_SHORT}</span>
          <span className="hidden md:inline"> Camera and mic show a recorded run until the live API answers.</span>
        </p>
      </div>
    </div>
  )
}
