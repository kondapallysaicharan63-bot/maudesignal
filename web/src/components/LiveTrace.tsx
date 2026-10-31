import { fmtStepMs, type LiveTraceStep } from '../live/api'

const MODEL: Record<string, string> = {
  'muse-spark-1.3': 'Muse Spark',
  'muse-voice-transcribe-1.0': 'Voice Transcribe',
  'sam-3.1': 'SAM 3.1',
}

const STATUS: Record<LiveTraceStep['status'], { text: string; cls: string }> = {
  ok: { text: 'done', cls: 'bg-success-soft text-success' },
  skipped: { text: 'skipped', cls: 'bg-sunk text-ink-2' },
  failed: { text: 'failed', cls: 'bg-critical-soft text-critical' },
  not_searched: { text: 'not searched', cls: 'bg-sunk text-ink-2' },
  unknown: { text: 'unknown', cls: 'bg-sunk text-ink-2' },
}

/** The steps of one live run, in order, each with the model that did it, its time in milliseconds and its outcome. */
export function LiveTrace({ steps, shown = steps.length, label = 'Steps of this run' }: { steps: LiveTraceStep[]; shown?: number; label?: string }) {
  if (steps.length === 0) return null
  return (
    <ol className="m-0 list-none space-y-1 p-0 text-[15px]" aria-label={label} data-testid="live-trace">
      {steps.slice(0, shown).map((s, i) => (
        <li key={i} className="flex flex-wrap items-center gap-x-2 gap-y-1" data-testid="trace-step">
          <span className="ms-num w-5 shrink-0 text-ink-2">{i + 1}</span>
          <span className="font-semibold">{s.step}</span>
          {s.model && <span className="ms-code">{MODEL[s.model] ?? s.model}</span>}
          <span className="ms-num text-ink-2">{fmtStepMs(s.ms)}</span>
          <span className={`ws-pill ${STATUS[s.status].cls}`}>{STATUS[s.status].text}</span>
          {s.note && <span className="ws-wrap text-ink-2">{s.note}</span>}
        </li>
      ))}
    </ol>
  )
}
