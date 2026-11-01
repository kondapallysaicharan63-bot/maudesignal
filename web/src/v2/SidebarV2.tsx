// The v2 sidebar, top to bottom: New chat, Search, Home, Signals, Our devices, Evidence, Connect, Recents; at the bottom
// the theme menu and one small link to the schedules and sources. A drawer below 768 px.
import { useEffect, useRef, useState } from 'react'
import { Icon } from '../icons'
import type { SavedChat } from './chatStore'
import type { Section } from './router'
import { ThemeMenu } from './ThemeMenu'
import type { ThemeId } from './theme'

export const SAVED_NOTE = 'Saved on this device only'
export const NOT_SAVED_NOTE = 'Not saved: browser storage is full or blocked'

export type NavId = 'home' | Section

interface Props {
  open: boolean
  collapsed: boolean
  active: NavId | null
  activeChat: string | null
  chats: SavedChat[]
  /** False when the browser refused to save (storage full or blocked). */
  saved: boolean
  /** The address of a saved chat (so a Recents row can open in a new tab). */
  chatHref: (id: string) => string
  devicesLabel: string
  devicesToReview: number
  theme: ThemeId
  onTheme: (t: ThemeId) => void
  onNewChat: () => void
  onSearch: () => void
  onNav: (n: NavId) => void
  onChat: (id: string) => void
  onRename: (id: string, title: string) => void
  onDelete: (id: string) => void
  onSchedules: () => void
  onClose: () => void
}

function RecentRow({
  c,
  href,
  active,
  onOpen,
  onRename,
  onDelete,
}: {
  c: SavedChat
  href: string
  active: boolean
  onOpen: () => void
  onRename: (t: string) => void
  onDelete: () => void
}) {
  const [mode, setMode] = useState<'idle' | 'menu' | 'rename' | 'confirm'>('idle')
  const [draft, setDraft] = useState(c.title)
  const input = useRef<HTMLInputElement>(null)
  const menuBtn = useRef<HTMLButtonElement>(null)
  const wrap = useRef<HTMLLIElement>(null)
  const finished = useRef(false)
  useEffect(() => {
    if (mode === 'rename') {
      finished.current = false
      setDraft(c.title)
      window.setTimeout(() => input.current?.select(), 0)
    }
  }, [mode]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (mode !== 'menu') return
    const down = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setMode('idle')
    }
    window.addEventListener('mousedown', down)
    return () => window.removeEventListener('mousedown', down)
  }, [mode])
  const done = (save: boolean) => {
    if (mode === 'rename') {
      if (finished.current) return
      finished.current = true
    }
    if (save && draft.trim() && draft.trim() !== c.title) onRename(draft)
    setMode('idle')
    window.setTimeout(() => menuBtn.current?.focus(), 0)
  }
  if (mode === 'rename')
    return (
      <li className="ms2-recent" ref={wrap}>
        <input
          ref={input}
          value={draft}
          maxLength={120}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              done(true)
            } else if (e.key === 'Escape') {
              e.preventDefault()
              e.stopPropagation()
              done(false)
            }
          }}
          onBlur={() => done(true)}
          aria-label="Chat name"
          className="ms2-rename"
          data-testid="rename-input"
        />
      </li>
    )
  if (mode === 'confirm')
    return (
      <li className="ms2-recent ms2-recent--confirm" ref={wrap} data-testid="delete-confirm">
        <p className="m-0 text-[15px]" id={`del-${c.id}`}>
          Delete “<span className="ms2-clip">{c.title}</span>”?
        </p>
        <div className="mt-1 flex gap-2">
          <button
            type="button"
            className="ms-btn ms-btn--secondary ms2-danger"
            style={{ height: 36 }}
            onClick={() => {
              setMode('idle')
              onDelete()
            }}
            aria-describedby={`del-${c.id}`}
            data-testid="delete-yes"
            autoFocus
          >
            Delete
          </button>
          <button type="button" className="ms-btn ms-btn--secondary" style={{ height: 36 }} onClick={() => done(false)} data-testid="delete-no">
            Cancel
          </button>
        </div>
      </li>
    )
  return (
    <li className="ms2-recent" ref={wrap}>
      <a
        href={href}
        className="ms2-navitem ms2-recent-open"
        aria-current={active ? 'page' : undefined}
        onClick={(e) => {
          // A plain click opens the chat here; Ctrl / Cmd / Shift / middle click keep the browser's new tab or window.
          if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
          e.preventDefault()
          onOpen()
        }}
        title={c.title}
        data-testid="recent-chat"
      >
        <span className="ms2-clip">{c.title}</span>
      </a>
      <button
        ref={menuBtn}
        type="button"
        className="ms2-recent-more"
        aria-label={`Options for ${c.title}`}
        aria-haspopup="menu"
        aria-expanded={mode === 'menu'}
        onClick={() => setMode((m) => (m === 'menu' ? 'idle' : 'menu'))}
        data-testid="recent-more"
      >
        <Icon name="more" size={18} />
      </button>
      {mode === 'menu' && (
        <ul
          role="menu"
          aria-label={`Options for ${c.title}`}
          className="ms2-menu"
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.stopPropagation()
              setMode('idle')
              menuBtn.current?.focus()
            }
          }}
        >
          <li role="none">
            <button type="button" role="menuitem" autoFocus onClick={() => setMode('rename')} data-testid="recent-rename">
              Rename
            </button>
          </li>
          <li role="none">
            <button type="button" role="menuitem" onClick={() => setMode('confirm')} data-testid="recent-delete">
              Delete
            </button>
          </li>
        </ul>
      )}
    </li>
  )
}

