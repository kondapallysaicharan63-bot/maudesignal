import { Icon } from '../icons'
import { NOT_RECORDED, type Metric, type Trace, type TraceStep } from '../trace'

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
      {label}: <span className={m.recorded ? 'ms-num text-ink-2' : 'text-ink-3'}>{m.text}</span>
    </span>
  )
}

/**
 * The step timeline of one run. `shown` is how many steps the replay has revealed so far. Time, tokens and cost
 * are printed per step only as "not recorded" unless the step itself stored a value; the whole-run line carries
 * the run-level values that were stored.
 */
export function TraceView({
  trace,
  shown,
  label = 'Steps taken',
  replayed = true,
}: {
  trace: Trace
  shown: number
  label?: string
  /** True while a stored run is being replayed step by step; false when the whole stored run is shown at once. */
  replayed?: boolean
}) {
  const steps = trace.steps.slice(0, shown)
  const complete = shown >= trace.steps.length
  return (
    <details open className="rounded-md border border-rule bg-surface px-3 py-2 text-[15px]" data-testid="trace">
      <summary className="cursor-pointer py-1 font-semibold">How this was made ({trace.steps.length} steps)</summary>
      <ol className="m-0 mt-2 list-none p-0" aria-label={label}>
        {steps.map((s) => (
          <li key={s.id} data-step={s.kind} className="relative border-l-2 border-rule-strong pb-3 pl-4 last:pb-1">
            <span aria-hidden className={`absolute -left-[7px] top-[7px] h-3 w-3 rounded-full ${DOT[s.kind]}`} />
            <p className="m-0 flex flex-wrap items-center gap-2">
              <span className="font-semibold">{s.title}</span>
              <span className="ws-pill bg-sunk text-ink-2">{s.model ?? 'Plain code, no model'}</span>
            </p>
            <p className="ws-wrap m-0 mt-0.5 text-ink-2">{s.detail}</p>
            {s.lines.length > 0 && (
              <ul className="m-0 mt-1 list-disc pl-5 text-ink-2">
                {s.lines.map((l, i) => (
                  <li key={i} className="ws-wrap">
                    {l}
                  </li>
                ))}
              </ul>
            )}
            <p className="m-0 mt-1 flex flex-wrap gap-x-3 text-[14px] text-ink-3">
              <Val label="Time" m={s.time} />
              <Val label="Tokens" m={s.tokens} />
              <Val label="Cost" m={s.cost} />
            </p>
          </li>
        ))}
      </ol>
      {complete && (
        <p className="m-0 mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-rule pt-2 text-[14px] text-ink-2" data-testid="trace-run">
          <span className="font-semibold">Whole run</span>
          <Val label="Time" m={trace.usage.time} />
          <Val label="Tokens" m={trace.usage.tokens} />
          <Val label="Cost" m={trace.usage.cost} />
        </p>
      )}
      <p className="m-0 mt-2 flex gap-2 text-[14px] leading-snug text-ink-3">
        <Icon name="info" size={16} />
        <span>
          {replayed
            ? 'Replayed from a recording at an even pace. The pace is not the speed of the original run. '
            : 'Stored run. '}
          A value appears only where the recording stored it ({NOT_RECORDED} otherwise).
        </span>
      </p>
    </details>
  )
}
