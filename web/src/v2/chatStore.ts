// Saved chats for the v2 layout. Kept in this browser only (localStorage), never sent to a server.
// Every read and write is wrapped: a private window or blocked site data leaves an empty list and the app works.
// Format: {"v": 1, "chats": [SavedChat]} under a versioned key; the list is capped by count and by size, oldest dropped.
import { useCallback, useEffect, useRef, useState } from 'react'
import { parseAsk, parseLabelResponse } from '../live/api'
import type { LiveTurn } from '../live/useLiveChat'

export const CHATS_KEY = 'ms-chats-v1'
/**
 * The answer format the saved turns were written in. A saved answer is read back through the same parser as a fresh
 * one (parseAsk / parseLabelResponse); bump this when the answer view needs a field older saves do not have, so they
 * are dropped instead of shown broken.
 */
export const ANSWER_FORMAT = 1
export const MAX_CHATS = 50
/** About 2 MB of JSON (one UTF-16 char counted as one byte; close enough for a cap). */
export const MAX_BYTES = 2_000_000
export const TITLE_MAX = 48
export const PENDING_NOTE = 'This question was still being answered when the chat was closed. Ask it again to get an answer.'

export interface SavedChat {
  id: string
  title: string
  /** True once the person renamed it; the first question no longer sets the title. */
  titleEdited?: boolean
  createdAt: number
  updatedAt: number
  turns: LiveTurn[]
}

interface Store {
  read: (key: string) => string | null
  /** False when the browser refused the write (storage full or blocked). */
  write: (key: string, value: string) => boolean | void
}

const browserStore: Store = {
  read: (k) => {
    try {
      return window.localStorage.getItem(k)
    } catch {
      return null
    }
  },
  write: (k, v) => {
    try {
      window.localStorage.setItem(k, v)
      return true
    } catch {
      return false // full or blocked: the chats stay in this page's memory only
    }
  },
}

/** "Which device types…" from the first question, cut at a word near 48 characters. */
export function autoTitle(turns: LiveTurn[]): string {
  for (const t of turns) {
    const q = (t.question ?? t.followUp ?? '').replace(/\s+/g, ' ').trim()
    if (q) return trimTitle(q)
    if (t.via === 'photo') return 'Photo of a device label'
  }
  return turns.some((t) => t.via === 'voice') ? 'Spoken question' : 'New chat'
}

export function trimTitle(s: string, max: number = TITLE_MAX): string {
  const one = s.replace(/\s+/g, ' ').trim()
  if (one.length <= max) return one
  const cut = one.slice(0, max)
  const sp = cut.lastIndexOf(' ')
  return `${(sp > max * 0.6 ? cut.slice(0, sp) : cut).trimEnd()}…`
}

/** A turn as it is kept: no object URL (it dies with the page), a pending turn says it was not answered. */
export function storableTurn(t: LiveTurn): LiveTurn {
  const out: LiveTurn = { ...t }
  delete out.image
  return out
}

function restoredTurn(t: LiveTurn): LiveTurn {
  if (t.status !== 'pending') return t
  return { ...t, status: 'error', error: PENDING_NOTE }
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)

const optStr = (v: unknown): v is string | undefined => v === undefined || typeof v === 'string'

/**
 * A saved turn rebuilt in exactly the shape the answer view reads, or null when it cannot be. Answers and label
 * readings go through the same parsers as a fresh API answer; the daily-limit count is never restored.
 */
export function restoreTurn(v: unknown): LiveTurn | null {
  if (!isObj(v) || typeof v.id !== 'number' || !Number.isFinite(v.id)) return null
  if (v.via !== 'text' && v.via !== 'voice' && v.via !== 'photo') return null
  if (v.status !== 'pending' && v.status !== 'done' && v.status !== 'error') return null
  if (!(v.question === null || v.question === undefined || typeof v.question === 'string')) return null
  if (!optStr(v.error) || !optStr(v.followUp)) return null
  const t: LiveTurn = { id: v.id, via: v.via, question: typeof v.question === 'string' ? v.question : null, status: v.status }
  if (typeof v.error === 'string') t.error = v.error
  if (typeof v.followUp === 'string') t.followUp = v.followUp
  if (v.offerRecordedVoice === true) t.offerRecordedVoice = true
  if (v.offerRecordedLabel === true) t.offerRecordedLabel = true
  if (v.resp !== undefined) {
    const resp = parseAsk(v.resp)
    if (!resp) return null
    t.resp = { ...resp, limits: null }
  }
  if (v.label !== undefined) {
    const label = parseLabelResponse(v.label)
    if (!label) return null
    t.label = { ...label, limits: null }
  }
  if (t.status === 'done' && (t.via === 'photo' ? !t.label : !t.resp)) return null
  if (t.status === 'error' && !t.error) t.error = PENDING_NOTE
  return t
}