export function SidebarV2(p: Props) {
  const closeRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!p.open) return
    if (window.matchMedia('(max-width: 767px)').matches) closeRef.current?.focus()
    const phone = window.matchMedia('(max-width: 767px)').matches
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !document.querySelector('[data-popover-open]')) p.onClose()
      // Phone drawer: Tab and Shift+Tab go round inside it (the page behind is inert as well).
      if (e.key === 'Tab' && phone) {
        const aside = document.getElementById('sidebar')
        if (!aside) return
        const f = Array.from(aside.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input, select, [tabindex="0"]')).filter(
          (el) => el.offsetParent !== null,
        )
        if (f.length === 0) return
        const first = f[0]
        const last = f[f.length - 1]
        const at = document.activeElement
        if (e.shiftKey && (at === first || !aside.contains(at))) {
          e.preventDefault()
          last.focus()
        } else if (!e.shiftKey && (at === last || !aside.contains(at))) {
          e.preventDefault()
          first.focus()
        }
      }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [p.open]) // eslint-disable-line react-hooks/exhaustive-deps
  const nav: { id: NavId; label: string; icon: Parameters<typeof Icon>[0]['name']; badge?: string }[] = [
    { id: 'home', label: 'Home', icon: 'panel' },
    { id: 'signals', label: 'Signals', icon: 'bell' },
    { id: 'devices', label: p.devicesLabel, icon: 'lock', badge: p.devicesToReview > 0 ? `${p.devicesToReview}` : undefined },
    { id: 'evidence', label: 'Evidence', icon: 'check' },
    { id: 'connect', label: 'Connect', icon: 'plug' },
  ]
  return (
    <>
      {p.open && <div className="ws-scrim z-30 md:hidden" onClick={p.onClose} aria-hidden="true" data-testid="drawer-scrim" />}
      <aside
        id="sidebar"
        aria-label="Workspace"
        className={['ms2-sidebar', p.open ? 'is-open' : '', p.collapsed ? 'is-collapsed' : ''].join(' ')}
        data-testid="sidebar-v2"
      >
        <div className="flex items-center justify-between px-3 pt-3 md:hidden">
          <span className="t-wordmark" style={{ fontSize: 20 }}>
            MaudeSignal
          </span>
          <button ref={closeRef} className="ws-icon-btn min-h-11 min-w-11" onClick={p.onClose} aria-label="Close menu">
            <Icon name="close" />
          </button>
        </div>
        <div className="space-y-0.5 px-2 pt-3">
          <button type="button" className="ms2-navitem ms2-newchat" onClick={p.onNewChat} data-testid="new-chat">
            <Icon name="plus" size={18} />
            <span className="ms2-clip">New chat</span>
          </button>
          <button type="button" className="ms2-navitem" onClick={p.onSearch} aria-keyshortcuts="Control+K Meta+K" data-testid="side-search">
            <Icon name="search" size={18} />
            <span className="ms2-clip">Search</span>
            <kbd className="ms2-kbd ml-auto">Ctrl K</kbd>
          </button>
        </div>
        <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-3" aria-label="Sections">
          <ul className="m-0 mt-2 list-none space-y-0.5 p-0">
            {nav.map((n) => (
              <li key={n.id}>
                <button
                  type="button"
                  className="ms2-navitem"
                  aria-current={p.active === n.id ? 'page' : undefined}
                  onClick={() => p.onNav(n.id)}
                  title={n.badge ? `${n.label} · ${n.badge} to review` : n.label}
                  data-testid={`nav-${n.id}`}
                >
                  <Icon name={n.icon} size={18} />
                  <span className="ms2-clip">{n.label}</span>
                  {n.badge && (
                    <span className="ms2-badge" data-testid={`badge-${n.id}`}>
                      {n.badge}
                      <span className="sr-only"> to review</span>
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
          <h2 className="ms2-side-h">Recents</h2>
          <p className={['ms2-side-note', p.saved ? '' : 'is-bad'].join(' ')} data-testid="saved-note" role={p.saved ? undefined : 'status'}>
            {p.saved ? SAVED_NOTE : NOT_SAVED_NOTE}
          </p>
          {p.chats.length === 0 ? (
            <p className="ms2-side-note">No saved chats yet.</p>
          ) : (
            <ul className="m-0 list-none space-y-0.5 p-0" aria-label="Recent chats" data-testid="recents">
              {p.chats.map((c) => (
                <RecentRow
                  key={c.id}
                  c={c}
                  href={p.chatHref(c.id)}
                  active={p.activeChat === c.id}
                  onOpen={() => p.onChat(c.id)}
                  onRename={(t) => p.onRename(c.id, t)}
                  onDelete={() => p.onDelete(c.id)}
                />
              ))}
            </ul>
          )}
        </nav>
        <div className="ms2-side-foot">
          <ThemeMenu theme={p.theme} onTheme={p.onTheme} placement="up" testid="side-theme" showLabel />
          <button type="button" className="ms2-siderow" onClick={p.onSchedules} data-testid="schedules-link">
            <Icon name="info" size={18} />
            Schedules and sources
          </button>
        </div>
      </aside>
    </>
  )
}
