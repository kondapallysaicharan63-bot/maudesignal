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

/** v2 layout: a saved chat's address (/chat/<id>) goes to Web Analytics as /chat, so no chat id leaves the browser. */
export function stripChatId(url: string): string {
  try {
    const u = new URL(url)
    u.pathname = u.pathname.replace(/\/chat\/[^/]+\/?$/, '/chat')
    return u.toString()
  } catch {
    return url
  }
}