function validChat(v: unknown): SavedChat | null {
  if (!isObj(v) || typeof v.id !== 'string' || !v.id || typeof v.title !== 'string' || !Array.isArray(v.turns)) return null
  const createdAt = typeof v.createdAt === 'number' ? v.createdAt : 0
  const updatedAt = typeof v.updatedAt === 'number' ? v.updatedAt : createdAt
  const turns = v.turns.map(restoreTurn).filter((t): t is LiveTurn => t !== null).map(restoredTurn)
  if (turns.length === 0) return null
  return { id: v.id, title: v.title, ...(v.titleEdited === true ? { titleEdited: true } : {}), createdAt, updatedAt, turns }
}

/** The saved chats, newest first. Unreadable or foreign data gives an empty list (never an error). */
export function parseChats(raw: string | null): SavedChat[] {
  if (!raw) return []
  try {
    const doc = JSON.parse(raw) as unknown
    if (!isObj(doc) || doc.v !== 1 || doc.fmt !== ANSWER_FORMAT || !Array.isArray(doc.chats)) return []
    const seen = new Set<string>()
    const out: SavedChat[] = []
    for (const c of doc.chats) {
      const ok = validChat(c)
      if (ok && !seen.has(ok.id)) {
        seen.add(ok.id)
        out.push(ok)
      }
    }
    return sortChats(out)
  } catch {
    return []
  }
}

export const sortChats = (chats: SavedChat[]): SavedChat[] => [...chats].sort((a, b) => b.updatedAt - a.updatedAt)

const serialize = (chats: SavedChat[]): string => JSON.stringify({ v: 1, fmt: ANSWER_FORMAT, chats: chats.map((c) => ({ ...c, turns: c.turns.map(storableTurn) })) })

/** The list cut to MAX_CHATS and MAX_BYTES, oldest chats dropped first; the newest is kept even when alone too big (its oldest turns go). */
export function capChats(chats: SavedChat[], maxChats: number = MAX_CHATS, maxBytes: number = MAX_BYTES): SavedChat[] {
  let list = sortChats(chats).slice(0, maxChats)
  while (list.length > 1 && serialize(list).length > maxBytes) list = list.slice(0, -1)
  if (list.length === 1 && serialize(list).length > maxBytes) {
    let turns = list[0].turns
    while (turns.length > 1 && serialize([{ ...list[0], turns }]).length > maxBytes) turns = turns.slice(1)
    list = serialize([{ ...list[0], turns }]).length > maxBytes ? [] : [{ ...list[0], turns }]
  }
  return list
}

export function loadChats(store: Store = browserStore): SavedChat[] {
  return parseChats(store.read(CHATS_KEY))
}

/** Writes the capped list; `ok` is false when the browser refused it (the chats then live in this page only). */
export function saveChats(chats: SavedChat[], store: Store = browserStore): { kept: SavedChat[]; ok: boolean } {
  const kept = capChats(chats)
  const ok = store.write(CHATS_KEY, serialize(kept)) !== false
  return { kept, ok }
}

const sameTurns = (a: LiveTurn[], b: LiveTurn[]): boolean =>
  a.length === b.length && JSON.stringify(a.map(storableTurn)) === JSON.stringify(b.map(storableTurn))

/** Adds or updates one chat. The time moves (and the chat goes to the top) only when its turns changed. */
export function upsertChat(chats: SavedChat[], id: string, turns: LiveTurn[], now: number = Date.now()): SavedChat[] {
  if (turns.length === 0) return chats
  const cur = chats.find((c) => c.id === id)
  if (cur && sameTurns(cur.turns, turns)) return chats
  const title = cur?.titleEdited ? cur.title : autoTitle(turns)
  const next: SavedChat = cur
    ? { ...cur, title, turns, updatedAt: now }
    : { id, title, createdAt: now, updatedAt: now, turns }
  return sortChats([next, ...chats.filter((c) => c.id !== id)])
}

