// One theme control for the v2 layout: the same small menu opens from the top bar and from the sidebar.
import { useEffect, useRef, useState } from 'react'
import { Icon } from '../icons'
import { THEMES, themeLabel, type ThemeId } from './theme'

const ICON: Partial<Record<ThemeId, 'sun' | 'moon' | 'auto'>> = { light: 'sun', dark: 'moon' }

export function ThemeMenu({
  theme,
  onTheme,
  placement,
  testid,
  showLabel = false,
}: {
  theme: ThemeId
  onTheme: (t: ThemeId) => void
  placement: 'down' | 'up'
  testid: string
  /** Sidebar: a plain row "Theme: Paper (light)"; top bar: the icon only. */
  showLabel?: boolean
}) {
  const [open, setOpen] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  const btn = useRef<HTMLButtonElement>(null)
  const items = useRef<(HTMLButtonElement | null)[]>([])
  useEffect(() => {
    if (!open) return
    const i = Math.max(0, THEMES.findIndex((t) => t.id === theme))
    window.setTimeout(() => items.current[i]?.focus(), 0)
    const down = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false)
    }
    // Escape closes this menu only (the top-most layer), not the drawer or a dialog under it.
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopImmediatePropagation()
        e.preventDefault()
        setOpen(false)
        btn.current?.focus()
      }
    }
    window.addEventListener('mousedown', down)
    window.addEventListener('keydown', key, true)
    return () => {
      window.removeEventListener('mousedown', down)
      window.removeEventListener('keydown', key, true)
    }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="ms2-thememenu" ref={wrap}>
      <button
        ref={btn}
        type="button"
        className={showLabel ? 'ms2-siderow' : 'ws-icon-btn'}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Theme: ${themeLabel(theme)}. Choose a theme`}
        onClick={() => setOpen((o) => !o)}
        data-testid={testid}
      >
        <Icon name={ICON[theme] ?? 'auto'} size={showLabel ? 18 : 22} />
        {showLabel && <span>Theme: {themeLabel(theme)}</span>}
      </button>
      {open && (
        <ul
          role="menu"
          aria-label="Theme"
          data-popover-open
          className={['ms2-menu ms2-menu--theme', placement === 'up' ? 'is-up' : 'is-down'].join(' ')}
          onKeyDown={(e) => {
            const i = items.current.findIndex((el) => el === document.activeElement)
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
              e.preventDefault()
              const n = THEMES.length
              items.current[(i + (e.key === 'ArrowDown' ? 1 : n - 1)) % n]?.focus()
            }
          }}
        >
          {THEMES.map((t, i) => (
            <li role="none" key={t.id}>
              <button
                ref={(el) => {
                  items.current[i] = el
                }}
                type="button"
                role="menuitemradio"
                aria-checked={t.id === theme}
                onClick={() => {
                  onTheme(t.id)
                  setOpen(false)
                  btn.current?.focus()
                }}
                data-testid={`theme-${t.id}`}
              >
                <span className="ms2-check" aria-hidden="true">
                  {t.id === theme ? '✓' : ''}
                </span>
                {t.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
