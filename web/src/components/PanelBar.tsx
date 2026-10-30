import { createContext, useContext } from 'react'
import { Icon } from '../icons'
import { PANEL_NAME, type PanelId } from '../layout'

/** Where "Home" goes and what the current workflow is called, for the trail shown on an expanded panel. */
export const PanelNav = createContext<{ onHome: () => void; workflow: string | null }>({ onHome: () => undefined, workflow: null })

/**
 * Expand a panel to full screen, or collapse it back (Esc and the browser's back button do the same).
 * When expanded it is a labelled "Back" button (44px high) so the way out is never a bare icon.
 */
export function ExpandButton({
  panel,
  expanded,
  onToggle,
  iconOnly = false,
}: {
  panel: PanelId
  expanded: boolean
  onToggle: () => void
  iconOnly?: boolean
}) {
  const name = PANEL_NAME[panel]
  return (
    <button
      type="button"
      className={['ws-icon-btn min-h-11', expanded ? 'border-rule-strong bg-surface px-3' : ''].join(' ')}
      onClick={onToggle}
      aria-pressed={expanded}
      aria-label={expanded ? `Back: collapse ${name} (Esc)` : `Expand ${name} to full screen`}
      title={expanded ? 'Back (Esc)' : 'Expand to full screen'}
      data-testid={`expand-${panel}`}
    >
      <Icon name={expanded ? 'back' : 'expand'} size={18} />
      {expanded ? (
        <span className="text-[17px] font-semibold">Back</span>
      ) : (
        !iconOnly && <span className="hidden text-[17px] sm:inline">Expand</span>
      )}
    </button>
  )
}

/** Trail "Home > workflow > panel" shown on an expanded panel; Home is a link back to the dashboard. */
export function Crumbs({ panel }: { panel: PanelId }) {
  const { onHome, workflow } = useContext(PanelNav)
  return (
    <nav aria-label="Breadcrumb" className="min-w-0 flex-1 truncate text-[17px] text-ink-2">
      <button type="button" className="min-h-11 px-1 font-semibold text-accent underline" onClick={onHome}>
        Home
      </button>
      {workflow && (
        <>
          <span aria-hidden="true"> › </span>
          <span>{workflow}</span>
        </>
      )}
      <span aria-hidden="true"> › </span>
      <span className="font-semibold text-ink" aria-current="page">
        {PANEL_NAME[panel][0].toUpperCase() + PANEL_NAME[panel].slice(1)}
      </span>
    </nav>
  )
}

/** Thin title row above a panel's content with its expand/collapse button. */
export function PanelBar({
  title,
  panel,
  expanded,
  onToggle,
}: {
  title: string
  panel: PanelId
  expanded: boolean
  onToggle: () => void
}) {
  return (
    <div className="flex shrink-0 items-center justify-between gap-2 border-b border-rule px-4 py-1">
      {expanded ? <Crumbs panel={panel} /> : <h2 className="m-0 text-[17px] font-semibold">{title}</h2>}
      <ExpandButton panel={panel} expanded={expanded} onToggle={onToggle} />
    </div>
  )
}
