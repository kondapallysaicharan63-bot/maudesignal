// Composer type-ahead: recorded questions (threads.json) and device codes (AI sweep + brief product codes).
// Nothing is generated; every suggestion is a stored question or a code that appears in the stored data,
// plus any exactly-typed three-letter code, which "Check any device type" accepts.
import { suggestThreads } from './match'
import type { Brief, Sweep, Thread } from './types'

export interface CodeInfo {
  code: string
  /** Device name from a stored brief, when one has it. */
  name: string | null
}

export type Suggestion = { kind: 'question'; thread: Thread } | { kind: 'code'; code: string; name: string | null; known: boolean }

/** Every product code in the sweep and in the briefs, with a name where a brief gives one. Sorted by code. */
export function knownCodes(sweep: Sweep | null | undefined, briefs: Brief[]): CodeInfo[] {
  const names = new Map<string, string>()
  for (const b of briefs) for (const [c, n] of Object.entries(b.device_types ?? {})) if (!names.has(c)) names.set(c, n)
  const codes = new Set<string>(names.keys())
  for (const r of sweep?.rows ?? []) codes.add(r.product_code)
  for (const b of briefs) for (const s of b.signals ?? []) codes.add(s.product_code)
  return [...codes]
    .filter((c) => /^[A-Z]{3}$/.test(c))
    .sort()
    .map((code) => ({ code, name: names.get(code) ?? null }))
}

const CODE_LIMIT = 4

/** Suggestions for what has been typed. Empty text gives none (the composer shows its starting points instead). */
export function suggest(text: string, threads: Thread[], codes: CodeInfo[], limit = 8): Suggestion[] {
  const typed = text.trim()
  if (!typed) return []
  const upper = typed.toUpperCase()
  const questions: Suggestion[] = suggestThreads(typed, threads, limit).map((thread) => ({ kind: 'question', thread }))
  const found: Suggestion[] = []
  const lower = typed.toLowerCase()
  if (/^[A-Za-z]{1,3}$/.test(typed)) {
    for (const c of codes) if (c.code.startsWith(upper)) found.push({ kind: 'code', code: c.code, name: c.name, known: true })
  } else if (lower.length >= 4) {
    for (const c of codes) if (c.name && c.name.toLowerCase().includes(lower)) found.push({ kind: 'code', code: c.code, name: c.name, known: true })
  }
  const exact = /^[A-Za-z]{3}$/.test(typed)
  if (exact && !found.some((s) => s.kind === 'code' && s.code === upper))
    found.unshift({ kind: 'code', code: upper, name: null, known: false })
  const shownCodes = found.slice(0, CODE_LIMIT)
  // Two or three letters that start a code put the codes first (the person is likely typing a code);
  // anything longer puts the recorded questions first and the codes after.
  const codeFirst = /^[A-Za-z]{2,3}$/.test(typed)
  const ordered = codeFirst ? [...shownCodes, ...questions] : [...questions, ...shownCodes]
  return ordered.slice(0, limit)
}

/** The code to open for Enter with no highlighted suggestion: a typed code that is in the stored data. */
export function exactKnownCode(text: string, codes: CodeInfo[]): string | null {
  const t = text.trim().toUpperCase()
  return /^[A-Z]{3}$/.test(t) && codes.some((c) => c.code === t) ? t : null
}

/**
 * The highlighted option after a key press in the combobox: ArrowDown moves on (wrapping), ArrowUp moves back
 * (wrapping; from nothing it goes to the last one). Any other key leaves it unchanged. -1 means none.
 */
export function moveActive(active: number, key: string, count: number): number {
  if (count <= 0) return -1
  if (key === 'ArrowDown') return (active + 1) % count
  if (key === 'ArrowUp') return active <= 0 ? count - 1 : active - 1
  return active
}
