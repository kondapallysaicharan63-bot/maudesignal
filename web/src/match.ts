// Matches typed text against the recorded questions (threads.json). Token overlap only: no model,
// nothing sent anywhere. A weak match is not shown as an answer; the composer offers "Ask live" instead.
import type { Thread } from './types'

const STOP = new Set(
  'a an and are as at be but by can could did do does for from had has have how i if in is it its me my of on or our please should so tell than that the their them then there these they this to us was we were what when where which who why will with would you your about any'.split(
    ' ',
  ),
)

/** Lower-case words without punctuation or stop words; a trailing plural "s" is dropped. */
export function tokens(text: string): string[] {
  const words = text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .split(' ')
    .filter((w) => w && !STOP.has(w))
    .map((w) => (w.length > 3 && w.endsWith('s') && !w.endsWith('ss') ? w.slice(0, -1) : w))
  return [...new Set(words)]
}

export interface Match {
  thread: Thread
  /** Share of the typed words that appear in the recorded question (0 to 1). */
  score: number
}

/** A match needs at least half of the typed words, and two words unless only one or two were typed. */
export const MIN_SCORE = 0.5

export function closestThread(text: string, threads: Thread[]): Match | null {
  const q = tokens(text)
  if (q.length === 0) return null
  let best: (Match & { jaccard: number; hits: number }) | null = null
  for (const t of threads) {
    // Greetings (no tool step, no claim) are not answers to a question.
    if (t.tool_steps.length === 0 && t.sentences.every((s) => s.claims.length === 0)) continue
    const have = new Set(tokens(`${t.question} ${t.voice?.transcript_text ?? ''}`))
    const hits = q.filter((w) => have.has(w)).length
    if (hits === 0) continue
    const score = hits / q.length
    const jaccard = hits / (q.length + have.size - hits)
    if (!best || score > best.score || (score === best.score && jaccard > best.jaccard))
      best = { thread: t, score, jaccard, hits }
  }
  if (!best) return null
  if (best.score < MIN_SCORE) return null
  if (best.hits < 2 && q.length > 2) return null
  return { thread: best.thread, score: best.score }
}

const isAnswer = (t: Thread): boolean => t.tool_steps.length > 0 || t.sentences.some((s) => s.claims.length > 0)

/**
 * Type-ahead: recorded questions that share a word with what has been typed (the word being typed counts
 * when a question word starts with it), best first. Nothing is generated; every suggestion is a stored question.
 */
export function suggestThreads(text: string, threads: Thread[], limit = 6): Thread[] {
  const q = tokens(text)
  const last = text.toLowerCase().match(/[a-z0-9]+$/)?.[0] ?? ''
  if (q.length === 0 && !last) return []
  const scored: { t: Thread; hits: number }[] = []
  for (const t of threads) {
    if (!isAnswer(t)) continue
    const words = tokens(t.question)
    const hit = (w: string) => words.includes(w) || (w === last && last.length >= 2 && words.some((x) => x.startsWith(last)))
    const hits = new Set([...q, ...(last.length >= 2 ? [last] : [])].filter(hit)).size
    if (hits > 0) scored.push({ t, hits })
  }
  return scored
    .sort((a, b) => b.hits - a.hits)
    .slice(0, limit)
    .map((x) => x.t)
}
