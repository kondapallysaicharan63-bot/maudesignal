import { useState } from 'react'
import type { AlertItem } from '../dashboard'
import { Icon } from '../icons'
import { AlertBell } from './AlertBell'
import type { ThemeChoice } from '../storage'
import type { Manifest } from '../types'

interface Props {
  manifest: Manifest | null
  theme: ThemeChoice
  sidebarOpen: boolean
  artifactsOpen: boolean
  onToggleSidebar: () => void
  onToggleArtifacts: () => void
  onTheme: () => void
  onPalette: () => void
  onFeedback: () => void
  alerts: AlertItem[]
  onAlert: (a: AlertItem) => void
  /** company.json's banner, printed over the simulated devices in the bell. */
  companyBanner?: string
  onViewAll?: (group: 'signals' | 'devices') => void
  /** Opens the thread holding the first withheld sentence (omitted when none is stored). */
  onWithheld?: () => void
}

const THEME_ICON = { system: 'auto', light: 'sun', dark: 'moon' } as const
const THEME_NEXT = { system: 'light', light: 'dark', dark: 'system' } as const

export function Header(p: Props) {
  const [detail, setDetail] = useState(false)
  const h = p.manifest?.header
  return (
    <header className="shrink-0 border-b border-rule bg-paper">
      <div className="flex h-14 items-center gap-0.5 px-1.5 sm:gap-1 md:px-3">
        <button
          className="ws-icon-btn"
          onClick={p.onToggleSidebar}
          aria-label="Toggle sidebar"
          title={p.sidebarOpen ? 'Hide the sidebar' : 'Show the sidebar'}
          aria-controls="sidebar"
          aria-expanded={p.sidebarOpen}
        >
          <Icon name={p.sidebarOpen ? 'sidebarOpen' : 'sidebarShut'} />
        </button>
        <span className="t-wordmark mr-auto min-w-0 truncate pl-1 max-sm:!text-[19px]" style={{ fontSize: 22 }}>
          MaudeSignal
        </span>
        <button className="ws-icon-btn" onClick={p.onPalette} aria-label="Search workflows (Ctrl or Cmd K)">
          <Icon name="search" />
          <span className="hidden text-[15px] md:inline">Search</span>
          <kbd className="ms-code hidden rounded-xs border border-rule px-1 md:inline">Ctrl K</kbd>
        </button>
        <AlertBell items={p.alerts} onOpen={p.onAlert} onViewAll={p.onViewAll} companyBanner={p.companyBanner} />
        <button
          className="ws-icon-btn"
          onClick={p.onFeedback}
          aria-haspopup="dialog"
          aria-label="Give feedback"
        >
          <Icon name="chat" />
          <span className="hidden text-[15px] md:inline">Feedback</span>
        </button>
        <button
          className="ws-icon-btn"
          onClick={p.onTheme}
          aria-label={`Theme: ${p.theme}. Switch to ${THEME_NEXT[p.theme]}`}
          title={`Theme: ${p.theme}`}
        >
          <Icon name={THEME_ICON[p.theme]} />
        </button>
        <button
          className="ws-icon-btn"
          onClick={p.onToggleArtifacts}
          aria-label="Toggle artifacts"
          aria-controls="artifacts"
          aria-expanded={p.artifactsOpen}
        >
          <Icon name="panel" />
        </button>
      </div>
      <div className="border-t border-rule bg-sunk px-3 py-0.5 text-[16px] max-sm:text-[15px] md:px-4" role="status">
        {h ? (
          <>
            <div className="flex flex-nowrap items-center gap-x-2 sm:gap-x-3">
              <span className="shrink-0 whitespace-nowrap">
                <strong className="ms-num">{h.claims_verified}</strong> claims verified <span aria-hidden="true" className="max-sm:hidden">·</span>{' '}
                {p.onWithheld && h.sentences_withheld > 0 ? (
                  <button
                    type="button"
                    onClick={p.onWithheld}
                    className="inline-flex min-h-9 items-center rounded-xs border border-rule-strong bg-surface px-2 font-semibold text-ink underline decoration-dotted underline-offset-4 hover:bg-paper"
                    aria-label={`${h.sentences_withheld} ${h.sentences_withheld === 1 ? 'sentence' : 'sentences'} withheld: open the withheld sentence`}
                  >
                    <span className="ms-num">{h.sentences_withheld}</span>&nbsp;withheld
                  </button>
                ) : (
                  <>
                    <strong className="ms-num">{h.sentences_withheld}</strong> withheld
                  </>
                )}
              </span>
              {h.audit_chain_ok ? (
                <span className="ms-chip ms-chip--ok">
                  <Icon name="check" size={14} /> Audit<span className="max-sm:sr-only">&nbsp;verified</span>
                </span>
              ) : (
                <span className="ms-chip ms-chip--high">Audit chain not verified</span>
              )}
              <button
                type="button"
                className="ml-auto inline-flex min-h-9 shrink-0 items-center gap-1 text-[16px] font-semibold text-accent underline max-sm:text-[15px]"
                aria-expanded={detail}
                aria-controls="audit-detail"
                onClick={() => setDetail((d) => !d)}
              >
                Details
              </button>
            </div>
            {detail && (
              <p id="audit-detail" className="m-0 pb-1 text-ink-2">
                Every sentence is checked against stored source records before it is shown. The counts are computed from the stored
                recordings; the audit chain is the hash chain of the stored audit trail.
              </p>
            )}
          </>
        ) : (
          <span className="text-ink-2">Loading stored counts…</span>
        )}
      </div>
    </header>
  )
}
