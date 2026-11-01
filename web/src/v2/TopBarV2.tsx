// The one top bar of the v2 layout: menu, logo, search, alert bell (real alerts only, with a separate link to the
// simulated devices), Feedback and the theme switch.
import type { AlertItem } from '../dashboard'
import { Icon } from '../icons'
import { AlertBell } from '../components/AlertBell'
import { nextQuick, themeLabel, type ThemeId } from './theme'

const QUICK_ICON = { system: 'auto', light: 'sun', dark: 'moon' } as const

export const BELL_NOTE =
  'Real FDA alerts only: the AI device sweep and the stored demo-snapshot brief. Signals for a person to review. Simulated devices are listed under Our devices.'

export function TopBarV2({
  sidebarOpen,
  onToggleSidebar,
  onHome,
  onSearch,
  alerts,
  onAlert,
  onViewAll,
  devicesLabel,
  devicesToReview,
  onDevices,
  onFeedback,
  theme,
  onTheme,
}: {
  sidebarOpen: boolean
  onToggleSidebar: () => void
  onHome: () => void
  onSearch: () => void
  /** Real alerts only. */
  alerts: AlertItem[]
  onAlert: (a: AlertItem) => void
  onViewAll: () => void
  devicesLabel: string
  devicesToReview: number
  onDevices: () => void
  onFeedback: () => void
  theme: ThemeId
  onTheme: (t: ThemeId) => void
}) {
  const quick = theme === 'system' || theme === 'light' || theme === 'dark' ? theme : null
  const next = nextQuick(quick ?? 'dark')
  return (
    <header className="ms2-topbar" data-testid="topbar-v2">
      <button
        type="button"
        className="ws-icon-btn"
        onClick={onToggleSidebar}
        aria-label={sidebarOpen ? 'Hide the sidebar' : 'Show the sidebar'}
        aria-controls="sidebar"
        aria-expanded={sidebarOpen}
        data-testid="sidebar-toggle"
      >
        <Icon name={sidebarOpen ? 'sidebarOpen' : 'sidebarShut'} />
      </button>
      <a
        href="./"
        className="t-wordmark mr-auto min-w-0 truncate pl-1 no-underline"
        style={{ fontSize: 21, color: 'var(--ink)' }}
        onClick={(e) => {
          e.preventDefault()
          onHome()
        }}
        aria-label="MaudeSignal, Home"
      >
        MaudeSignal
      </a>
      <button type="button" className="ws-icon-btn" onClick={onSearch} aria-label="Search chats and pages (Ctrl or Cmd K)" aria-keyshortcuts="Control+K Meta+K" data-testid="top-search">
        <Icon name="search" />
        <span className="ms2-hide-sm text-[15px]">Search</span>
      </button>
      <AlertBell
        items={alerts}
        onOpen={onAlert}
        onViewAll={() => onViewAll()}
        note={BELL_NOTE}
        extra={(close) => (
          <section aria-label={devicesLabel} className="ms2-bell-sim" data-testid="bell-simulated">
            <button
              type="button"
              className="ms2-row"
              onClick={() => {
                close()
                onDevices()
              }}
            >
              <span>
                <span className="font-medium">{devicesLabel}</span>
                <span className="ms2-muted"> · </span>
                <span className="ms-num">{devicesToReview}</span> to review
                <span className="ms2-muted block text-[15px]">Separate from the real alerts.</span>
              </span>
              <Icon name="chevron" size={18} />
            </button>
          </section>
        )}
      />
      <button type="button" className="ws-icon-btn" onClick={onFeedback} aria-haspopup="dialog" aria-label="Give feedback" data-testid="top-feedback">
        <Icon name="chat" />
        <span className="ms2-hide-sm text-[15px]">Feedback</span>
      </button>
      <button
        type="button"
        className="ws-icon-btn"
        onClick={() => onTheme(next)}
        aria-label={`Theme: ${themeLabel(theme)}. Switch to ${themeLabel(next)}`}
        title={`Theme: ${themeLabel(theme)}`}
        data-testid="top-theme"
      >
        <Icon name={quick ? QUICK_ICON[quick] : 'auto'} />
      </button>
    </header>
  )
}
