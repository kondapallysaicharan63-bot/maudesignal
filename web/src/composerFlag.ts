// The on/off switch for the message box with the "+" menu (photo, sample label, web research, voice).
// Build time: VITE_FEATURE_COMPOSER_MENU (default on; "0", "false", "off" or "no" turns it off).
// Run time: ?composer=classic in the address forces the earlier composer for that visit.
// When it is off, the earlier composer (camera, mic and type-ahead in one row) renders unchanged.

const OFF = ['0', 'false', 'off', 'no']

/** True when the new message box is used. */
export function composerMenuOn(
  flag: string | undefined = import.meta.env.VITE_FEATURE_COMPOSER_MENU as string | undefined,
  search: string = typeof window === 'undefined' ? '' : (window.location?.search ?? ''),
): boolean {
  try {
    if (new URLSearchParams(search).get('composer')?.trim().toLowerCase() === 'classic') return false
  } catch {
    // an unreadable address keeps the build setting
  }
  return !OFF.includes((flag ?? '').trim().toLowerCase())
}
