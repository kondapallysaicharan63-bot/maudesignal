// Ctrl/Cmd K (v2): one search over saved chats (titles and text) and the pages of the workspace.
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { Icon } from '../icons'
import type { WorkflowDef, WorkflowId } from '../types'
import { searchChats, type SavedChat } from './chatStore'
import type { Route } from './router'
import { CONNECT_TAB_LABELS, DEVICES_TAB_LABELS, EVIDENCE_TAB_LABELS, SIGNALS_TAB_LABELS } from './Sections'

export type SearchItem =
  | { kind: 'chat'; id: string; title: string; snippet: string }
  | { kind: 'page'; key: string; title: string; hint: string; route: Route }
  | { kind: 'workflow'; key: string; title: string; hint: string; id: WorkflowId }

/** Every page the palette can open, in sidebar order. */
export function pageItems(workflows: WorkflowDef[], devicesTitle = 'Our devices (simulated)'): SearchItem[] {
  const out: SearchItem[] = [{ kind: 'page', key: 'home', title: 'Home', hint: 'Page', route: { page: 'home' } }]
  for (const t of SIGNALS_TAB_LABELS) out.push({ kind: 'page', key: `s-${t.id}`, title: `Signals · ${t.label}`, hint: 'Page', route: { page: 'signals', tab: t.id } })
  for (const t of DEVICES_TAB_LABELS) out.push({ kind: 'page', key: `d-${t.id}`, title: `${devicesTitle} · ${t.label}`, hint: 'Page', route: { page: 'devices', tab: t.id } })
  for (const t of EVIDENCE_TAB_LABELS) out.push({ kind: 'page', key: `e-${t.id}`, title: `Evidence · ${t.label}`, hint: 'Page', route: { page: 'evidence', tab: t.id } })
  for (const t of CONNECT_TAB_LABELS) out.push({ kind: 'page', key: `c-${t.id}`, title: `Connect · ${t.label}`, hint: 'Page', route: { page: 'connect', tab: t.id } })
  for (const w of workflows) out.push({ kind: 'workflow', key: `w-${w.id}`, title: w.title, hint: 'Workflow', id: w.id })
  return out
}

/** Chats first (title, then text matches), then pages whose name matches. */
export function searchAll(query: string, chats: SavedChat[], pages: SearchItem[]): SearchItem[] {
  const q = query.trim().toLowerCase()
  const chatHits: SearchItem[] = searchChats(chats, q)
    .slice(0, q ? 20 : 8)
    .map((h) => ({ kind: 'chat', id: h.chat.id, title: h.chat.title, snippet: h.snippet }))
  const pageHits = q ? pages.filter((p) => p.title.toLowerCase().includes(q)) : pages
  return [...chatHits, ...pageHits]
}

export function SearchPalette({
  open,
  onClose,
  chats,
  pages,
  onPick,
}: {
  open: boolean
  onClose: () => void
  chats: SavedChat[]
  pages: SearchItem[]
  onPick: (item: SearchItem) => void
}) {
  const [q, setQ] = useState('')
  const [idx, setIdx] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  const back = useRef<HTMLElement | null>(null)
  const listId = useId()
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  const items = useMemo(() => searchAll(q, chats, pages), [q, chats, pages])
  useEffect(() => {
    if (!open) return
    const el = document.activeElement
    back.current = el instanceof HTMLElement ? el : null
    setQ('')
    setIdx(0)
    const t = window.setTimeout(() => input.current?.focus(), 0)
    // Escape closes this dialog only (the top-most layer), even before the input has focus; nothing under it sees it.
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopImmediatePropagation()
        onCloseRef.current()
      }
    }
    window.addEventListener('keydown', esc, true)
    return () => {
      window.clearTimeout(t)
      window.removeEventListener('keydown', esc, true)
      back.current?.focus?.()
    }
  }, [open])
  useEffect(() => {
    document.getElementById(`${listId}-${idx}`)?.scrollIntoView?.({ block: 'nearest' })
  }, [idx, listId])
  if (!open) return null
  const pick = (i: number) => {
    const it = items[i]
    if (!it) return
    onClose()
    onPick(it)
  }
  const firstPage = items.findIndex((i) => i.kind !== 'chat')
  return (
    <div className="ws-scrim z-[70] flex items-start justify-center px-3 pt-[10vh]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Search chats and pages"
        className="ms2-palette"
        onKeyDown={(e) => {
          if (e.key === 'Tab') {
            // Focus stays in the dialog: the search box is its one control (results are picked with the arrows).
            e.preventDefault()
            input.current?.focus()
          } else if (e.key === 'ArrowDown') {
            e.preventDefault()
            setIdx((i) => Math.min(i + 1, items.length - 1))
          } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            setIdx((i) => Math.max(i - 1, 0))
          } else if (e.key === 'Enter') {
            e.preventDefault()
            pick(idx)
          }
        }}
      >
        <div className="flex items-center gap-2 border-b border-rule px-3">
          <Icon name="search" />
          <input
            ref={input}
            value={q}
            onChange={(e) => {
              setQ(e.target.value)
              setIdx(0)
            }}
            placeholder="Search chats and pages"
            aria-label="Search chats and pages"
            role="combobox"
            aria-expanded="true"
            aria-controls={listId}
            aria-activedescendant={items[idx] ? `${listId}-${idx}` : undefined}
            aria-autocomplete="list"
            className="h-12 min-w-0 flex-1 bg-transparent text-[16px] text-ink placeholder:text-ink-2 focus:outline-none"
            data-testid="search-input"
          />
          <kbd className="ms2-kbd">Esc</kbd>
        </div>
        <ul id={listId} role="listbox" aria-label="Results" className="m-0 max-h-[60vh] list-none overflow-y-auto p-1" data-testid="search-results">
          {items.map((it, i) => (
            <li
              key={it.kind === 'chat' ? `chat-${it.id}` : it.key}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === idx}
              className={['ms2-option', i === idx ? 'is-active' : ''].join(' ')}
              onMouseEnter={() => setIdx(i)}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => pick(i)}
              data-testid={it.kind === 'chat' ? 'search-chat' : 'search-page'}
            >
              {(i === 0 && it.kind === 'chat') || i === firstPage ? (
                <span className="ms2-option-group">{it.kind === 'chat' ? 'Chats' : 'Pages'}</span>
              ) : null}
              <span className="block truncate font-medium" title={it.title}>
                {it.title}
              </span>
              {it.kind === 'chat' ? (
                it.snippet && <span className="ms2-muted block truncate text-[14px]">{it.snippet}</span>
              ) : (
                <span className="ms2-muted block text-[14px]">{it.hint}</span>
              )}
            </li>
          ))}
          {items.length === 0 && <li className="px-3 py-3 text-ink-2">Nothing matches.</li>}
        </ul>
      </div>
    </div>
  )
}
