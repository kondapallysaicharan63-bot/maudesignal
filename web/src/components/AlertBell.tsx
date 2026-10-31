import { useEffect, useState } from 'react'
import { groupAlerts, type AlertItem } from '../dashboard'
import { Icon } from '../icons'
import { readStore, writeStore } from '../storage'
import { Pill } from './artifacts/common'

const SOURCE_LABEL: Record<AlertItem['source'], string> = {
  sweep: 'AI device sweep',
  brief: 'Demo snapshot brief',
  company: 'Our devices (simulated)',
}

/** Shown over the simulated devices in the bell when company.json is not at hand (the contract string). */
const FALLBACK_BANNER = 'Simulated company — sample data. Problem evidence is real FDA data.'

const SEEN_KEY = 'ms-seen-alerts'

/** Alert ids the person marked as seen (a per-browser convenience; the alerts themselves stay listed). */
export function useSeen(): { seen: string[]; markAll: (ids: string[]) => void } {
  const [seen, setSeen] = useState<string[]>(() => {
    try {
      const v = JSON.parse(readStore(SEEN_KEY) ?? '[]') as unknown
      return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []
    } catch {
      return []
    }
  })
  const markAll = (ids: string[]) =>
    setSeen((cur) => {
      const n = [...new Set([...cur, ...ids])]
      writeStore(SEEN_KEY, JSON.stringify(n))
      return n
    })
  return { seen, markAll }
}

/** One alert: the device name with its code, the kind as a pill, then where it comes from and when. */
const sourceLabel = (a: AlertItem): string => (a.mine ? 'Your company' : SOURCE_LABEL[a.source])

function AlertRow({ a, onOpen, dim }: { a: AlertItem; onOpen: (a: AlertItem) => void; dim?: boolean }) {
  return (
    <li className="border-t border-rule first:border-t-0">
      <button
        type="button"
        className={[
          'flex min-h-11 w-full items-center justify-between gap-2 rounded-xs py-2 text-left text-[17px] leading-snug text-ink hover:bg-sunk',
          dim ? 'opacity-75' : '',
        ].join(' ')}
        onClick={() => onOpen(a)}
        aria-label={`${a.deviceName ? `${a.deviceName}, ` : ''}${a.productCode}: ${a.label}. ${sourceLabel(a)}, ${a.date}. Open.`}
      >
        <span className="min-w-0">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            {a.deviceName && <span className="ws-wrap font-semibold">{a.deviceName}</span>}
            <span className="ms-code !text-[17px] !text-ink">{a.productCode}</span>
            <Pill tone={a.kind === 'severity_escalation' ? 'bad' : 'warn'}>{a.label}</Pill>
          </span>
          <span className="ws-wrap block text-[17px] text-ink-2">
            {a.detail} · {sourceLabel(a)} · <span className="ms-num whitespace-nowrap">{a.date}</span>
          </span>
        </span>
        <span className="shrink-0 text-accent" aria-hidden="true">
          <Icon name="chevron" size={20} />
        </span>
      </button>
    </li>
  )
}

/** The alerts, each a link to the view that shows it (chevron, 44px tap target). */
export function AlertList({ items, onOpen, seen = [] }: { items: AlertItem[]; onOpen: (a: AlertItem) => void; seen?: string[] }) {
  if (items.length === 0) return <p className="m-0 text-ink-2">No alerts right now.</p>
  return (
    <ul className="m-0 list-none p-0" aria-label="Alerts">
      {items.map((a) => (
        <AlertRow key={a.id} a={a} onOpen={onOpen} dim={seen.includes(a.id)} />
      ))}
    </ul>
  )
}

/** One group with its heading, count and a link to everything of that kind. */
export function AlertGroup({
  title,
  items,
  onOpen,
  onViewAll,
  viewAllLabel,
  seen,
  banner,
}: {
  banner?: string
  title: string
  items: AlertItem[]
  onOpen: (a: AlertItem) => void
  onViewAll: () => void
  viewAllLabel: string
  seen: string[]
}) {
  if (items.length === 0) return null
  return (
    <section aria-label={title} className="mb-3" data-testid="alert-group">
      <div className="flex items-center justify-between gap-2 border-b border-rule-strong pb-1">
        <h3 className="m-0 font-serif text-[20px] font-semibold">
          {title} · <span className="ms-num">{items.length}</span>
        </h3>
        <button type="button" className="min-h-11 shrink-0 px-1 text-[17px] font-semibold text-accent underline" onClick={onViewAll}>
          {viewAllLabel}
        </button>
      </div>
      {banner && (
        <p className="ms-banner ms-banner--warn m-0 mt-2" data-testid="alert-group-banner">
          <span className="ws-wrap font-semibold">{banner}</span>
        </p>
      )}
      <AlertList items={items} onOpen={onOpen} seen={seen} />
    </section>
  )
}

