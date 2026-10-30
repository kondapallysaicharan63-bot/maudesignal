import { pct, runMetrics, usd, type RunMetric } from '../dashboard'
import type { Thread } from '../types'

const W = 100
const H = 40

// Series colours are design-system tokens: neutral ink for counts, success for the final gate result.
const BAR = 'var(--ink-2)'
const FIRST = 'var(--ink-2)'
const FINAL = 'var(--success)'

/** Axis labels from top to bottom (three ticks: top, middle, bottom). */
function Axis({ ticks }: { ticks: [string, string, string] }) {
  return (
    <div className="ms-num flex w-14 shrink-0 flex-col justify-between text-right text-[14px] leading-none text-ink-2" aria-hidden="true">
      {ticks.map((t, i) => (
        <span key={i}>{t}</span>
      ))}
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
          <rect key={ids[i]} x={i * slot + slot * 0.12} width={slot * 0.76} y={H - (v / max) * H} height={(v / max) * H} fill={BAR}>
            <title>{`${ids[i]}: ${v}`}</title>
          </rect>
        ),
      )}
      <line x1="0" x2={W} y1={H} y2={H} stroke="var(--rule-strong)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

/** Lines between `lo` and 1 (a share of sentences); a missing point breaks the line. No point markers. */
function Lines({
  series,
  n,
  lo,
  label,
}: {
  series: { name: string; color: string; dash?: string; width: number; values: (number | null)[] }[]
  n: number
  lo: number
  label: string
}) {
  const slot = W / Math.max(n, 1)
  const x = (i: number) => i * slot + slot / 2
  const y = (v: number) => H - ((v - lo) / (1 - lo)) * H
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
            strokeWidth={s.width}
            strokeDasharray={s.dash}
            vectorEffect="non-scaling-stroke"
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))
      })}
    </svg>
  )
}

function ChartCard({ title, summary, children, wide = false }: { title: string; summary: string; children?: React.ReactNode; wide?: boolean }) {
  return (
    <figure className={['m-0 rounded-md border border-rule bg-paper p-3', wide ? 'lg:col-span-2' : ''].join(' ')}>
      <figcaption className="text-[17px] font-semibold">{title}</figcaption>
      <p className="ws-wrap m-0 mt-1 text-[16px] leading-snug text-ink-2">{summary}</p>
      {children && <div className="mt-2">{children}</div>}
    </figure>
  )
}

/** Oldest and newest run ids under a chart, so the horizontal direction is labelled. */
function XLabels({ first, last }: { first: string; last: string }) {
  return (
    <div className="ms-num mt-1 flex justify-between gap-2 pl-16 text-[14px] text-ink-2" aria-hidden="true">
      <span className="truncate">{first}</span>
      <span className="truncate text-right">{last}</span>
    </div>
  )
}

/**
 * Small charts over the recorded runs (threads.json): answers, gate pass rate, cost. Speed is drawn only
 * if the recordings stored a duration; otherwise a one-line note says it was not recorded.
 */
