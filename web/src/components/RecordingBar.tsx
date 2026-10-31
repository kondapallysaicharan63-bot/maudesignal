import { fmtClock, MAX_SECONDS } from '../live/audio'
import type { Recorder } from '../live/useRecorder'

/** Shown while the mic is on: a live level meter and a timer. Click the mic again (or wait 60 s) to stop. */
export function RecordingBar({ rec }: { rec: Pick<Recorder, 'state' | 'seconds' | 'level' | 'stop'> }) {
  if (rec.state === 'idle') return null
  const recording = rec.state === 'recording'
  return (
    <div className="mb-2 flex flex-wrap items-center gap-3 rounded-md border border-rule-strong bg-surface px-3 py-2" data-testid="recording-bar">
      <span className="ws-pill bg-critical-soft text-critical ws-pill--ring" role="status">
        {recording ? 'Recording' : 'Preparing your question'}
      </span>
      {recording && (
        <>
          <span className="ms-num text-[17px] font-semibold" data-testid="rec-timer" aria-label={`Recording time ${fmtClock(rec.seconds)} of ${fmtClock(MAX_SECONDS)}`}>
            {fmtClock(rec.seconds)} / {fmtClock(MAX_SECONDS)}
          </span>
          <div
            className="ws-meter min-w-24 flex-1"
            role="meter"
            aria-label="Microphone level"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(rec.level * 100)}
            data-testid="rec-meter"
          >
            <i style={{ width: `${Math.max(2, Math.round(rec.level * 100))}%` }} />
          </div>
          <button type="button" className="ms-btn ms-btn--secondary" style={{ height: 40 }} onClick={rec.stop}>
            Stop and send
          </button>
        </>
      )}
    </div>
  )
}