export function renameChat(chats: SavedChat[], id: string, title: string): SavedChat[] {
  const t = title.replace(/\s+/g, ' ').trim().slice(0, 120)
  if (!t) return chats
  return chats.map((c) => (c.id === id ? { ...c, title: t, titleEdited: true } : c))
}

export const deleteChat = (chats: SavedChat[], id: string): SavedChat[] => chats.filter((c) => c.id !== id)

/** One turn of a saved chat changed while another chat was open (an answer arrived late). */
export function patchTurn(chats: SavedChat[], chatId: string, turnId: number, p: Partial<LiveTurn>, now: number = Date.now()): SavedChat[] {
  const cur = chats.find((c) => c.id === chatId)
  if (!cur || !cur.turns.some((t) => t.id === turnId)) return chats
  return upsertChat(chats, chatId, cur.turns.map((t) => (t.id === turnId ? { ...t, ...p } : t)), now)
}

/** The words a chat can be found by: its title, the questions and the answer sentences. */
export function chatText(c: SavedChat): string {
  const parts: string[] = [c.title]
  for (const t of c.turns) {
    if (t.question) parts.push(t.question)
    if (t.followUp) parts.push(t.followUp)
    for (const s of t.resp?.answer.speakable ?? []) parts.push(s.text)
  }
  return parts.join(' \n ')
}

export interface ChatHit {
  chat: SavedChat
  /** A short piece of text around the first match (empty when the title matched). */
  snippet: string
}

export function searchChats(chats: SavedChat[], query: string): ChatHit[] {
  const q = query.trim().toLowerCase()
  if (!q) return chats.map((chat) => ({ chat, snippet: '' }))
  const out: ChatHit[] = []
  for (const chat of chats) {
    if (chat.title.toLowerCase().includes(q)) {
      out.push({ chat, snippet: '' })
      continue
    }
    const text = chatText(chat)
    const i = text.toLowerCase().indexOf(q)
    if (i >= 0) {
      const from = Math.max(0, i - 30)
      const piece = text.slice(from, i + q.length + 50).replace(/\s+/g, ' ').trim()
      out.push({ chat, snippet: `${from > 0 ? '…' : ''}${piece}…` })
    }
  }
  return out
}

/** A new chat id: short, URL-safe and random enough for one browser. */
export function newChatId(): string {
  const rnd =
    typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function'
      ? Array.from(crypto.getRandomValues(new Uint8Array(6)), (b) => b.toString(36).padStart(2, '0')).join('')
      : Math.random().toString(36).slice(2, 14)
  return `c${Date.now().toString(36)}${rnd}`.slice(0, 22)
}

export interface ChatStore {
  chats: SavedChat[]
  /** False after the browser refused a write (storage full or blocked). */
  saved: boolean
  get: (id: string) => SavedChat | undefined
  upsert: (id: string, turns: LiveTurn[]) => void
  rename: (id: string, title: string) => void
  remove: (id: string) => void
  patch: (chatId: string, turnId: number, p: Partial<LiveTurn>) => void
}

/** The saved chats as React state; every change is written through (and capped) at once. */
export function useChatStore(store: Store = browserStore): ChatStore {
  const [chats, setChats] = useState<SavedChat[]>(() => loadChats(store))
  const [saved, setSaved] = useState(true)
  const ref = useRef(chats)
  const apply = useCallback(
    (f: (cur: SavedChat[]) => SavedChat[]) => {
      const next = f(ref.current)
      if (next === ref.current) return
      const { kept, ok } = saveChats(next, store)
      ref.current = kept
      setChats(kept)
      setSaved(ok)
    },
    [store],
  )
  // Another tab of this site saved or deleted a chat: show the same list here.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key !== CHATS_KEY) return
      const next = parseChats(e.newValue)
      ref.current = next
      setChats(next)
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])
  return {
    chats,
    saved,
    get: useCallback((id: string) => ref.current.find((c) => c.id === id), []),
    upsert: useCallback((id, turns) => apply((cur) => upsertChat(cur, id, turns)), [apply]),
    rename: useCallback((id, title) => apply((cur) => renameChat(cur, id, title)), [apply]),
    remove: useCallback((id) => apply((cur) => deleteChat(cur, id)), [apply]),
    patch: useCallback((chatId, turnId, p) => apply((cur) => patchTurn(cur, chatId, turnId, p)), [apply]),
  }
}
