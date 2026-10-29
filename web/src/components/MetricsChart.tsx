import { pct, runMetrics, usd, type RunMetric } from '../dashboard'
import type { Thread } from '../types'

const W = 100
const H = 40

function Axis({ top, unit }: { top: string; unit?: string }) {
  return (
    <div className="flex w-12 shrink-0 flex-col justify-between text-right text-[13px] leading-none text-ink-3 ms-num" aria-hidden="true">
      <span>{top}</span>
      <span>0{unit ?? ''}</span>
    </div>
  )
}

/** Bars drawn to scale from zero. `null` values draw no bar (the value was not recorded). */
function Bars({ values, ids, max, label }: { values: (number | null)[]; ids: string[]; max: number; label: string }) {
  const n = values.length
  const slot = W / Math.max(n, 1)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" overflow="visible" className="h-28 w-full" role="img" aria-label={label}>
      <line x1="0" x2={W} y1={H / 2} y2={H / 2} stroke="var(--rule)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      {values.map((v, i) =>
        v === null || max === 0 ? null : (
          <rect key={ids[i]} x={i * slot + slot * 0.12} width={slot * 0.76} y={H - (v / max) * H} height={(v / max) * H} fill="var(--accent)">
            <title>{`${ids[i]}: ${v}`}</title>
          </rect>
        ),
      )}
      <line x1="0" x2={W} y1={H} y2={H} stroke="var(--rule-strong)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

/** Two lines on a 0 to 100% scale; a missing point breaks the line. */
function Lines({ series, n, label }: { series: { name: string; color: string; values: (number | null)[] }[]; n: number; label: string }) {
  const slot = W / Math.max(n, 1)
  const x = (i: number) => i * slot + slot / 2
  const y = (v: number) => H - v * H
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" overflow="visible" className="h-28 w-full" role="img" aria-label={label}>
      <line x1="0" x2={W} y1={H / 2} y2={H / 2} stroke="var(--rule)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      <line x1="0" x2={W} y1={H} y2={H} stroke="var(--rule-strong)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      {series.map((s) => {
        const segs: string[][] = []
        let cur: string[] = []
        s.values.forEach((v, i) => {
          if (v === null) {
            if (cur.length) segs.push(cur)
            cur = []
          } else cur.push(`${x(i)},${y(v)}`)
        })
        if (cur.length) segs.push(cur)
        return segs.map((pts, k) => (
          <polyline
            key={`${s.name}${k}`}
            points={pts.join(' ')}
            fill="none"
            stroke={s.color}
            strokeWidth={s.name === 'First pass' ? 5 : 2.5}
            strokeDasharray={s.name === 'First pass' ? '4 3' : undefined}
            vectorEffect="non-scaling-stroke"
            strokeLinejoin="round"
          />
        ))
      })}
    </svg>
  )
}

function ChartCard({ title, summary, children }: { title: string; summary: string; children: React.ReactNode }) {
  return (
    <figure className="m-0 rounded-md border border-rule bg-paper p-3">
      <figcaption className="text-[15px] font-semibold">{title}</figcaption>
      <p className="m-0 mt-1 text-[15px] leading-snug text-ink-2 ws-wrap">{summary}</p>
      <div className="mt-2">{children}</div>
    </figure>
  )
}

/**
 * Small charts over the recorded runs (threads.json): answers, gate pass rate, cost, speed.
 * Speed is drawn only if the recordings stored a duration; otherwise it says so.
 */