/** Top-bar bell: a red badge with the number of unseen risky items; click for the list in two groups. */
export function AlertBell({
  items,
  onOpen,
  onViewAll = () => undefined,
  companyBanner = FALLBACK_BANNER,
  seenState,
}: {
  /** Shared with the alert buddy so both agree on what is unseen; the bell keeps its own when absent. */
  seenState?: { seen: string[]; markAll: (ids: string[]) => void }
  items: AlertItem[]
  /** The banner of company.json, printed over the simulated devices. */
  companyBanner?: string
  onOpen: (a: AlertItem) => void
  /** "View all" of a group: the AI device sweep for signals, the Needs review devices for the simulated company. */
  onViewAll?: (group: 'signals' | 'devices') => void
}) {
  const [open, setOpen] = useState(false)
  const own = useSeen()
  const { seen, markAll } = seenState ?? own
  const unseen = items.filter((a) => !seen.includes(a.id)).length
  const { signals, devices } = groupAlerts(items)
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
    <div className="relative mr-2">
      <button
        type="button"
        className="ws-icon-btn relative"
        onClick={() => setOpen((o) => !o)}
        aria-label={items.length === 0 ? 'Alerts: no risky items' : unseen === 0 ? 'Alerts: nothing new' : `Alerts: ${unseen} risky ${unseen === 1 ? 'item' : 'items'}`}
        aria-expanded={open}
        aria-controls="alert-list"
        data-testid="alert-bell"
      >
        <Icon name="bell" />
        {unseen > 0 && (
          <span
            className="absolute -right-2 -top-2 flex h-6 min-w-6 items-center justify-center rounded-full bg-critical px-1.5 text-[15px] font-bold leading-none text-[var(--on-critical)] ring-2 ring-paper"
            data-testid="alert-badge"
            aria-hidden="true"
          >
            {unseen}
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
            className="fixed inset-0 z-[60] flex flex-col overflow-hidden border border-rule-strong bg-surface shadow-[var(--shadow-pop)] sm:absolute sm:inset-x-auto sm:bottom-auto sm:right-0 sm:top-12 sm:max-h-[min(40rem,85dvh)] sm:w-[30rem] sm:rounded-md"
          >
            <div className="flex shrink-0 items-center justify-between gap-2 border-b border-rule p-4 pb-2">
              <h2 className="m-0 text-[20px] font-semibold">
                Alerts · <span className="ms-num">{items.length}</span>
              </h2>
              <button type="button" className="ws-icon-btn min-h-11 min-w-11" onClick={() => setOpen(false)} aria-label="Close alerts">
                <Icon name="close" />
              </button>
            </div>
            <div className="ws-fade-bottom min-h-0 flex-1 overflow-y-auto px-4 pb-6 pt-3" data-testid="alert-scroll">
              {items.length === 0 && <p className="m-0 text-ink-2">No alerts right now.</p>}
              <AlertGroup
                title="Signals"
                items={signals}
                onOpen={(a) => {
                  setOpen(false)
                  onOpen(a)
                }}
                onViewAll={() => {
                  setOpen(false)
                  onViewAll('signals')
                }}
                viewAllLabel="View all"
                seen={seen}
              />
              <AlertGroup
                title={devices.some((x) => x.mine) ? 'Our devices (your company)' : 'Our devices (simulated)'}
                items={devices}
                onOpen={(a) => {
                  setOpen(false)
                  onOpen(a)
                }}
                onViewAll={() => {
                  setOpen(false)
                  onViewAll('devices')
                }}
                viewAllLabel="View all"
                seen={seen}
                banner={companyBanner}
              />
              <p className="m-0 mt-2 text-[16px] leading-snug text-ink-2">
                Signals: a new kind of problem, or more serious than usual, in the AI device sweep and the newest demo-snapshot brief.
                Our devices: devices that need review (simulated, or yours in Make it yours). Signals for a person to review.
              </p>
            </div>
            <div className="flex shrink-0 items-center justify-between gap-2 border-t border-rule p-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))]">
              <button
                type="button"
                className="ms-btn ms-btn--secondary"
                style={{ height: 44 }}
                disabled={unseen === 0}
                onClick={() => markAll(items.map((a) => a.id))}
              >
                Mark all seen
              </button>
              <span className="text-[16px] text-ink-2">{unseen === 0 ? 'All seen' : `${unseen} not seen`}</span>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
