// "Did you mean LLZ?" after a spoken question: the server names known product codes one letter away from an unknown
// code-like word it heard. The words are never changed by themselves; only a click on the suggestion swaps the word.

/** Number of single-letter edits (insert, delete, change) between two short strings. */
export function editDistance(a: string, b: string): number {
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i)
  for (let i = 1; i <= a.length; i++) {
    const cur = [i]
    for (let j = 1; j <= b.length; j++) cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1))
    prev = cur
  }
  return prev[b.length]
}

/** The first capitalised three-letter word that is one letter from `code` (and not `code` itself), or null. */
export function heardCodeFor(text: string, code: string): string | null {
  for (const m of text.matchAll(/\b([A-Z]{3})\b/g)) {
    if (m[1] !== code && editDistance(m[1], code) === 1) return m[1]
  }
  return null
}

/** `text` with the heard word replaced by `code` (first match only). Unchanged when no such word is found. */
export function applyCodeSuggestion(text: string, code: string): string {
  const heard = heardCodeFor(text, code)
  if (!heard) return text
  return text.replace(new RegExp(`\\b${heard}\\b`), code)
}
