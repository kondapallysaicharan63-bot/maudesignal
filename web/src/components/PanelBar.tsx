import { Icon } from '../icons'
import { PANEL_NAME, type PanelId } from '../layout'

/** Expand a panel to full screen, or collapse it back (Esc does the same). */
export function ExpandButton({ panel, expanded, onToggle }: { panel: PanelId; expanded: boolean; onToggle: () => void }) {
  const name = PANEL_NAME[panel]
  return (
    <button
      type="button"
      className="ws-icon-btn"
      onClick={onToggle}
      aria-pressed={expanded}
      aria-label={expanded ? `Collapse ${name} (Esc)` : `Expand ${name} to full screen`}
      title={expanded ? 'Collapse (Esc)' : 'Expand to full screen'}
      data-testid={`expand-${panel}`}
    >
      <Icon name={expanded ? 'collapse' : 'expand'} size={18} />
      <span className="hidden text-[15px] sm:inline">{expanded ? 'Collapse' : 'Expand'}</span>
    </button>
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
    <div className="flex shrink-0 items-center justify-between border-b border-rule px-4 py-1">
      <h2 className="m-0 text-[16px] font-semibold">{title}</h2>
      <ExpandButton panel={panel} expanded={expanded} onToggle={onToggle} />
    </div>
  )
}
