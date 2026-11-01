// A stored run shown in the same shape as a live answer, so the chat has one way to draw both. Nothing is added: the
// sentences, reasons and links all come from the stored thread and the stored evidence.
import { closestThread } from '../match'
import type { Evidence, Thread } from '../types'
import type { AskResponse, Link } from './api'
import { NOT_MEDICAL_ADVICE } from './api'

const MAX_LINKS = 2

/** Up to two MAUDE links for the reports a sentence's claims list. */
function sentenceLinks(ids: string[], ev: Evidence): Link[] {
  const out: Link[] = []
  for (const id of ids) {
    const r = ev.reports[id]
    if (r?.maude_url && !out.some((l) => l.url === r.maude_url)) out.push({ label: `Report ${id}`, url: r.maude_url })
    if (out.length >= MAX_LINKS) break
  }
  return out
}

/** The stored thread as an answer: passed sentences with links, blocked sentences as held-back reasons. */
export function threadToResponse(t: Thread, ev: Evidence, note: string): AskResponse {
  const speakable = t.sentences
    .filter((s) => s.status === 'pass')
    .map((s) => ({ text: s.text, links: sentenceLinks(s.claims.flatMap((c) => c.evidence_ids), ev) }))
  const withheld = t.sentences.filter((s) => s.status === 'block').map((s) => ({ reason: s.reasons[0] ?? 'held back by the claim gate' }))
  return {
    mode: 'recorded',
    recorded_note: note,
    ...(t.recorded_at_utc ? { recorded_at: t.recorded_at_utc } : {}),
    not_medical_advice: true,
    trace: [],
    cost_usd: null,
    limits: null,
    suggestions: [],
    answer: { speakable, withheld, spoken_text: speakable.map((s) => s.text).join(' ') },
  }
}

/** Why a stored run is shown, naming which one. */
export const recordedNote = (why: string, t: Thread): string =>
  `${why} Showing the stored run "${t.question}" (${t.id}, recorded ${t.recorded_at_utc.slice(0, 10)}), replayed from a recording.`

/** The closest stored question to the typed one as an answer, or a plain "no stored run is close" answer. */
export function recordedFor(question: string, threads: Thread[], ev: Evidence, why: string): AskResponse {
  const m = closestThread(question, threads)
  if (m) return threadToResponse(m.thread, ev, recordedNote(why, m.thread))
  return {
    mode: 'recorded',
    recorded_note: `${why} No stored run is close to that question, so nothing is shown as an answer.`,
    not_medical_advice: true,
    trace: [],
    cost_usd: null,
    limits: null,
    suggestions: [],
    answer: { speakable: [], withheld: [], spoken_text: '' },
  }
}

export { NOT_MEDICAL_ADVICE }
