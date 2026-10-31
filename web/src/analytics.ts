/** Removes the personal ?r=CODE from a URL before it goes to Web Analytics. */
export function stripRef(url: string): string {
  try {
    const u = new URL(url)
    u.searchParams.delete('r')
    return u.toString()
  } catch {
    return url
  }
}
