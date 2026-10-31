// Reads an answer aloud with the browser's own speech synthesis. Only the answer's spoken_text is ever read: sentences the
// gate held back are not in it. Nothing is sent anywhere; the voice is the device's.

interface SynthLike {
  speak: (u: SpeechSynthesisUtterance) => void
  cancel: () => void
  speaking: boolean
}

const synthOf = (w: Window | undefined = typeof window === 'undefined' ? undefined : window): SynthLike | null =>
  w && 'speechSynthesis' in w && typeof SpeechSynthesisUtterance !== 'undefined' ? (w.speechSynthesis as SynthLike) : null

export const speechSupported = (): boolean => synthOf() !== null

/** The text to read: spoken_text trimmed and cut at a sensible length (very long answers are not read in full). */
export function speechText(spoken: string, max = 1200): string {
  const t = spoken.replace(/\s+/g, ' ').trim()
  if (t.length <= max) return t
  const cut = t.slice(0, max)
  const end = Math.max(cut.lastIndexOf('. '), cut.lastIndexOf('? '))
  return end > 200 ? cut.slice(0, end + 1) : cut
}

/** Starts reading `spoken`. Returns false when the browser cannot speak or there is nothing to read. */
export function speak(spoken: string, handlers: { onStart?: () => void; onEnd?: () => void } = {}): boolean {
  const synth = synthOf()
  const text = speechText(spoken)
  if (!synth || !text) return false
  synth.cancel()
  const u = new SpeechSynthesisUtterance(text)
  u.lang = 'en-US'
  u.onstart = () => handlers.onStart?.()
  u.onend = () => handlers.onEnd?.()
  u.onerror = () => handlers.onEnd?.()
  synth.speak(u)
  return true
}

export function stopSpeaking(): void {
  synthOf()?.cancel()
}
