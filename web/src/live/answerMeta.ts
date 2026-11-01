// Plain functions behind the v2 answer turn (?layout=v2): the quiet model chip, the text Copy puts on the clipboard,
// the text Read aloud speaks, and the clock time under an answer. Nothing here guesses: a model is named only when
// the response's own trace says that model did the work, and a date only when the response carries one.
import { NOT_MEDICAL_ADVICE, type AskResponse, type LabelResponse, type LiveTraceStep } from './api'

/** Display names of the Meta models the API reports in trace[].model. An id not listed and not matched is not named. */
const KNOWN: Record<string, string> = {
  'muse-voice-transcribe-1.0': 'Voice Transcribe',
}

/** The display name of one model id, or null when the id is unknown (never guessed). */
export function modelName(id: string | null | undefined): string | null {
  const t = (id ?? '').trim().toLowerCase()
  if (!t) return null
  if (KNOWN[t]) return KNOWN[t]
  let m = /^muse-spark-(\d+(?:\.\d+)*)$/.exec(t)
  if (m) return `Muse Spark ${m[1]}`
  if (t === 'muse-spark') return 'Muse Spark'
  if (/^muse-voice-transcribe(?:-\d+(?:\.\d+)*)?$/.test(t)) return 'Voice Transcribe'
  if (/^muse-wonder(?:-\d+(?:\.\d+)*)?$/.test(t)) return 'Muse Wonder'
  m = /^sam-(\d+(?:\.\d+)*)$/.exec(t)
  if (m) return `SAM ${m[1]}`
  return null
}

/** The models that did work in this run, in the order they ran: only steps that finished ('ok') and only known ids. */
export function modelsUsed(trace: LiveTraceStep[]): string[] {
  const out: string[] = []
  for (const s of trace) {
    if (s.status !== 'ok') continue
    const n = modelName(s.model)
    if (n && !out.includes(n)) out.push(n)
  }
  return out
}

/** "Oct 28, 2026" from "2026-10-28" (or an ISO time); null when the text holds no such date. */
export function fmtDate(iso: string | null | undefined): string | null {
  const m = /(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '')
  if (!m) return null
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])))
  if (Number.isNaN(d.getTime())) return null
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })
}

/** The date a recorded run was recorded: the response's own field, else "recorded YYYY-MM-DD" in its note. */
export function recordedDate(r: { recorded_at?: string; recorded_note?: string }): string | null {
  if (r.recorded_at) return fmtDate(r.recorded_at)
  const m = /recorded (\d{4}-\d{2}-\d{2})/i.exec(r.recorded_note ?? '')
  return m ? fmtDate(m[1]) : null
}

export type ChipKind = 'live' | 'instant' | 'cached' | 'recorded'
export interface Chip {
  kind: ChipKind
  text: string
}

/** The one quiet chip under an answer: which route answered and, for a live run, which Meta models did the work. */
export function chipFor(r: Pick<AskResponse, 'tier' | 'mode' | 'trace' | 'recorded_note'> & { recorded_at?: string }): Chip {
  if (r.tier === 'canned' || r.tier === 'direct') return { kind: 'instant', text: 'Instant answer' }
  if (r.tier === 'cache') return { kind: 'cached', text: 'Cached' }
  if (r.mode === 'recorded') {
    const d = recordedDate(r)
    return { kind: 'recorded', text: d ? `Recorded · ${d}` : 'Recorded' }
  }
  const names = modelsUsed(r.trace)
  return { kind: 'live', text: names.length ? `${names.join(' + ')} · Live` : 'Live' }
}

/** The chip for a label-photo turn (SAM 3.1 finds the label, Muse Spark reads it). */
export const labelChip = (r: Pick<LabelResponse, 'mode' | 'trace' | 'recorded_note'>): Chip => chipFor({ mode: r.mode, trace: r.trace, recorded_note: r.recorded_note })

/** What the Details panel calls the route that answered. */
export function tierLabel(r: Pick<AskResponse, 'tier' | 'mode'>): string {
  if (r.tier === 'canned') return 'Tier 1 · fixed reply, no model call'
  if (r.tier === 'direct') return 'Tier 2 · direct FDA lookup, no model call'
  if (r.tier === 'cache') return 'Tier 3 · earlier answer reused, no model call'
  if (r.mode === 'recorded') return 'Recorded run, no live model call'
  return 'Tier 4 · live model call'
}

/** Sum of the step times, in ms (null when there are no steps). */
export const totalMs = (trace: LiveTraceStep[]): number | null => (trace.length ? trace.reduce((a, s) => a + (Number.isFinite(s.ms) ? s.ms : 0), 0) : null)

/**
 * The text Copy puts on the clipboard: the answer's sentences, then every FDA link under them as "label: url".
 * The question is never included, and neither is any sentence the gate held back.
 */
export function copyText(r: Pick<AskResponse, 'answer'>): string {
  const lines: string[] = []
  const links: string[] = []
  for (const s of r.answer.speakable) {
    lines.push(s.text.trim())
    for (const l of s.links) {
      const row = `${l.label}: ${l.url}`
      if (!links.includes(row)) links.push(row)
    }
  }
  const out = [lines.join('\n')]
  if (links.length) out.push(['FDA sources:', ...links.map((l) => `- ${l}`)].join('\n'))
  out.push(NOT_MEDICAL_ADVICE)
  return out.filter(Boolean).join('\n\n')
}

/**
 * The text Read aloud speaks: the answer only, without web addresses, and without report ids or K-numbers in
 * parentheses ("(K123456)", "(report 50426770)"), which sound like noise when read out.
 */
export function readableText(r: Pick<AskResponse, 'answer'>): string {
  const base = r.answer.spoken_text?.trim() || r.answer.speakable.map((s) => s.text).join(' ')
  return base
    .replace(/https?:\/\/\S+/gi, ' ')
    .replace(/\(\s*[^()]*?\b(?:K\d{6}|DEN\d{6}|P\d{6}|\d{6,})\b[^()]*\)/gi, ' ')
    .replace(/\(\s*\)/g, ' ')
    .replace(/\s+([.,;:!?])/g, '$1')
    .replace(/\s+/g, ' ')
    .trim()
}

/** "11:42 PM" in the visitor's own time zone. */
export const fmtClock = (d: Date, locale = 'en-US'): string => d.toLocaleTimeString(locale, { hour: 'numeric', minute: '2-digit' })

/** A random id for one answer, used only to tie a rating to an answer. It holds nothing from the question or answer. */
export function newAnswerId(rand: () => string = defaultRand): string {
  return `a-${rand()}`.replace(/[^A-Za-z0-9_-]/g, '').slice(0, 40)
}

function defaultRand(): string {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID().replace(/-/g, '').slice(0, 20)
  } catch {
    /* fall through */
  }
  return Math.random().toString(36).slice(2, 12) + Date.now().toString(36)
}
