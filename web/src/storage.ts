import { useCallback, useEffect, useState } from 'react'

// localStorage can throw (private window, blocked site data): every access is wrapped and the
// app renders correctly without it.
export function readStore(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

export function writeStore(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* ignore */
  }
}

export type ThemeChoice = 'system' | 'light' | 'dark'
const ORDER: ThemeChoice[] = ['system', 'light', 'dark']

function applyTheme(t: ThemeChoice): void {
  const root = document.documentElement
  if (t === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', t)
}

/** Light / Dark following the system until the person picks one. */
export function useTheme(): { theme: ThemeChoice; next: () => void } {
  const [theme, setTheme] = useState<ThemeChoice>(() => {
    const saved = readStore('ms-theme')
    return saved === 'light' || saved === 'dark' ? saved : 'system'
  })
  useEffect(() => applyTheme(theme), [theme])
  const next = useCallback(() => {
    setTheme((cur) => {
      const n = ORDER[(ORDER.indexOf(cur) + 1) % ORDER.length]
      writeStore('ms-theme', n)
      return n
    })
  }, [])
  return { theme, next }
}

const READ_KEY = 'ms-read-briefs'

/** Which daily briefs have been opened (drives the unread dot). */
export function useReadBriefs(): { isRead: (date: string) => boolean; markRead: (date: string) => void } {
  const [read, setRead] = useState<string[]>(() => {
    try {
      const v = JSON.parse(readStore(READ_KEY) ?? '[]') as unknown
      return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []
    } catch {
      return []
    }
  })
  const markRead = useCallback((date: string) => {
    setRead((cur) => {
      if (cur.includes(date)) return cur
      const n = [...cur, date]
      writeStore(READ_KEY, JSON.stringify(n))
      return n
    })
  }, [])
  return { isRead: (d) => read.includes(d), markRead }
}