export function MetricsChart({ threads }: { threads: Thread[] }) {
  const m: RunMetric[] = runMetrics(threads)
  const ids = m.map((r) => r.id)
  const n = m.length
  const answers = m.map((r) => r.answers)
  const maxA = Math.max(0, ...answers)
  const costs = m.map((r) => r.costUsd)
  const costVals = costs.filter((c): c is number => c !== null)
  const maxC = Math.max(0, ...costVals)
  const durs = m.map((r) => r.durationS)
  const durVals = durs.filter((d): d is number => d !== null)
  const maxD = Math.max(0, ...durVals)
  const fp = threads.reduce((a, t) => a + (t.first_pass?.passed ?? 0), 0)
  const fpAll = threads.reduce((a, t) => a + (t.first_pass ? t.first_pass.passed + t.first_pass.blocked : 0), 0)
  const finPass = m.reduce((a, r) => a + r.answers, 0)
  const finAll = m.reduce((a, r) => a + r.sentences, 0)

  return (
    <div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <ChartCard
          title="Answers per run"
          summary={`${finPass} sentences shown across ${n} recorded runs (most in one run: ${maxA}).`}
        >
          <div className="flex gap-2">
            <Axis top={`${maxA}`} />
            <div className="min-w-0 flex-1">
              <Bars values={answers} ids={ids} max={maxA} label={`Sentences shown per recorded run, ${n} runs, scale 0 to ${maxA}`} />
            </div>
          </div>
        </ChartCard>
        <ChartCard
          title="Gate pass rate"
          summary={`First pass ${fp} of ${fpAll} sentences (${fpAll ? pct(fp / fpAll) : 'not recorded'}). Final ${finPass} of ${finAll} (${finAll ? pct(finPass / finAll) : 'not recorded'})`}
        >
          <div className="flex gap-2">
            <Axis top="100%" />
            <div className="min-w-0 flex-1">
              <Lines
                n={n}
                label={`Gate pass rate per recorded run, first pass and final, scale 0 to 100 percent, ${n} runs`}
                series={[
                  { name: 'First pass', color: 'var(--warning)', values: m.map((r) => r.firstPass) },
                  { name: 'Final', color: 'var(--success)', values: m.map((r) => r.finalPass) },
                ]}
              />
            </div>
          </div>
          <p className="m-0 mt-1 flex flex-wrap gap-x-4 text-[14px] text-ink-2">
            <span>
              <span aria-hidden="true" style={{ color: 'var(--warning)' }}>
                - -{' '}
              </span>
              First pass
            </span>
            <span>
              <span aria-hidden="true" style={{ color: 'var(--success)' }}>
                ——{' '}
              </span>
              Final
            </span>
          </p>
        </ChartCard>
        <ChartCard
          title="Cost per run"
          summary={
            costVals.length === 0
              ? 'Cost not recorded.'
              : `${usd(costVals.reduce((a, b) => a + b, 0))} in total over ${costVals.length} runs; most in one run: ${usd(maxC)}.${costVals.length < n ? ` ${n - costVals.length} runs have no cost recorded.` : ''}`
          }
        >
          {costVals.length > 0 && (
            <div className="flex gap-2">
              <Axis top={usd(maxC)} />
              <div className="min-w-0 flex-1">
                <Bars values={costs} ids={ids} max={maxC} label={`Cost in US dollars per recorded run, scale 0 to ${usd(maxC)}`} />
              </div>
            </div>
          )}
        </ChartCard>
        <ChartCard
          title="Speed per run"
          summary={
            durVals.length === 0
              ? 'Not recorded: the stored runs do not include how long each took.'
              : `Longest run: ${maxD} s. ${durVals.length < n ? `${n - durVals.length} runs have no duration recorded.` : ''}`
          }
        >
          {durVals.length > 0 && (
            <div className="flex gap-2">
              <Axis top={`${maxD} s`} />
              <div className="min-w-0 flex-1">
                <Bars values={durs} ids={ids} max={maxD} label={`Seconds per recorded run, scale 0 to ${maxD}`} />
              </div>
            </div>
          )}
        </ChartCard>
      </div>
      <p className="m-0 mt-2 text-[14px] leading-snug text-ink-3">
        {n} recorded runs, oldest to newest, left to right. Each bar or point is one run; hover a bar for its id.
      </p>
    </div>
  )
}
