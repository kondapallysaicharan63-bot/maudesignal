// The one top bar of the v2 layout: menu, logo, search, alert bell (real alerts only, with a separate link to the
// simulated devices) and Feedback. The theme is chosen in one place, the sidebar.
import type { AlertItem } from '../dashboard'
import { Icon } from '../icons'
import { AlertBell } from '../components/AlertBell'

export const BELL_NOTE =
  'Real FDA alerts only: the AI device sweep and the stored demo-snapshot brief. Signals for a person to review. Simulated devices are listed under Our devices.'

export function TopBarV2({
  desktop,
  homeHref,
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
}: {
  /** From 768 px: the sidebar sits beside the page (the Search here is for phones only). */
  desktop: boolean
  homeHref: string
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
}) {
  return (
    <header className="ms2-topbar" data-testid="topbar-v2">
      <button
        type="button"
        className="ws-icon-btn"
        onClick={onToggleSidebar}
        aria-label={desktop ? (sidebarOpen ? 'Hide the sidebar' : 'Show the sidebar') : 'Menu'}
        title={desktop ? (sidebarOpen ? 'Hide the sidebar' : 'Show the sidebar') : 'Menu'}
        aria-controls="sidebar"
        aria-expanded={sidebarOpen}
        data-testid="sidebar-toggle"
      >
        <Icon name={sidebarOpen ? 'sidebarOpen' : 'sidebarShut'} />
      </button>
      <a
        href={homeHref}
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
      {!desktop && (
        <button type="button" className="ws-icon-btn" onClick={onSearch} aria-label="Search chats and pages" title="Search chats and pages" data-testid="top-search">
          <Icon name="search" />
        </button>
      )}
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
      <button type="button" className="ws-icon-btn" onClick={onFeedback} aria-haspopup="dialog" aria-label="Give feedback" title="Give feedback" data-testid="top-feedback">
        <Icon name="chat" />
        <span className="ms2-hide-sm text-[15px]">Feedback</span>
      </button>
    </header>
  )
}