export function MetricsChart({ threads }: { threads: Thread[] }) {
  const m: RunMetric[] = runMetrics(threads)
  const ids = m.map((r) => r.id)
  const n = m.length
  const first = ids[0] ?? ''
  const last = ids[n - 1] ?? ''
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
  // The gate chart's floor: 90% unless a run is lower, then the next whole ten below it.
  const rates = m.flatMap((r) => [r.firstPass, r.finalPass]).filter((v): v is number => v !== null)
  const lo = Math.min(0.9, Math.floor(Math.min(1, ...rates) * 10) / 10)
  const lastRun = m[n - 1]

  return (
    <div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <ChartCard
          title="Answers per run"
          summary={`${finPass} sentences shown across ${n} recorded runs (most in one run: ${maxA}). Latest run: ${lastRun?.answers ?? 0}.`}
        >
          <div className="flex gap-2">
            <Axis ticks={[`${maxA}`, `${Math.round((maxA / 2) * 10) / 10}`, '0']} />
            <div className="min-w-0 flex-1">
              <Bars values={answers} ids={ids} max={maxA} label={`Sentences shown per recorded run, ${n} runs, scale 0 to ${maxA}`} />
            </div>
          </div>
          <XLabels first={first} last={last} />
        </ChartCard>
        <ChartCard
          title="Gate pass rate"
          summary={`First pass ${fp} of ${fpAll} sentences (${fpAll ? pct(fp / fpAll) : 'not recorded'}). Final ${finPass} of ${finAll} (${finAll ? pct(finPass / finAll) : 'not recorded'}). Axis starts at ${Math.round(lo * 100)}%.`}
        >
          <div className="flex gap-2">
            <Axis ticks={['100%', `${Math.round(((1 + lo) / 2) * 1000) / 10}%`, `${Math.round(lo * 100)}%`]} />
            <div className="min-w-0 flex-1">
              <Lines
                n={n}
                lo={lo}
                label={`Gate pass rate per recorded run, first pass and final, scale ${Math.round(lo * 100)} to 100 percent, ${n} runs`}
                series={[
                  { name: 'First pass', color: FIRST, dash: '7 5', width: 2, values: m.map((r) => r.firstPass) },
                  { name: 'Final', color: FINAL, width: 3, values: m.map((r) => r.finalPass) },
                ]}
              />
            </div>
          </div>
          <XLabels first={first} last={last} />
          <p className="m-0 mt-1 flex flex-wrap gap-x-4 text-[16px] text-ink-2">
            <span>
              <span aria-hidden="true" style={{ color: FIRST }}>
                - - -{' '}
              </span>
              First pass
            </span>
            <span>
              <span aria-hidden="true" style={{ color: FINAL }}>
                ——{' '}
              </span>
              Final
            </span>
          </p>
        </ChartCard>
        <ChartCard
          wide
          title="Cost per run"
          summary={
            costVals.length === 0
              ? 'Cost not recorded.'
              : `${usd(costVals.reduce((a, b) => a + b, 0))} in total over ${costVals.length} runs; most in one run: ${usd(maxC)}.${lastRun?.costUsd != null ? ` Latest run: ${usd(lastRun.costUsd)}.` : ''}${costVals.length < n ? ` ${n - costVals.length} runs have no cost recorded.` : ''}`
          }
        >
          {costVals.length > 0 && (
            <>
              <div className="flex gap-2">
                <Axis ticks={[usd(maxC), usd(maxC / 2), '$0']} />
                <div className="min-w-0 flex-1">
                  <Bars values={costs} ids={ids} max={maxC} label={`Cost in US dollars per recorded run, scale 0 to ${usd(maxC)}`} />
                </div>
              </div>
              <XLabels first={first} last={last} />
            </>
          )}
        </ChartCard>
        {durVals.length > 0 && (
          <ChartCard
            wide
            title="Speed per run"
            summary={`Longest run: ${maxD} s. ${durVals.length < n ? `${n - durVals.length} runs have no duration recorded.` : ''}`}
          >
            <div className="flex gap-2">
              <Axis ticks={[`${maxD} s`, `${Math.round((maxD / 2) * 10) / 10} s`, '0 s']} />
              <div className="min-w-0 flex-1">
                <Bars values={durs} ids={ids} max={maxD} label={`Seconds per recorded run, scale 0 to ${maxD}`} />
              </div>
            </div>
            <XLabels first={first} last={last} />
          </ChartCard>
        )}
      </div>
      {durVals.length === 0 && (
        <p className="m-0 mt-3 text-[16px] leading-snug text-ink-2" data-testid="speed-note">
          <strong>Speed per run:</strong> Not recorded: the stored runs do not include how long each took.
        </p>
      )}
      <p className="m-0 mt-2 text-[16px] leading-snug text-ink-2">
        {n} recorded runs, oldest to newest, left to right. Each bar or point is one run; hover a bar for its id.
      </p>
    </div>
  )
}
