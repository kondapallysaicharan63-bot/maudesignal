// Which page layout is shown: the new one ('v2') or the current one ('classic').
// Run time: ?layout=v2 or ?layout=classic in the address wins for that visit.
// Build time: VITE_LAYOUT_DEFAULT ('v2' or 'classic'). Anything else, or nothing: 'classic'.
// Shared by every part of the v2 layout; keep this file small and its signature stable.

export type LayoutMode = 'v2' | 'classic'

const pick = (v: string | null | undefined): LayoutMode | null => {
  const t = (v ?? '').trim().toLowerCase()
  return t === 'v2' || t === 'classic' ? t : null
}

/** The layout for this visit: ?layout= first, then VITE_LAYOUT_DEFAULT, then 'classic'. */
export function layoutMode(
  search: string = typeof window === 'undefined' ? '' : (window.location?.search ?? ''),
  fallback: string | undefined = import.meta.env.VITE_LAYOUT_DEFAULT as string | undefined,
): LayoutMode {
  let fromUrl: LayoutMode | null = null
  try {
    fromUrl = pick(new URLSearchParams(search).get('layout'))
  } catch {
    // an unreadable address keeps the build setting
  }
  return fromUrl ?? pick(fallback) ?? 'classic'
}

/** True when the v2 layout is shown. */
export const isV2 = (search?: string): boolean => layoutMode(search) === 'v2'
