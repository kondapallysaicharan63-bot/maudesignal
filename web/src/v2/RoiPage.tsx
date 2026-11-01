// F27 Time and cost: measured, not claimed. Route /roi (v2 layout).
// Part 1: what has been timed and recorded (web/public/data/measurements.json). Part 2: a calculator that runs on the
// person's own typed assumptions and labels its results that way. No figure on this page is written by the product.
import { useEffect, useMemo, useState } from 'react'
import {
  compute,
  EMPTY,
  fmt,
  forTask,
  JOBS,
  loadAssumptions,
  num,
  parseMeasurements,
  recordedMeans,
  saveAssumptions,
  slower,
  TASKS,
  type Assumptions,
  type Measurement,
  type Source,
} from './roi'
import './positioning.css'

const PENDING = 'Measurement pending'

/** Fetches measurements.json once; a failed or malformed file is the same as no measurements. */
export function useMeasurements(): { list: Measurement[]; loaded: boolean } {
  const [state, setState] = useState<{ list: Measurement[]; loaded: boolean }>({ list: [], loaded: false })
  useEffect(() => {
    let live = true
    fetch(`${import.meta.env.BASE_URL}data/measurements.json`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j: unknown) => live && setState({ list: parseMeasurements(j), loaded: true }))
      .catch(() => live && setState({ list: [], loaded: true }))
    return () => {
      live = false
    }
  }, [])
  return state
}

function Record({ m }: { m: Measurement }) {
  return (
    <div className="ms2-roi-rec" data-testid="roi-record">
      <dl className="ms2-roi-dl">
        <div>
          <dt>Who</dt>
          <dd>{m.who}</dd>
        </div>
        <div>
          <dt>When</dt>
          <dd>{m.when}</dd>
        </div>
        <div>
          <dt>How</dt>
          <dd>
            {m.how}
            {m.notes && <span className="ms2-muted block">{m.notes}</span>}
          </dd>
        </div>
        <div>
          <dt>Manual (minutes)</dt>
          <dd className="ms-num">{fmt(m.manual_minutes)}</dd>
        </div>
        <div>
          <dt>MaudeSignal (minutes)</dt>
          <dd className="ms-num">{fmt(m.maudesignal_minutes)}</dd>
        </div>
      </dl>
      {slower(m) && (
        <p className="ms2-roi-slow m-0" data-testid="roi-slower">
          MaudeSignal was slower in this recording.
        </p>
      )}
    </div>
  )
}

interface Field {
  key: keyof Assumptions
  label: string
  unit: string
}
const GROUPS: { title: string; fields: Field[] }[] = [
  {
    title: "Complaints: problems reported on other makers' devices of the same type",
    fields: [
      { key: 'complaints', label: 'Complaints', unit: 'per month' },
      { key: 'complaintManual', label: 'Manual, per complaint', unit: 'min' },
      { key: 'complaintTool', label: 'With MaudeSignal, per complaint', unit: 'min' },
    ],
  },
  {
    title: 'Trend reviews: weekly trend for a code',
    fields: [
      { key: 'trends', label: 'Trend reviews', unit: 'per month' },
      { key: 'trendManual', label: 'Manual, per review', unit: 'min' },
      { key: 'trendTool', label: 'With MaudeSignal, per review', unit: 'min' },
    ],
  },
  { title: 'Cost', fields: [{ key: 'hourly', label: 'Hourly cost of the person doing it', unit: '$/hour' }] },
]

