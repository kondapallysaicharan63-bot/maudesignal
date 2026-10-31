// Takes the place of the message box while a voice question is recorded: Cancel, the state and timer, a live waveform
// (a still level bar with prefers-reduced-motion), Pause or Resume, and Stop. Nothing is sent from here: Stop turns the
// recording into words that go into the message box for the person to read and edit before pressing Send.
import { useEffect, useRef, useState } from 'react'
import { Icon } from '../icons'
import { fmtClock, MAX_SECONDS } from '../live/audio'
import { WAVE_BARS, type Recorder } from '../live/useRecorder'

const reducedMotion = (): boolean => typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** What a screen reader hears: the state when it changes, and the time every 15 seconds while recording. */
export function voiceAnnouncement(state: 'recording' | 'paused' | 'transcribing', seconds: number): string {
  if (state === 'transcribing') return 'Recording stopped. Turning it into text; nothing is sent until you press Send.'
  if (state === 'paused') return `Paused at ${fmtClock(seconds)}.`
  return seconds < 1 ? 'Recording. Press Stop when you have finished, or Cancel to discard it.' : `Recording, ${fmtClock(seconds)}.`
}

export function VoiceBar({ rec, transcribing }: { rec: Recorder; transcribing: boolean }) {
  const stopRef = useRef<HTMLButtonElement>(null)
  const phase: 'recording' | 'paused' | 'transcribing' = transcribing || rec.state === 'processing' ? 'transcribing' : rec.state === 'paused' ? 'paused' : 'recording'
  const [reduced] = useState(reducedMotion)
  // The spoken status: changes of state at once, the clock only every 15 s (so it does not talk over the person).
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

  const bars = Array.from({ length: WAVE_BARS }, (_, i) => rec.levels[rec.levels.length - WAVE_BARS + i] ?? 0)
  const busy = phase === 'transcribing'
  const btn = 'ms-btn ms-btn--secondary !min-h-11 !min-w-11 shrink-0 !px-2 sm:!px-3'
  return (
    <div
      role="group"
      aria-label="Voice question"
      className="relative z-10 flex min-h-[3.25rem] items-center gap-2 rounded-md border border-rule-strong bg-surface p-1.5 sm:gap-3"
      data-testid="voice-bar"
      data-state={phase}
    >
      <p className="sr-only" aria-live="polite" data-testid="voice-live">
        {said}
      </p>
      <button type="button" className={btn} onClick={rec.cancel} disabled={busy} aria-label="Cancel: discard this recording" data-testid="voice-cancel">
        <Icon name="close" size={20} />
        <span className="max-sm:hidden">Cancel</span>
      </button>
      <span className="flex shrink-0 items-center gap-2 text-[16px] font-semibold text-ink">
        <i
          aria-hidden="true"
          className={['inline-block h-2.5 w-2.5 rounded-full', phase === 'recording' ? 'bg-critical' : 'bg-ink-3'].join(' ')}
        />
        <span className="max-sm:hidden" data-testid="voice-state">
          {phase === 'transcribing' ? 'Transcribing…' : phase === 'paused' ? 'Paused' : 'Recording'}
        </span>
        <span className="ms-num" role="timer" aria-label={`Recorded ${fmtClock(rec.seconds)} of ${fmtClock(MAX_SECONDS)}`} data-testid="voice-timer">
          {fmtClock(rec.seconds)}
        </span>
      </span>
      {reduced ? (
        <div
          className="ws-meter min-w-8 flex-1"
          role="meter"
          aria-label="Microphone level"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(rec.level * 100)}
          data-testid="voice-meter"
        >
          <i style={{ width: `${Math.max(2, Math.round(rec.level * 100))}%` }} />
        </div>
      ) : (
        <div className="flex h-8 min-w-8 flex-1 items-center justify-end gap-[2px] overflow-hidden" aria-hidden="true" data-testid="voice-wave">
          {bars.map((v, i) => (
            <i
              key={i}
              className={['block w-[3px] shrink-0 rounded-xs', phase === 'recording' ? 'bg-accent' : 'bg-ink-3'].join(' ')}
              style={{ height: `${Math.max(8, Math.round(Math.min(1, v * 1.6) * 100))}%` }}
            />
          ))}
        </div>
      )}
      {rec.canPause && (
        <button
          type="button"
          className={btn}
          onClick={phase === 'paused' ? rec.resume : rec.pause}
          disabled={busy}
          aria-label={phase === 'paused' ? 'Resume recording' : 'Pause recording'}
          data-testid="voice-pause"
        >
          <Icon name={phase === 'paused' ? 'play' : 'pause'} size={20} />
          <span className="max-sm:hidden">{phase === 'paused' ? 'Resume' : 'Pause'}</span>
        </button>
      )}
      <button
        ref={stopRef}
        type="button"
        className="ms-btn ws-btn-primary !min-h-11 !min-w-11 shrink-0 !px-2 sm:!px-3"
        onClick={rec.stop}
        disabled={busy}
        aria-label="Stop and turn the recording into text (nothing is sent yet)"
        data-testid="voice-stop"
      >
        <Icon name="stop" size={20} />
        <span className="max-sm:hidden">{busy ? 'Working…' : 'Stop'}</span>
      </button>
    </div>
  )
}
