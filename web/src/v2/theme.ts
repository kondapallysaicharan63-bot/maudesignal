// The v2 theme choice: every theme the design system defines (tokens.css), or the system setting.
// Same storage key as the classic switch ('ms-theme'), so a choice carries over; index.html applies it before paint.
import { useCallback, useEffect, useState } from 'react'
import { readStore, writeStore } from '../storage'

export const THEMES = [
  { id: 'system', label: 'System' },
  { id: 'light', label: 'Paper (light)' },
  { id: 'dark', label: 'Night (dark)' },
  { id: 'contrast', label: 'High contrast' },
  { id: 'black', label: 'Black' },
  { id: 'pink', label: 'Pink' },
] as const
export type ThemeId = (typeof THEMES)[number]['id']

const isTheme = (v: string | null): v is ThemeId => THEMES.some((t) => t.id === v)

export const themeLabel = (t: ThemeId): string => THEMES.find((x) => x.id === t)?.label ?? 'System'

/** The quick switch in the top bar: System, then Paper, then Night (the other themes are in the sidebar menu). */
export function nextQuick(t: ThemeId): ThemeId {
  return t === 'system' ? 'light' : t === 'light' ? 'dark' : 'system'
}

export function applyTheme(t: ThemeId, root: HTMLElement = document.documentElement): void {
  if (t === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', t)
}

export function useThemeV2(): { theme: ThemeId; setTheme: (t: ThemeId) => void } {
  const [theme, set] = useState<ThemeId>(() => {
    const saved = readStore('ms-theme')
    return isTheme(saved) ? saved : 'system'
  })
  useEffect(() => applyTheme(theme), [theme])
  const setTheme = useCallback((t: ThemeId) => {
    writeStore('ms-theme', t)
    set(t)
  }, [])
  return { theme, setTheme }
}
