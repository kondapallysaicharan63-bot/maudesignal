// Noctua, MaudeSignal's watchful owl: the states, their priority, and the fixed captions.
// Branding only. Never evidence, never a decision, never an audit event.

/** The seven core states. The owl always sits beside text or a badge that says the same thing in words. */
export const MASCOT_STATES = ['idle', 'watching', 'alert', 'thinking', 'success', 'withheld', 'listening'] as const
export type MascotState = (typeof MASCOT_STATES)[number]

/** Highest first: alert > listening > thinking > withheld > success > watching > idle. */
export const STATE_PRIORITY: readonly MascotState[] = ['alert', 'listening', 'thinking', 'withheld', 'success', 'watching', 'idle']

/** Success and withheld are brief (2-3 s) and then the owl returns to whatever underlying state applies. */
export const TRANSIENT_STATES: readonly MascotState[] = ['success', 'withheld']
export const TRANSIENT_MS = 2500

export type MascotSignals = Partial<Record<MascotState, boolean>>

/** The state to show: the highest-priority one that is on; idle when none is. */
export function resolveState(signals: MascotSignals): MascotState {
  for (const s of STATE_PRIORITY) if (signals[s]) return s
  return 'idle'
}

export const isTransient = (s: MascotState): boolean => TRANSIENT_STATES.includes(s)

/** Captions only, never evidence. */
export const CAPTIONS = {
  alert: '3 codes flagged this week. Here are the links.',
  withheld: 'This sentence was withheld - it did not match a stored record.',
  listening: 'Listening. I will transcribe, then check every sentence.',
} as const

/** Words the owl never says (it never calls a device dangerous, never advises, never signs). */
export const FORBIDDEN_CAPTION = /dangerous|must recall|recall this|medical advice|\bI know\b|approved by|signed by|witness/i

/** The size classes: wings are dropped at 24px and below, where they turn to mud. */
export const WINGS_MAX_DROP_PX = 24
export const MASCOT_SIZES = { inline: 24, header: 32, empty: 48, hero: 96 } as const

/** The alert caption with the real count: always shown beside the alert links, never alone. */
export const alertCaption = (n: number): string => `${n} ${n === 1 ? 'code' : 'codes'} flagged. Here ${n === 1 ? 'is the link' : 'are the links'}.`
