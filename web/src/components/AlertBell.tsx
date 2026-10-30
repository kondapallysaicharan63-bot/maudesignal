import { useEffect, useState } from 'react'
import type { AlertItem } from '../dashboard'
import { Icon } from '../icons'
import { Pill } from './artifacts/common'

/** The alerts, each a link to the view that shows it (chevron, 44px tap target). */
export function AlertList({ items, onOpen }: { items: AlertItem[]; onOpen: (a: AlertItem) => void }) {
  if (items.length === 0) return <p className="m-0 text-ink-2">No alerts right now.</p>
  return (
    <ul className="m-0 list-none p-0" aria-label="Alerts">
      {items.map((a) => (
        <li key={a.id} className="border-t border-rule first:border-t-0">
          <button
            type="button"
            className="flex min-h-11 w-full items-center justify-between gap-2 rounded-xs py-2 text-left text-[17px] leading-snug text-ink hover:bg-sunk"
            onClick={() => onOpen(a)}
            aria-label={`${a.productCode}: ${a.label}. ${a.source === 'sweep' ? 'AI device sweep' : 'Demo snapshot brief'}, ${a.date}. Open.`}
          >
            <span className="min-w-0">
              <span className="flex flex-wrap items-center gap-2">
                <span className="ms-code !text-[17px] !text-ink">{a.productCode}</span>
                <Pill tone={a.kind === 'severity_escalation' ? 'bad' : 'warn'}>{a.label}</Pill>
              </span>
              <span className="ws-wrap block text-[17px] text-ink-2">
                {a.detail} · {a.source === 'sweep' ? 'AI device sweep' : 'Demo snapshot brief'} ·{' '}
                <span className="ms-num whitespace-nowrap">{a.date}</span>
              </span>
            </span>
            <span className="shrink-0 text-accent" aria-hidden="true">
              <Icon name="chevron" size={20} />
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
  const n = items.length
  useEffect(() => {
    if (!open) return
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', key)
    return () => {
      window.removeEventListener('keydown', key)
    }
  }, [open])
  return (
    <div className="relative">
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
            className="absolute -right-1.5 -top-1.5 flex h-7 min-w-7 items-center justify-center rounded-full bg-critical px-1.5 text-[15px] font-bold leading-none text-[var(--on-critical)] ring-2 ring-paper"
            data-testid="alert-badge"
            aria-hidden="true"
          >
            {n}
          </span>
        )}
      </button>
      {open && (
        <>
          <div className="ws-scrim z-[55]" onClick={() => setOpen(false)} aria-hidden="true" data-testid="alert-scrim" />
          <div
            id="alert-list"
            data-popover-open
            role="dialog"
            aria-label="Alerts"
            className="fixed inset-x-0 bottom-0 z-[60] max-h-[80dvh] overflow-y-auto rounded-t-md border border-rule-strong bg-surface p-4 pb-[calc(1rem+env(safe-area-inset-bottom))] shadow-[var(--shadow-pop)] sm:absolute sm:inset-x-auto sm:bottom-auto sm:right-0 sm:top-12 sm:w-[28rem] sm:rounded-md sm:pb-4"
          >
            <div className="mb-2 flex items-center justify-between gap-2">
              <h2 className="m-0 text-[18px] font-semibold">
                Alerts · <span className="ms-num">{n}</span>
              </h2>
              <button type="button" className="ws-icon-btn min-h-11 min-w-11" onClick={() => setOpen(false)} aria-label="Close alerts">
                <Icon name="close" />
              </button>
            </div>
            <AlertList
              items={items}
              onOpen={(a) => {
                setOpen(false)
                onOpen(a)
              }}
            />
            <p className="m-0 mt-3 text-[15px] leading-snug text-ink-2">
              A new kind of problem, or more serious than usual, in the AI device sweep and the newest demo-snapshot brief. Signals for a
              person to review.
            </p>
          </div>
        </>
      )}
    </div>
  )
}
