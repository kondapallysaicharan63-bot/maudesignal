// Read aloud for the v2 answer turn: the browser's own speechSynthesis; this page adds no voice vendor and makes no
// network call of its own. Which voice is used decides where the text goes: a voice on the device (localService)
// speaks offline, while a cloud voice ("Online", many "Natural" voices) sends the text to the browser vendor's speech
// service. So on-device voices come first: on-device Natural / Neural, then other on-device voices, and cloud
// Natural / Online voices only when the device has no English voice of its own. Rate 0.95, one sentence per
// utterance (queued), only one answer at a time. Voices load asynchronously in most browsers, so the list is read
// again on "voiceschanged". No synthesis or no voices: the button is hidden.
import { useEffect, useState, useSyncExternalStore } from 'react'
import { speechText } from './speech'

export const READ_RATE = 0.95

export interface VoiceLike {
  name: string
  lang: string
  default?: boolean
  localService?: boolean
}

interface SynthLike {
  speak: (u: SpeechSynthesisUtterance) => void
  cancel: () => void
  getVoices?: () => VoiceLike[]
  addEventListener?: (t: string, f: () => void) => void
  removeEventListener?: (t: string, f: () => void) => void
}

const synth = (): SynthLike | null => {
  try {
    return typeof window !== 'undefined' && 'speechSynthesis' in window && typeof SpeechSynthesisUtterance !== 'undefined'
      ? (window.speechSynthesis as unknown as SynthLike)
      : null
  } catch {
    return null
  }
}

/**
 * How good a voice is for reading an answer (higher is better); non-English voices score -1. On-device natural
 * voices first, then other on-device voices, then cloud natural / online ones, then any other cloud voice.
 */
export function voiceScore(v: VoiceLike): number {
  const lang = (v.lang ?? '').toLowerCase().replace('_', '-')
  if (!lang.startsWith('en')) return -1
  const n = v.name.toLowerCase()
  const natural = /\b(natural|neural)\b/.test(n)
  const online = /\bonline\b/.test(n)
  const local = v.localService === true
  let s: number
  if (local && natural) s = 400
  else if (local) s = 300
  else if (natural || online) s = 200
  else s = 100
  if (n.startsWith('google')) s += 3
  if (/\b(aria|jenny|guy|ava|andrew|emma|brian|samantha)\b/.test(n)) s += 1
  if (lang === 'en-us') s += 2
  if (v.default) s += 0.5
  return s
}

/** The best English voice in `voices` (see voiceScore), or null when there is none. */
export function pickVoice<T extends VoiceLike>(voices: T[]): T | null {
  let best: T | null = null
  let bestScore = -1
  for (const v of voices) {
    const s = voiceScore(v)
    if (s > bestScore) {
      best = v
      bestScore = s
    }
  }
  return bestScore >= 0 ? best : null
}

/** The text split into sentences, one utterance each (long answers stop and resume more reliably this way). */
export function sentencesOf(text: string): string[] {
  return text
    .split(/(?<=[.!?]["”)]?)\s+(?=["“(]?[A-Z0-9])/)
    .map((s) => s.trim())
    .filter(Boolean)
}

/** The read-aloud key of a chat turn, shared by the action bar and the voice auto-read. */
export const readKey = (turnId: number | string): string => `turn-${turnId}`

// ---- one reader for the whole page -----------------------------------------------------------------

let speakingKey: string | null = null
/** The reading in progress: each utterance checks it is still this one before it changes any state. */
let active: object | null = null
const listeners = new Set<() => void>()
const emit = () => listeners.forEach((f) => f())
const setKey = (k: string | null) => {
  if (speakingKey !== k) {
    speakingKey = k
    emit()
  }
}

/** Starts reading `text` for answer `key`; any other reading stops first. Returns false when nothing can be read. */
export function startReading(key: string, text: string): boolean {
  const s = synth()
  const parts = sentencesOf(speechText(text))
  if (!s || parts.length === 0) return false
  const session = {}
  active = session
  s.cancel()
  const voice = pickVoice((s.getVoices?.() ?? []) as VoiceLike[])
  const finish = () => {
    // A cancelled reading's late end or error event belongs to an older session and changes nothing.
    if (active !== session) return
    active = null
    setKey(null)
  }
  setKey(key)
  parts.forEach((part, i) => {
    const u = new SpeechSynthesisUtterance(part)
    if (voice) {
      u.voice = voice as SpeechSynthesisVoice
      u.lang = voice.lang
    } else u.lang = 'en-US'
    u.rate = READ_RATE
    u.onerror = finish
    if (i === parts.length - 1) u.onend = finish
    s.speak(u)
  })
  return true
}

/** The key of the answer being read now, without subscribing. */
export const currentSpeakingKey = (): string | null => speakingKey

/** Stops any reading. */
export function stopReading(): void {
  active = null
  synth()?.cancel()
  setKey(null)
}

const subscribe = (f: () => void) => {
  listeners.add(f)
  return () => listeners.delete(f)
}

/** The key of the answer being read now (null: none). */
export const useSpeakingKey = (): string | null => useSyncExternalStore(subscribe, () => speakingKey, () => null)

/** True when this browser can read aloud: speechSynthesis exists and has at least one voice (rechecked on voiceschanged). */
export function useCanReadAloud(): boolean {
  const [ok, setOk] = useState(() => (synth()?.getVoices?.() ?? []).length > 0)
  useEffect(() => {
    const s = synth()
    if (!s) return
    const check = () => setOk((s.getVoices?.() ?? []).length > 0)
    check()
    s.addEventListener?.('voiceschanged', check)
    return () => s.removeEventListener?.('voiceschanged', check)
  }, [])
  return ok
}
