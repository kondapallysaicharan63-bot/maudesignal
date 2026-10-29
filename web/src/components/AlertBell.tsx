import { useEffect, useRef, useState } from 'react'
import type { AlertItem } from '../dashboard'
import { Icon } from '../icons'
import { Pill } from './artifacts/common'

/** The risky items, each a link to the view that shows it. */
export function AlertList({ items, onOpen }: { items: AlertItem[]; onOpen: (a: AlertItem) => void }) {
  if (items.length === 0) return <p className="m-0 text-ink-2">No risky items right now.</p>
  return (
    <ul className="m-0 list-none p-0" aria-label="Risky items">
      {items.map((a) => (
        <li key={a.id} className="border-t border-rule first:border-t-0">
          <button
            type="button"
            className="ws-side-item items-start !px-0 hover:!bg-transparent"
            onClick={() => onOpen(a)}
            aria-label={`${a.productCode}: ${a.label}. ${a.source === 'sweep' ? 'AI device sweep' : 'Demo snapshot brief'}, ${a.date}. Open.`}
          >
            <span className="min-w-0">
              <span className="flex flex-wrap items-center gap-2">
                <span className="ms-code !text-[14px] !text-ink">{a.productCode}</span>
                <Pill tone={a.kind === 'severity_escalation' ? 'bad' : 'warn'}>{a.label}</Pill>
              </span>
              <span className="ws-wrap block text-[15px] text-ink-2">
                {a.detail} · {a.source === 'sweep' ? 'AI device sweep' : 'Demo snapshot brief'} · <span className="ms-num">{a.date}</span>
              </span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}

/** Top-bar bell: a red badge with the number of risky items; click for the list. */
export function AlertBell({ items, onOpen }: { items: AlertItem[]; onOpen: (a: AlertItem) => void }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const n = items.length
  useEffect(() => {
    if (!open) return
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    const down = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener('keydown', key)
    window.addEventListener('mousedown', down)
    return () => {
      window.removeEventListener('keydown', key)
      window.removeEventListener('mousedown', down)
    }
  }, [open])
  return (
    <div ref={box} className="relative">
      <button
        type="button"
        className="ws-icon-btn relative"
        onClick={() => setOpen((o) => !o)}
        aria-label={n === 0 ? 'Alerts: no risky items' : `Alerts: ${n} risky ${n === 1 ? 'item' : 'items'}`}
        aria-expanded={open}
        aria-controls="alert-list"
        data-testid="alert-bell"
      >
        <Icon name="bell" />
        {n > 0 && (
          <span
            className="absolute -right-0.5 -top-0.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-critical px-1 text-[12px] font-bold leading-none text-[var(--on-critical)]"
            data-testid="alert-badge"
            aria-hidden="true"
          >
            {n}
          </span>
        )}
      </button>
      {open && (
        <div
          id="alert-list"
          data-popover-open
          className="fixed inset-x-3 top-16 z-50 max-h-[70dvh] overflow-y-auto rounded-md border border-rule-strong bg-surface p-4 shadow-[var(--shadow-pop)] sm:absolute sm:inset-x-auto sm:right-0 sm:top-12 sm:w-[26rem]"
        >
          <h2 className="m-0 mb-2 text-[16px] font-semibold">
            Risky items · <span className="ms-num">{n}</span>
          </h2>
          <AlertList
            items={items}
            onOpen={(a) => {
              setOpen(false)
              onOpen(a)
            }}
          />
          <p className="m-0 mt-3 text-[13px] leading-snug text-ink-3">
            A new kind of problem, or more serious than usual, in the AI device sweep and the newest demo-snapshot brief. Signals for a
            person to review.
          </p>
        </div>
      )}
    </div>
  )
}