function Calculator({ measurements }: { measurements: Measurement[] }) {
  const [init] = useState(() => loadAssumptions())
  const [a, setA] = useState<Assumptions>(init.a)
  const [source, setSource] = useState<Source>(init.source)
  const means = useMemo(() => recordedMeans(measurements), [measurements])
  const result = compute(a)
  const set = (k: keyof Assumptions, v: string) => {
    const next = { ...a, [k]: v }
    setA(next)
    setSource('assumptions')
    saveAssumptions(next, 'assumptions')
  }
  const useRecorded = () => {
    if (!means) return
    const next = { ...a }
    for (const j of JOBS) {
      const m = means[j.task]
      if (!m) continue
      next[j.manual] = fmt(m.manual)
      next[j.tool] = fmt(m.tool)
    }
    setA(next)
    setSource('recorded')
    saveAssumptions(next, 'recorded')
  }
  const clear = () => {
    setA(EMPTY)
    setSource('assumptions')
    saveAssumptions(EMPTY, 'assumptions')
  }
  const from = source === 'recorded' ? 'Minutes from recorded measurements; counts and cost from your assumptions' : 'from your assumptions'
  const neg = result !== null && result.hoursDiff < 0
  const diffLabel = neg ? 'Manual minus MaudeSignal (hours per month)' : 'Difference, hours per month'
  const costLabel = neg ? 'Manual minus MaudeSignal (cost per month)' : 'Difference in cost per month'
  return (
    <section className="ms2-card" aria-labelledby="roi-calc-h" data-testid="roi-calc">
      <h2 id="roi-calc-h" className="ms2-h2">
        Your assumptions — not a claim
      </h2>
      <p className="ms2-muted m-0 mt-1 text-[15px]">
        Type your own values. Nothing is filled in for you, nothing is sent anywhere, and this browser keeps them only on this device.
      </p>
      {GROUPS.map((g) => (
        <fieldset key={g.title} className="ms2-roi-group">
          <legend>{g.title}</legend>
          <div className="ms2-roi-fields">
            {g.fields.map((f) => (
              <label key={f.key} className="ms2-roi-field">
                <span>{f.label}</span>
                <span className="ms2-roi-inwrap">
                  <input
                    type="text"
                    inputMode="decimal"
                    autoComplete="off"
                    maxLength={12}
                    value={a[f.key]}
                    placeholder="enter yours"
                    aria-invalid={a[f.key] !== '' && num(a[f.key]) === null ? true : undefined}
                    onChange={(e) => set(f.key, e.target.value)}
                    data-testid={`roi-in-${f.key}`}
                  />
                  <span className="ms2-roi-unit" aria-hidden="true">
                    {f.unit}
                  </span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
      ))}
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="ms2-posbtn"
          onClick={useRecorded}
          disabled={!means}
          aria-disabled={!means}
          data-testid="roi-use-recorded"
        >
          Use recorded measurements
        </button>
        <button type="button" className="ms2-roi-clear" onClick={clear}>
          Clear
        </button>
        {!means && (
          <span className="ms2-muted text-[15px]" data-testid="roi-use-note">
            No recorded measurements for these two tasks yet, so there is nothing to use.
          </span>
        )}
      </div>
      <div className="mt-3" data-testid="roi-result">
        {result ? (
          <div>
            <p className="ms2-tag m-0" role="status" data-testid="roi-result-label">
              {from}
            </p>
            {neg && (
              <p className="ms2-roi-slow mt-2" data-testid="roi-result-slower">
                {source === 'recorded' ? 'MaudeSignal was slower in these recordings.' : 'MaudeSignal is slower in these numbers.'}
              </p>
            )}
            <dl className="ms2-stats mt-2">
              <div>
                <dt>Hours per month, manual</dt>
                <dd className="ms-num">{fmt(result.hoursManual)}</dd>
              </div>
              <div>
                <dt>Hours per month, with MaudeSignal</dt>
                <dd className="ms-num">{fmt(result.hoursTool)}</dd>
              </div>
              <div>
                <dt>{diffLabel}</dt>
                <dd className="ms-num">{fmt(result.hoursDiff)}</dd>
              </div>
              {result.cost !== null && (
                <div>
                  <dt>{costLabel}</dt>
                  <dd className="ms-num">{fmt(result.cost)}</dd>
                </div>
              )}
            </dl>
          </div>
        ) : (
          <p className="ms2-muted m-0 text-[15px]">
            Results appear when one task has its monthly count and both minutes typed. Add an hourly cost to see a cost.
          </p>
        )}
      </div>
    </section>
  )
}

/** The page. `measurements` is given by tests; otherwise measurements.json is fetched. */
export function RoiPage({ measurements, onHome }: { measurements?: Measurement[]; onHome?: () => void }) {
  const fetched = useMeasurements()
  const list = measurements ?? fetched.list
  const any = TASKS.some((t) => forTask(list, t.id).length > 0)
  return (
    <div className="ms2-pos" data-testid="roi-page">
      {onHome && (
        <nav aria-label="Breadcrumb" className="ms2-crumb">
          <button type="button" className="ms2-quietlink" onClick={onHome} data-testid="crumb-home">
            ← Home
          </button>
        </nav>
      )}
      <header className="ms2-pagehead">
        <h1 className="ms2-h1">Time and cost: measured, not claimed</h1>
        <p className="ms2-lead">
          A time or cost figure appears here only when a person typed it as their own assumption, or when a timing test was recorded with who ran it, when and how.
        </p>
      </header>

      <section aria-labelledby="roi-rec-h" className="ms2-card">
        <div className="ms2-roi-head">
          <h2 id="roi-rec-h" className="ms2-h2">
            Recorded measurements
          </h2>
          {!any && (
            <span className="ms2-tag" data-testid="roi-pending-chip">
              Pending
            </span>
          )}
        </div>
        <p className="ms2-muted m-0 mt-1 text-[15px]" data-testid="roi-timing-note">
          Timing tests by whoever runs them, to be recorded here with their name, the date and how they timed it.
        </p>
        <ul className="ms2-roi-tasks" aria-label="Timing tests by task">
          {TASKS.map((t) => {
            const rows = forTask(list, t.id)
            return (
              <li key={t.id} data-testid={`roi-task-${t.id}`}>
                <h3 className="ms2-roi-task">{t.label}</h3>
                {rows.length === 0 ? (
                  <p className="ms2-muted m-0" data-testid={`roi-pending-${t.id}`}>
                    {PENDING}
                  </p>
                ) : (
                  rows.map((m) => <Record key={m.id} m={m} />)
                )}
              </li>
            )
          })}
        </ul>
      </section>

      <div className="mt-6">
        <Calculator measurements={list} />
      </div>
    </div>
  )
}
