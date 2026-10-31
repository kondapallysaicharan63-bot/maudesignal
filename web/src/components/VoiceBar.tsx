// Takes the place of the message box while a voice question is recorded: Cancel, the state word and timer, a live
// waveform (24 bars from the analyser level; flat grey while paused; a still level bar with prefers-reduced-motion),
// Pause or Resume, and Stop. Nothing is sent from here: Stop turns the recording into words that go into the message
// box for the person to read and edit before pressing Send. At 1:00 the recording pauses and waits for Stop or Cancel.
import { useEffect, useRef, useState } from 'react'
import { Icon } from '../icons'
import { fmtClock, MAX_SECONDS } from '../live/audio'
import { WARN_SECONDS, WAVE_BARS, type Recorder } from '../live/useRecorder'

const reducedMotion = (): boolean => typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

export const LIMIT_TEXT = 'Limit reached — press Stop to use it or ✕ to discard'

type Phase = 'recording' | 'paused' | 'limit' | 'transcribing'

/** What a screen reader hears: the state when it changes, and the time every 15 seconds while recording. */
export function voiceAnnouncement(state: Phase, seconds: number): string {
  if (state === 'transcribing') return 'Recording stopped. Turning it into text; nothing is sent until you press Send.'
  if (state === 'limit') return `One minute recorded. ${LIMIT_TEXT}.`
  if (state === 'paused') return `Paused at ${fmtClock(seconds)}.`
  return seconds < 1 ? 'Recording. Press Stop when you have finished, or Cancel to discard it.' : `Recording, ${fmtClock(seconds)}.`
}

/** Bar heights (0..1) for the waveform: the newest levels on the right, flat while not recording. */
export function waveHeights(levels: number[], live: boolean, n = WAVE_BARS): number[] {
  return Array.from({ length: n }, (_, i) => {
    if (!live) return 0
    const v = levels[levels.length - n + i] ?? 0
    return Math.min(1, Math.sqrt(Math.max(0, v)) * 1.6) // square root: quiet speech still shows
  })
}

export function VoiceBar({ rec, transcribing, title }: { rec: Recorder; transcribing: boolean; title?: string }) {
  const stopRef = useRef<HTMLButtonElement>(null)
  const phase: Phase =
    transcribing || rec.state === 'processing' ? 'transcribing' : rec.atLimit ? 'limit' : rec.state === 'paused' ? 'paused' : 'recording'
  const [reduced] = useState(reducedMotion)
  const quarter = Math.floor(rec.seconds / 15)
  const [said, setSaid] = useState('')
  useEffect(() => {
    setSaid(voiceAnnouncement(phase, phase === 'recording' ? quarter * 15 : rec.seconds))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, quarter])
  // Keyboard: Stop is focused when the bar appears (recording has started).
  useEffect(() => {
    stopRef.current?.focus()
  }, [])

  const busy = phase === 'transcribing'
  const live = phase === 'recording'
  const word = phase === 'transcribing' ? 'Transcribing…' : phase === 'recording' ? 'Recording' : 'Paused'
  const iconBtn =
    'inline-flex h-11 min-w-11 shrink-0 items-center justify-center gap-2 rounded-full px-2 text-[16px] font-semibold text-ink hover:bg-sunk disabled:opacity-45 sm:px-3'
  return (
    <div className="relative z-10" title={title}>
      <div
        role="group"
        aria-label="Voice question"
        className="flex min-h-[3.75rem] items-center gap-1.5 rounded-lg border border-rule bg-surface p-2 shadow-[var(--shadow-pop)] sm:gap-3"
        data-testid="voice-bar"
        data-state={phase === 'limit' ? 'paused' : phase}
        data-limit={rec.atLimit ? 'true' : undefined}
      >
        <p className="sr-only" aria-live="polite" data-testid="voice-live">
          {said}
        </p>
        <button type="button" className={iconBtn} onClick={rec.cancel} disabled={busy} aria-label="Cancel: discard this recording" data-testid="voice-cancel">
          <Icon name="close" size={20} />
          <span className="max-sm:hidden">Cancel</span>
        </button>
        <span className="flex shrink-0 items-center gap-1.5 text-[15px] font-semibold text-ink">
          <i aria-hidden="true" className={['inline-block h-2.5 w-2.5 rounded-full', live ? 'bg-critical' : 'bg-ink-3'].join(' ')} />
          <span data-testid="voice-state">{word}</span>
          <span className="ms-num font-normal text-ink-2" role="timer" aria-label={`Recorded ${fmtClock(rec.seconds)} of ${fmtClock(MAX_SECONDS)}`} data-testid="voice-timer">
            {fmtClock(rec.seconds)}
          </span>
        </span>
        {reduced ? (
          <div
            className="ws-meter min-w-6 flex-1"
            role="meter"
            aria-label="Microphone level"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={live ? Math.round(rec.level * 100) : 0}
            data-testid="voice-meter"
          >
            <i style={{ width: `${live ? Math.max(2, Math.round(rec.level * 100)) : 2}%` }} />
          </div>
        ) : (
          <div className="flex h-8 min-w-6 flex-1 items-center justify-center overflow-hidden" aria-hidden="true" data-testid="voice-wave">
            {/* A 2px grey floor across the whole wave; each bar rises from it, centred on it. */}
            <span className="relative flex h-8 max-w-full items-center justify-center gap-[3px]">
              <span className="absolute inset-x-0 top-1/2 h-[2px] -translate-y-1/2 rounded-full bg-ink-3 opacity-60" />
              {waveHeights(rec.levels, live).map((v, i) => {
                const h = Math.round(v * 32)
                return (
                  <i
                    key={i}
                    className={['relative block w-[2px] shrink-0 rounded-full transition-[height] duration-100 ease-out', live && h > 2 ? 'bg-accent' : 'bg-ink-3'].join(' ')}
                    style={{ height: `${Math.max(2, h)}px` }}
                  />
                )
              })}
            </span>
          </div>
        )}
        {rec.canPause && (
          <button
            type="button"
            className={`${iconBtn} sm:min-w-[7.5rem]`}
            onClick={phase === 'paused' ? rec.resume : rec.pause}
            disabled={busy || phase === 'limit'}
            aria-label={phase === 'paused' || phase === 'limit' ? 'Resume recording' : 'Pause recording'}
            data-testid="voice-pause"
          >
            <Icon name={phase === 'paused' || phase === 'limit' ? 'play' : 'pause'} size={20} />
            <span className="max-sm:hidden">{phase === 'paused' || phase === 'limit' ? 'Resume' : 'Pause'}</span>
          </button>
        )}
        <button
          ref={stopRef}
          type="button"
          className="inline-flex h-11 min-w-11 shrink-0 items-center justify-center gap-2 rounded-full bg-accent px-3 text-[16px] font-semibold text-[var(--on-accent)] hover:opacity-90 disabled:opacity-45"
          onClick={rec.stop}
          disabled={busy}
          aria-label="Stop and turn the recording into text (nothing is sent yet)"
          data-testid="voice-stop"
        >
          <Icon name="stop" size={18} />
          <span className="max-sm:hidden">{busy ? 'Working…' : 'Stop'}</span>
        </button>
      </div>
      {(phase === 'limit' || (live && rec.seconds >= WARN_SECONDS)) && (
        <p className="m-0 mt-1 text-center text-[15px] font-semibold text-ink" role={phase === 'limit' ? 'status' : undefined} data-testid="voice-limit">
          {phase === 'limit' ? LIMIT_TEXT : `Stops at ${fmtClock(MAX_SECONDS)}`}
        </p>
      )}
    </div>
  )
}
