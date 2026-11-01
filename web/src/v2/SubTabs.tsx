import { useId, useRef, type KeyboardEvent, type ReactNode } from 'react'

export interface TabDef<T extends string> {
  id: T
  label: string
}

/** How a tab was chosen: a click or the "View" menu (a new history entry), or arrow keys (the entry is replaced). */
export type TabHow = 'click' | 'key'

/** Where arrow keys, Home and End move in a row of n tabs (wraps round); null for any other key. */
export function tabMove(key: string, i: number, n: number): number | null {
  if (n <= 0) return null
  if (key === 'ArrowRight' || key === 'ArrowDown') return (i + 1) % n
  if (key === 'ArrowLeft' || key === 'ArrowUp') return (i - 1 + n) % n
  if (key === 'Home') return 0
  if (key === 'End') return n - 1
  return null
}

/**
 * ARIA tabs: one panel open at a time. Arrow keys move and open (automatic activation); only the open tab is in the
 * Tab order. Each tab is an address, so the panel can be linked to and Back returns to the previous tab. Below 480 px
 * the row becomes one "View" menu, so every tab is reachable without a clipped row.
 */
export function SubTabs<T extends string>({
  id,
  label,
  tabs,
  value,
  onChange,
  children,
}: {
  /** Prefix for element ids (unique per page). */
  id: string
  label: string
  tabs: readonly TabDef<T>[]
  value: T
  onChange: (t: T, how: TabHow) => void
  children: ReactNode
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const selectId = useId()
  const onKey = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const j = tabMove(e.key, i, tabs.length)
    if (j === null) return
    e.preventDefault()
    onChange(tabs[j].id, 'key')
    refs.current[j]?.focus()
  }
  return (
    <>
      <div className="ms2-viewpick">
        <label htmlFor={selectId}>View</label>
        <select id={selectId} value={value} onChange={(e) => onChange(e.target.value as T, 'click')} data-testid={`${id}-viewpick`}>
          {tabs.map((t) => (
            <option key={t.id} value={t.id}>
              {t.label}
            </option>
          ))}
        </select>
      </div>
      <div role="tablist" aria-label={label} className="ms2-tabs" data-testid={`${id}-tabs`}>
        {tabs.map((t, i) => {
          const on = t.id === value
          return (
            <button
              key={t.id}
              ref={(el) => {
                refs.current[i] = el
              }}
              type="button"
              role="tab"
              id={`${id}-tab-${t.id}`}
              aria-selected={on}
              aria-controls={`${id}-panel`}
              tabIndex={on ? 0 : -1}
              className="ms2-tab"
              onClick={() => onChange(t.id, 'click')}
              onKeyDown={(e) => onKey(e, i)}
              data-testid={`tab-${t.id}`}
            >
              {t.label}
            </button>
          )
        })}
      </div>
      <div role="tabpanel" id={`${id}-panel`} aria-labelledby={`${id}-tab-${value}`} className="ms2-tabpanel" tabIndex={0}>
        {children}
      </div>
    </>
  )
}
