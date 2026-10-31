// The "+" button at the left of the message box and its one menu (WAI-ARIA menu button pattern):
// Enter, Space or Arrow Down open it on the first item, Arrow Up on the last; arrows, Home and End move; Escape closes and
// returns focus to the button; Tab closes; a click outside closes. Checkbox items show their state (aria-checked).
import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { Icon, type IconName } from '../icons'

export interface MenuItem {
  id: string
  label: string
  icon: IconName
  /** A second line under the label. */
  hint?: string
  /** An on/off item (role menuitemcheckbox). */
  checked?: boolean
  onSelect: () => void
}

/** Next index for a menu key, wrapping at both ends; null for keys the menu does not handle. */
export function menuMove(key: string, i: number, n: number): number | null {
  if (n <= 0) return null
  if (key === 'ArrowDown') return (i + 1) % n
  if (key === 'ArrowUp') return (i - 1 + n) % n
  if (key === 'Home') return 0
  if (key === 'End') return n - 1
  return null
}

export function PlusMenu({ items, disabled = false }: { items: MenuItem[]; disabled?: boolean }) {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const btn = useRef<HTMLButtonElement>(null)
  const wrap = useRef<HTMLDivElement>(null)
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const menuId = useId()

  const close = useCallback((refocus: boolean) => {
    setOpen(false)
    if (refocus) btn.current?.focus()
  }, [])

  const openAt = (i: number) => {
    setActive(i)
    setOpen(true)
  }

  // Focus follows the active item while open.
  useEffect(() => {
    if (open) refs.current[active]?.focus()
  }, [open, active])

  // A press outside the menu and its button closes it (focus stays where the person put it).
  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent | MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const choose = (it: MenuItem) => {
    close(true)
    it.onSelect()
  }

  return (
    <div ref={wrap} className="relative shrink-0">
      <button
        ref={btn}
        type="button"
        className={['ws-icon-btn min-h-11 min-w-11 !rounded-sm border !border-rule-strong', open ? '!bg-sunk !text-ink' : ''].join(' ')}
        aria-label="Add a photo, a sample label or a voice question"
        title="Add a photo, a sample label or a voice question"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        disabled={disabled}
        data-testid="composer-plus"
        onClick={() => (open ? close(false) : openAt(0))}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            openAt(0)
          } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            openAt(items.length - 1)
          } else if (e.key === 'Escape' && open) {
            e.stopPropagation()
            close(true)
          }
        }}
      >
        <Icon name="plus" size={22} />
      </button>
      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label="Add to your message"
          aria-orientation="vertical"
          data-testid="composer-menu"
          className="absolute bottom-full left-0 z-50 mb-2 w-[min(20rem,calc(100vw-2rem))] rounded-md border border-rule-strong bg-surface p-1 shadow-[var(--shadow-pop)]"
          onKeyDown={(e) => {
            const next = menuMove(e.key, active, items.length)
            if (next !== null) {
              e.preventDefault()
              setActive(next)
            } else if (e.key === 'Escape') {
              e.preventDefault()
              e.stopPropagation()
              close(true)
            } else if (e.key === 'Tab') {
              setOpen(false)
            }
          }}
        >
          {items.map((it, i) => {
            const check = it.checked !== undefined
            return (
              <button
                key={it.id}
                ref={(el) => {
                  refs.current[i] = el
                }}
                type="button"
                role={check ? 'menuitemcheckbox' : 'menuitem'}
                aria-checked={check ? it.checked : undefined}
                tabIndex={i === active ? 0 : -1}
                data-testid={`menu-${it.id}`}
                onClick={() => choose(it)}
                onMouseMove={() => i !== active && setActive(i)}
                className={[
                  'flex min-h-11 w-full items-center gap-3 rounded-xs px-3 py-2 text-left text-[16px] leading-snug text-ink focus-visible:!-outline-offset-2',
                  i === active ? 'bg-accent-soft shadow-[inset_4px_0_0_var(--accent)]' : 'hover:bg-sunk',
                ].join(' ')}
              >
                <span className="shrink-0 text-ink-2">
                  <Icon name={it.icon} size={20} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold">{it.label}</span>
                  {it.hint && <span className="ws-wrap block text-[15px] text-ink-2">{it.hint}</span>}
                </span>
                {check && (
                  <span
                    aria-hidden="true"
                    className={[
                      'inline-flex h-6 w-10 shrink-0 items-center rounded-sm border p-0.5',
                      it.checked ? 'justify-end border-accent bg-accent' : 'justify-start border-rule-strong bg-sunk',
                    ].join(' ')}
                  >
                    <span className={['block h-4 w-4 rounded-full', it.checked ? 'bg-surface' : 'bg-ink-2'].join(' ')} />
                  </span>
                )}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
