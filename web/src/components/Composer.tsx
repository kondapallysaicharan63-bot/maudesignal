import { useState } from 'react'
import { STREAMLIT_URL } from '../data'
import { Icon } from '../icons'
import { closestThread } from '../match'
import type { Thread } from '../types'

const DISCLAIMER =
  'Signals for a person to review. Not medical advice; a named person makes every decision. Nothing is filed with FDA.'

// Recorded threads offered as starting points (ids from threads.json). Missing ids are skipped.
const SUGGESTED = ['01-what-changed', '05-capa-need-evidence', '06-trap', '10-recalls', '23-mhra']
const SHOWN = 3

interface Props {
  threads: Thread[]
  onThread: (id: string) => void
  /** Identifies what is on screen; a message about one screen is not shown on another. */
  viewKey: string
}

type Notice = ({ kind: 'match'; question: string } | { kind: 'live' }) & { forKey: string }

export function Composer({ threads, onThread, viewKey }: Props) {
  const [text, setText] = useState('')
  const [saved, setNotice] = useState<Notice | null>(null)
  const notice = saved && saved.forKey === viewKey ? saved : null
  const [more, setMore] = useState(false)

  const suggested = SUGGESTED.map((id) => threads.find((t) => t.id === id)).filter((t): t is Thread => !!t)
  const shown = more ? suggested : suggested.slice(0, SHOWN)
  const hidden = suggested.length - SHOWN

  const submit = () => {
    if (!text.trim()) return
    const m = closestThread(text, threads)
    if (m) {
      setNotice({ kind: 'match', question: m.thread.question, forKey: `thread:${m.thread.id}` })
      setText('')
      onThread(m.thread.id)
    } else setNotice({ kind: 'live', forKey: viewKey })
  }

  return (
    <div className="shrink-0 border-t border-rule bg-paper px-3 pb-[calc(1rem+env(safe-area-inset-bottom))] pt-3 md:px-6">
      <div className="mx-auto max-w-3xl">
        {suggested.length > 0 && (
          <div className="mb-2">
            <p className="m-0 mb-1 text-[13px] text-ink-3">Recorded questions you can open</p>
            <ul className="m-0 flex list-none flex-wrap gap-2 p-0" aria-label="Suggested prompts">
              {shown.map((t) => (
                <li key={t.id} className="min-w-0 max-w-full">
                  <button
                    onClick={() => {
                      setNotice(null)
                      onThread(t.id)
                    }}
                    className="block max-w-[10.5rem] truncate rounded-full border border-rule-strong bg-surface px-3 py-1.5 text-[14px] text-ink hover:bg-sunk sm:max-w-[260px]"
                    title={t.question}
                  >
                    {t.question}
                  </button>
                </li>
              ))}
              {hidden > 0 && (
                <li>
                  <button
                    onClick={() => setMore((m) => !m)}
                    aria-expanded={more}
                    className="rounded-full border border-rule-strong bg-sunk px-3 py-1.5 text-[14px] font-semibold text-ink hover:bg-surface"
                  >
                    {more ? 'Show fewer' : `${hidden} more`}
                  </button>
                </li>
              )}
            </ul>
          </div>
        )}
        {notice && (
          <div role="status" className="ms-banner ms-banner--info mb-2 text-[15px]">
            {notice.kind === 'match' ? (
              <p className="ws-wrap m-0">
                <strong>Closest recorded answer:</strong> {notice.question}
              </p>
            ) : (
              <p className="ws-wrap m-0">
                <strong>No recorded question is close to that.</strong> Live questions run in the Streamlit app,
                where the copilot asks the model in real time.{' '}
                <a href={STREAMLIT_URL} target="_blank" rel="noreferrer" className="font-semibold underline">
                  Ask live
                </a>
              </p>
            )}
          </div>
        )}
        <form
          className="flex items-center gap-2 rounded-md border border-rule-strong bg-surface py-1 pl-3 pr-1"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          <Icon name="search" size={18} />
          <input
            value={text}
            onChange={(e) => {
              setText(e.target.value)
              setNotice(null)
            }}
            aria-label="Ask a question"
            placeholder="Type a question to find the closest recorded answer"
            className="h-11 min-w-0 flex-1 bg-transparent text-[17px] text-ink placeholder:text-ink-3 focus:outline-none"
          />
          <button type="submit" className="ms-btn ms-btn--secondary shrink-0" style={{ height: 40 }}>
            Open
          </button>
        </form>
        <p className="mt-2 pr-20 text-center text-[13px] leading-snug text-ink-3 md:pr-0">{DISCLAIMER}</p>
      </div>
    </div>
  )
}
