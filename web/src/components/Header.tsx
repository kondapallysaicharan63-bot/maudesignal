import { Icon } from '../icons'
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
  /** Opens the thread holding the first withheld sentence (omitted when none is stored). */
  onWithheld?: () => void
}

const THEME_ICON = { system: 'auto', light: 'sun', dark: 'moon' } as const
const THEME_NEXT = { system: 'light', light: 'dark', dark: 'system' } as const

export function Header(p: Props) {
  const h = p.manifest?.header
  return (
    <header className="shrink-0 border-b border-rule bg-paper">
      <div className="flex h-14 items-center gap-1 px-2 md:px-3">
        <button
          className="ws-icon-btn"
          onClick={p.onToggleSidebar}
          aria-label="Toggle sidebar"
          aria-controls="sidebar"
          aria-expanded={p.sidebarOpen}
        >
          <Icon name="sidebar" />
        </button>
        <span className="t-wordmark mr-auto pl-1" style={{ fontSize: 22 }}>
          MaudeSignal
        </span>
        <button className="ws-icon-btn" onClick={p.onPalette} aria-label="Search workflows (Ctrl or Cmd K)">
          <Icon name="search" />
          <span className="hidden text-[15px] md:inline">Search</span>
          <kbd className="ms-code hidden rounded-xs border border-rule px-1 md:inline">Ctrl K</kbd>
        </button>
        <button
          className="ws-icon-btn"
          onClick={p.onFeedback}
          aria-haspopup="dialog"
          aria-label="Give feedback"
        >
          <Icon name="chat" />
          <span className="text-[15px]">Feedback</span>
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
      <div
        className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-rule bg-sunk px-3 py-2 text-[15px] md:px-4"
        role="status"
      >
        {h ? (
          <>
            <span className="ws-wrap">
              Every sentence checked against stored source records ·{' '}
              <strong className="ms-num">{h.claims_verified}</strong> claims verified ·{' '}
              {p.onWithheld && h.sentences_withheld > 0 ? (
                <button
                  type="button"
                  onClick={p.onWithheld}
                  className="inline-flex min-h-8 items-center rounded-xs border border-rule-strong bg-surface px-2 font-semibold text-ink underline decoration-dotted underline-offset-4 hover:bg-paper"
                  aria-label={`${h.sentences_withheld} ${h.sentences_withheld === 1 ? 'sentence' : 'sentences'} withheld: open the withheld sentence`}
                >
                  <span className="ms-num">{h.sentences_withheld}</span>&nbsp;
                  {h.sentences_withheld === 1 ? 'sentence' : 'sentences'} withheld
                </button>
              ) : (
                <>
                  <strong className="ms-num">{h.sentences_withheld}</strong>{' '}
                  {h.sentences_withheld === 1 ? 'sentence' : 'sentences'} withheld
                </>
              )}
            </span>
            {h.audit_chain_ok ? (
              <span className="ms-chip ms-chip--ok">
                <Icon name="check" size={14} /> Audit verified
              </span>
            ) : (
              <span className="ms-chip ms-chip--high">Audit chain not verified</span>
            )}
          </>
        ) : (
          <span className="text-ink-3">Loading stored counts…</span>
        )}
      </div>
    </header>
  )
}
