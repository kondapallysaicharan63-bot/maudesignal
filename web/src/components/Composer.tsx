import { useEffect, useRef, useState } from 'react'
import { Icon } from '../icons'
import type { Thread } from '../types'

const DISCLAIMER =
  'Signals for a person to review. Not medical advice; a named person makes every decision. Nothing is filed with FDA.'

// Recorded threads offered as starting points (ids from threads.json). Missing ids are skipped.
const SUGGESTED = ['01-what-changed', '05-capa-need-evidence', '06-trap', '10-recalls', '23-mhra']

// Nothing in this menu is implemented yet, so every entry is disabled and labelled.
const MENU = ['Upload file', 'From GitHub', 'From Google Drive']

interface Props {
  threads: Thread[]
  onThread: (id: string) => void
}

export function Composer({ threads, onThread }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent) {
        if (e.key === 'Escape') setOpen(false)
      } else if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
    }
  }, [open])

  const suggested = SUGGESTED.map((id) => threads.find((t) => t.id === id)).filter((t): t is Thread => !!t)

  return (
    <div className="shrink-0 border-t border-rule bg-paper px-3 pb-4 pt-3 md:px-6">
      <div className="mx-auto max-w-3xl">
        {suggested.length > 0 && (
          <div className="mb-2">
            <p className="m-0 mb-1 text-[13px] text-ink-3">Recorded questions you can open</p>
            <ul className="m-0 flex list-none gap-2 overflow-x-auto p-0 pb-1" aria-label="Suggested prompts">
              {suggested.map((t) => (
                <li key={t.id} className="shrink-0">
                  <button
                    onClick={() => onThread(t.id)}
                    className="max-w-[260px] truncate rounded-full border border-rule-strong bg-surface px-3 py-1.5 text-[14px] text-ink hover:bg-sunk"
                    title={t.question}
                  >
                    {t.question}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        <div ref={ref} className="relative">
          {open && (
            <div
              role="menu"
              aria-label="Add"
              className="absolute bottom-full left-0 z-20 mb-2 w-72 max-w-[calc(100vw-2rem)] rounded-md border border-rule-strong bg-surface p-1 shadow-lg"
            >
              {MENU.map((label) => (
                <button
                  key={label}
                  role="menuitem"
                  disabled
                  className="flex w-full items-center justify-between gap-2 rounded-xs px-3 py-2 text-left text-[15px] text-ink-3"
                >
                  {label}
                  <span className="ws-pill bg-sunk text-ink-2">coming soon</span>
                </button>
              ))}
              <div className="flex items-center justify-between gap-2 border-t border-rule px-3 py-2 text-[15px] text-ink-3">
                <label htmlFor="connected-sources">Connected sources</label>
                <span className="flex items-center gap-2">
                  <input id="connected-sources" type="checkbox" role="switch" disabled checked={false} readOnly />
                  <span className="ws-pill bg-sunk text-ink-2">coming soon</span>
                </span>
              </div>
            </div>
          )}
          <div className="flex items-center gap-2 rounded-md border border-rule-strong bg-surface px-3 py-2">
            <button
              className="ws-icon-btn"
              aria-label="Add"
              aria-haspopup="menu"
              aria-expanded={open}
              onClick={() => setOpen((o) => !o)}
            >
              <Icon name="plus" />
            </button>
            <input
              disabled
              aria-label="Message (coming soon)"
              placeholder="Asking new questions: coming soon"
              className="min-w-0 flex-1 bg-transparent text-[17px] text-ink placeholder:text-ink-3 focus:outline-none"
            />
          </div>
        </div>
        <p className="mt-2 text-center text-[13px] leading-snug text-ink-3">{DISCLAIMER}</p>
      </div>
    </div>
  )
}
