// Read aloud for the v2 answer turn: the browser's own speechSynthesis, no voice vendor and no network call.
// It picks the most natural voice the device has (names with "Natural", "Neural" or "Online", then Google's),
// reads a little slower than default (0.95), and only ever one answer at a time. Voices load asynchronously in
// most browsers, so the list is read again on "voiceschanged". No synthesis or no voices: the button is hidden.
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

/** How natural a voice is likely to sound (higher is better); English voices only, others score -1. */
export function voiceScore(v: VoiceLike): number {
  const lang = (v.lang ?? '').toLowerCase().replace('_', '-')
  if (!lang.startsWith('en')) return -1
  const n = v.name.toLowerCase()
  let s = 0
  if (/\bnatural\b/.test(n)) s += 8
  if (/\bneural\b/.test(n)) s += 7
  if (/\bonline\b/.test(n)) s += 4
  if (n.startsWith('google')) s += 3
  if (/\b(aria|jenny|guy|ava|andrew|emma|brian|samantha)\b/.test(n)) s += 1
  if (lang === 'en-us') s += 2
  if (v.default) s += 0.5
  return s
}

/** The most natural English voice in `voices`, or null when there is none. */
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

// ---- one reader for the whole page -----------------------------------------------------------------

let speakingKey: string | null = null
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
  const t = speechText(text)
  if (!s || !t) return false
  s.cancel()
  const u = new SpeechSynthesisUtterance(t)
  const voice = pickVoice((s.getVoices?.() ?? []) as VoiceLike[])
  if (voice) {
    u.voice = voice as SpeechSynthesisVoice
    u.lang = voice.lang
  } else u.lang = 'en-US'
  u.rate = READ_RATE
  const done = () => {
    if (speakingKey === key) setKey(null)
  }
  u.onend = done
  u.onerror = done
  setKey(key)
  s.speak(u)
  return true
}

/** The key of the answer being read now, without subscribing. */
export const currentSpeakingKey = (): string | null => speakingKey

/** Stops any reading. */
export function stopReading(): void {
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
