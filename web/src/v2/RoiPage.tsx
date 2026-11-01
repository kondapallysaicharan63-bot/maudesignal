// F27 Time and cost: measured, not claimed. Route /roi (v2 layout).
// Part 1: what has been timed and recorded (web/public/data/measurements.json). Part 2: a calculator that runs on the
// person's own typed assumptions and labels its results that way. No figure on this page is written by the product.
import { useEffect, useMemo, useState } from 'react'
import {
  compute,
  EMPTY,
  fmt,
  forTask,
  loadAssumptions,
  num,
  parseMeasurements,
  recordedMeans,
  saveAssumptions,
  TASKS,
  type Assumptions,
  type Measurement,
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

function TaskTable({ id, label, rows }: { id: string; label: string; rows: Measurement[] }) {
  return (
    <section className="ms2-card" aria-labelledby={`roi-${id}-h`} data-testid={`roi-task-${id}`}>
      <h3 id={`roi-${id}-h`} className="ms2-h2">
        {label}
      </h3>
      <div className="ms2-tablewrap" role="region" aria-label={`Recorded timing tests: ${label}`} tabIndex={0}>
        <table className="ms2-table ms2-roi-table">
          <caption className="sr-only">Recorded timing tests: {label}</caption>
          <thead>
            <tr>
              <th scope="col">Who</th>
              <th scope="col">When</th>
              <th scope="col">How</th>
              <th scope="col">Manual (minutes)</th>
              <th scope="col">MaudeSignal (minutes)</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={5} className="ms2-muted" data-testid={`roi-pending-${id}`}>
                  {PENDING}
                </td>
              </tr>
            ) : (
              rows.map((m) => (
                <tr key={m.id}>
                  <td>{m.who}</td>
                  <td>{m.when}</td>
                  <td>
                    {m.how}
                    {m.notes && <span className="ms2-muted block">{m.notes}</span>}
                  </td>
                  <td className="ms-num">{fmt(m.manual_minutes)}</td>
                  <td className="ms-num">{fmt(m.maudesignal_minutes)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}

const FIELDS: { key: keyof Assumptions; label: string }[] = [
  { key: 'complaints', label: 'Complaints per month' },
  { key: 'trends', label: 'Trend reviews per month' },
  { key: 'hourly', label: 'Hourly cost of the person doing it' },
  { key: 'manual', label: 'Minutes per task, done manually' },
  { key: 'tool', label: 'Minutes per task, with MaudeSignal' },
]

function Calculator({ measurements }: { measurements: Measurement[] }) {
  const [a, setA] = useState<Assumptions>(() => loadAssumptions())
  const [source, setSource] = useState<'assumptions' | 'recorded'>('assumptions')
  const means = useMemo(() => recordedMeans(measurements), [measurements])
  const result = compute(a)
  const set = (k: keyof Assumptions, v: string) => {
    const next = { ...a, [k]: v }
    setA(next)
    setSource('assumptions')
    saveAssumptions(next)
  }
  const useRecorded = () => {
    if (!means) return
    const next = { ...a, manual: fmt(means.manual), tool: fmt(means.tool) }
    setA(next)
    setSource('recorded')
    saveAssumptions(next)
  }
  const clear = () => {
    setA(EMPTY)
    setSource('assumptions')
    saveAssumptions(EMPTY)
  }
  const from = source === 'recorded' ? 'minutes from recorded measurements, counts and cost from your assumptions' : 'from your assumptions'
  return (
    <section className="ms2-card" aria-labelledby="roi-calc-h" data-testid="roi-calc">
      <h2 id="roi-calc-h" className="ms2-h2">
        Your assumptions — not a claim
      </h2>
      <p className="ms2-muted m-0 mt-1 text-[15px]">
        Type your own values. Nothing is filled in for you, nothing is sent anywhere, and this browser keeps them only on this device.
      </p>
      <div className="ms2-roi-fields mt-3">
        {FIELDS.map((f) => (
          <label key={f.key} className="ms2-roi-field">
            <span>{f.label}</span>
            <input
              type="text"
              inputMode="decimal"
              autoComplete="off"
              value={a[f.key]}
              placeholder="enter yours"
              aria-invalid={a[f.key] !== '' && num(a[f.key]) === null ? true : undefined}
              onChange={(e) => set(f.key, e.target.value)}
              data-testid={`roi-in-${f.key}`}
            />
          </label>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button type="button" className="ms2-posbtn" onClick={useRecorded} disabled={!means} data-testid="roi-use-recorded">
          Use recorded measurements
        </button>
        <button type="button" className="ms2-quietlink" onClick={clear}>
          Clear
        </button>
        {!means && (
          <span className="ms2-muted text-[15px]" data-testid="roi-use-note">
            No recorded measurements yet, so there is nothing to use.
          </span>
        )}
      </div>
      <div className="mt-3" role="status" aria-live="polite" data-testid="roi-result">
        {result ? (
          <div>
            <p className="ms2-tag m-0" data-testid="roi-result-label">
              {from}
            </p>
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
                <dt>Difference, hours per month</dt>
                <dd className="ms-num">{fmt(result.hoursDiff)}</dd>
              </div>
              {result.cost !== null && (
                <div>
                  <dt>Difference in cost per month</dt>
                  <dd className="ms-num">{fmt(result.cost)}</dd>
                </div>
              )}
            </dl>
          </div>
        ) : (
          <p className="ms2-muted m-0 text-[15px]">
            Results appear when you have typed the minutes for both ways and at least one monthly count. Add an hourly cost to see a cost.
          </p>
        )}
      </div>
    </section>
  )
}

/** The page. `measurements` is given by tests; otherwise measurements.json is fetched. */
export function RoiPage({ measurements }: { measurements?: Measurement[] }) {
  const fetched = useMeasurements()
  const list = measurements ?? fetched.list
  return (
    <div className="ms2-pos" data-testid="roi-page">
      <header className="ms2-pagehead">
        <h1 className="ms2-h1">Time and cost: measured, not claimed</h1>
        <p className="ms2-lead">
          A time or cost figure appears here only when a person typed it as their own assumption, or when a timing test was recorded with who ran it, when and how.
        </p>
      </header>

      <section aria-labelledby="roi-rec-h">
        <h2 id="roi-rec-h" className="ms2-h2">
          Recorded measurements
        </h2>
        <p className="ms2-muted m-0 mt-1 text-[15px]" data-testid="roi-timing-note">
          Timing tests by whoever runs them, to be recorded here with their name, the date and how they timed it.
        </p>
        <div className="ms2-roi-tasks mt-3">
          {TASKS.map((t) => (
            <TaskTable key={t.id} id={t.id} label={t.label} rows={forTask(list, t.id)} />
          ))}
        </div>
      </section>

      <div className="mt-6">
        <Calculator measurements={list} />
      </div>
    </div>
  )
}
