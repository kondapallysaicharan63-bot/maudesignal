import { Icon } from '../icons'
import { NOT_RECORDED, stepHasMetrics, stepMetricParts, traceSummary, type Metric, type Trace, type TraceStep } from '../trace'

const DOT: Record<TraceStep['kind'], string> = {
  heard: 'bg-accent',
  plan: 'bg-accent',
  tool: 'bg-accent',
  sam: 'bg-accent',
  read: 'bg-accent',
  review: 'bg-accent',
  check: 'bg-success',
  gate: 'bg-success',
  done: 'bg-ink-3',
}

function Val({ label, m }: { label: string; m: Metric }) {
  return (
    <span className="whitespace-nowrap">
      {label}: <span className={m.recorded ? 'ms-num font-semibold text-ink' : ''}>{m.text}</span>
    </span>
  )
}

/**
 * The step timeline of one run, folded to one summary line until opened. `shown` is how many steps the replay has
 * revealed so far. A step prints time, tokens and cost only where the recording stored them; when it stored none for
 * any step, one note says so instead of repeating "not recorded" on every step. The whole-run line carries the
 * run-level values that were stored.
 */
export function TraceView({
  trace,
  shown,
  label = 'Steps taken',
  replayed = true,
  defaultOpen = false,
  absentLabels = false,
}: {
  trace: Trace
  shown: number
  label?: string
  /** True while a stored run is being replayed step by step; false when the whole stored run is shown at once. */
  replayed?: boolean
  defaultOpen?: boolean
  /** Print "Time: not recorded" (and "Cost: not recorded" on model steps) where the recording stored none. */
  absentLabels?: boolean
}) {
  const steps = trace.steps.slice(0, shown)
  const complete = shown >= trace.steps.length
  const anyMetrics = trace.steps.some(stepHasMetrics)
  return (
    <details open={defaultOpen} className="rounded-md border border-rule-strong bg-surface px-3 py-1 text-[17px]" data-testid="trace">
      <summary className="flex min-h-11 cursor-pointer flex-wrap items-center gap-x-3 gap-y-0 py-1">
        <span className="font-semibold">How this was made</span>
        <span className="ws-wrap text-[15px] text-ink-2" data-testid="trace-summary">
          {complete ? traceSummary(trace) : `Replaying: step ${Math.max(1, shown)} of ${trace.steps.length}`}
        </span>
      </summary>
      <ol className="m-0 mt-2 list-none p-0" aria-label={label}>
        {steps.map((s) => {
          const parts = stepMetricParts(s)
          if (absentLabels) {
            if (!s.time.recorded) parts.push(`time: ${NOT_RECORDED}`)
            if (!s.cost.recorded && s.model) parts.push(`cost: ${NOT_RECORDED}`)
          }
          return (
            <li key={s.id} data-step={s.kind} className="relative border-l-2 border-rule-strong pb-3 pl-4 last:pb-1">
              <span aria-hidden className={`absolute -left-[7px] top-[9px] h-3 w-3 rounded-full ${DOT[s.kind]}`} />
              <p className="m-0 flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="font-semibold text-ink">{s.title}</span>
                {s.kind === 'tool' && s.args !== null && (
                  <code className="ws-wrap rounded-xs bg-sunk px-1.5 font-mono text-[15px] text-ink">{s.args}</code>
                )}
              </p>
              <p className="ws-wrap m-0 mt-0.5 text-ink-2">{s.kind === 'tool' ? `Result: ${s.result}.` : s.detail}</p>
              {s.lines.length > 0 && (
                <ul className="m-0 mt-1 list-disc pl-5 text-ink-2">
                  {s.lines.map((l, i) => (
                    <li key={i} className="ws-wrap">
                      {l}
                    </li>
                  ))}
                </ul>
              )}
              <p className="m-0 mt-0.5 flex flex-wrap gap-x-2 text-[15px] text-ink-2">
                <span className="font-semibold">{s.model ?? 'Plain code, no model'}</span>
                {parts.map((p) => (
                  <span key={p} className="ms-num">
                    · {p}
                  </span>
                ))}
              </p>
            </li>
          )
        })}
      </ol>
      {complete && (
        <p
          className="m-0 mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-rule pt-2 text-[15px] text-ink-2"
          data-testid="trace-run"
        >
          <span className="font-semibold text-ink">Whole run</span>
          <Val label="Time" m={trace.usage.time} />
          <Val label="Tokens" m={trace.usage.tokens} />
          <Val label="Cost" m={trace.usage.cost} />
        </p>
      )}
      <p className="m-0 mb-1 mt-2 flex gap-2 text-[15px] leading-snug text-ink-2">
        <Icon name="info" size={16} />
        <span>
          {replayed
            ? 'Replayed from a recording at an even pace. The pace is not the speed of the original run. '
            : 'Stored run. '}
          {anyMetrics
            ? 'A step shows time, tokens or cost only where the recording stored it.'
            : `Per-step time, tokens and cost: ${NOT_RECORDED}.`}
        </span>
      </p>
    </details>
  )
}
