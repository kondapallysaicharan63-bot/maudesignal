// Which page layout is shown: the classic workspace or the v2 chat-app layout.
// Build time: VITE_LAYOUT_DEFAULT ("classic" or "v2"; anything else means classic).
// Run time: ?layout=classic or ?layout=v2 in the address wins for that visit. A v2-only address (/chat/<id>,
// /signals, ...) opens v2 so a saved chat link still works after a refresh when the build default is classic.

export type LayoutMode = 'classic' | 'v2'

/** First path segments only the v2 layout serves (kept in step with router.ts and web/vercel.json). */
export const V2_SEGMENTS = ['chat', 'signals', 'devices', 'evidence', 'connect', 'workflow', 'thread', 'run', 'capture', 'pms-workflow', 'roi', 'investigate'] as const

const norm = (v: string | null | undefined): LayoutMode | null => {
  const s = (v ?? '').trim().toLowerCase()
  return s === 'v2' ? 'v2' : s === 'classic' ? 'classic' : null
}

/** True when the path names a v2 page (any folder the app is served from is allowed in front). */
export function isV2Path(pathname: string): boolean {
  return new RegExp(`/(${V2_SEGMENTS.join('|')})(/|$)`).test(pathname)
}

export function layoutMode(
  flag: string | undefined = import.meta.env.VITE_LAYOUT_DEFAULT as string | undefined,
  search: string = typeof window === 'undefined' ? '' : (window.location?.search ?? ''),
  pathname: string = typeof window === 'undefined' ? '/' : (window.location?.pathname ?? '/'),
): LayoutMode {
  try {
    const q = norm(new URLSearchParams(search).get('layout'))
    if (q) return q
  } catch {
    // an unreadable address keeps the build setting
  }
  if (isV2Path(pathname)) return 'v2'
  return norm(flag) ?? 'classic'
}

/** True when the v2 layout is shown. */
export const isV2 = (search?: string): boolean => layoutMode(undefined, search) === 'v2'
