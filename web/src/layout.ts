// Which panel is shown full screen. One at a time; Esc or the same button brings it back.
export type PanelId = 'main' | 'mini' | 'artifacts'

export const toggleExpanded = (cur: PanelId | null, p: PanelId): PanelId | null => (cur === p ? null : p)

/** Esc collapses an expanded panel and leaves everything else alone. */
export const collapseOnEscape = (cur: PanelId | null, key: string): PanelId | null => (key === 'Escape' ? null : cur)

export const PANEL_NAME: Record<PanelId, string> = {
  main: 'chat',
  mini: 'dashboard',
  artifacts: 'artifacts',
}

/** Classes that lift a panel over the whole page. */
export const FULLSCREEN = 'fixed inset-0 z-50 h-full w-full max-w-none'
