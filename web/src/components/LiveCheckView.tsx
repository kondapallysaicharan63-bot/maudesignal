import { useState } from 'react'
import { isoDay, STREAMLIT_URL } from '../data'
import {
  browserStore,
  CHANGE_LABELS,
  checkDevice,
  checksUsed,
  reasonText,
  SESSION_CHECKS,
  type CheckOutcome,
  type LiveCheckResult,
} from '../liveCheck'

function Result({ r, cached }: { r: LiveCheckResult; cached: boolean }) {
  const flagged = r.classification !== 'stable'
  const label = CHANGE_LABELS[r.classification]
  const figure = r.classification === 'spike' && r.spike_ratio !== null ? `${r.spike_ratio.toFixed(2)}×` : String(r.current_count)
  const stats: [string, string][] = [
    ['This week', String(r.current_count)],
    ['Weekly mean before', r.baseline_weekly_mean.toFixed(2)],
    ['Injury / death this week', String(r.current_severe_count)],
    ['openFDA, all dates', (r.prior_report_count + r.current_count).toLocaleString('en-US')],
  ]
  return (
    <div className="mt-4" aria-live="polite">
      <article className={`rounded-md border p-4 ${flagged ? 'border-rule-strong bg-sunk' : 'border-rule bg-surface'}`}>
        <p className="ms-kicker m-0">Live from openFDA · {r.product_code}</p>
        <div className="mt-1 flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="t-title-lg m-0">{label.charAt(0).toUpperCase() + label.slice(1)}</h2>
          <span className="t-index ms-num">{figure}</span>
        </div>
        <p className="ws-wrap mt-2">
          <strong>{flagged ? 'Why it is flagged.' : 'Status.'}</strong> {reasonText(r)}
        </p>
        <p className="ws-wrap m-0 text-[14px] text-ink-3">
          {r.window
            ? `${isoDay(r.window.current_start)} to ${isoDay(r.window.current_end)} (the latest week on openFDA) against the 4 weeks before.`
            : 'No report in the last two years.'}
          {cached ? ' Saved in this browser from an earlier check (kept 6 hours).' : ''}
        </p>
      </article>
      <dl className="m-0 mt-3 grid grid-cols-2 gap-2">
        {stats.map(([k, v]) => (
          <div key={k} className="rounded-md border border-rule bg-surface p-3">
            <dt className="text-[14px] leading-snug text-ink-2">{k}</dt>
            <dd className="t-index ms-num m-0 mt-1">{v}</dd>
          </div>
        ))}
      </dl>
      <details className="mt-3" open>
        <summary className="min-h-10 cursor-pointer py-2 font-semibold">Where each number comes from (open the openFDA query)</summary>
        <ul className="m-0 list-none p-0">
          {r.queries.map(([name, url]) => (
            <li key={url} className="py-1">
              <a className="ws-wrap text-[15px] text-accent underline" href={url} target="_blank" rel="noreferrer">
                {name}
              </a>
            </li>
          ))}
        </ul>
      </details>
      <p className="mt-2 text-[13px] leading-snug text-ink-3">
        openFDA lags real time by weeks, so "this week" is the latest week it has. A triage signal for a person to review, not
        a finding.
      </p>
    </div>
  )
}

/** "Check any device type": the browser asks openFDA for counts and applies the four rules. */
export function LiveCheckView() {
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [out, setOut] = useState<CheckOutcome | null>(null)
  const [used, setUsed] = useState(() => checksUsed(browserStore('session')))

  const go = async () => {
    setBusy(true)
    const o = await checkDevice(code, {
      fetcher: (u) => fetch(u),
      session: browserStore('session'),
      local: browserStore('local'),
    })
    setOut(o)
    setUsed(o.used)
    setBusy(false)
  }

  return (
    <div>
      <p className="ms-kicker">Live from openFDA</p>
      <h1 className="t-title-lg m-0">Check any device type</h1>
      <p className="mt-2 max-w-xl text-ink-2">
        Type any FDA product code. Your browser asks openFDA for counts (no report text, no AI model, nothing sent to a
        MaudeSignal server) and applies the same four rules as the stored device types: a new kind of problem, more serious
        reports than usual, a sudden rise in reports, or no change.
      </p>
      <form
        className="mt-4 flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (!busy) void go()
        }}
      >
        <label className="block text-[14px] text-ink-3" htmlFor="live-code">
          Any FDA product code
          <input
            id="live-code"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/[^a-zA-Z]/g, '').slice(0, 3))}
            maxLength={3}
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            placeholder="e.g. LLZ, QIH, FLL"
            className="mt-1 block h-11 w-44 rounded-xs border border-rule-strong bg-surface px-3 text-[17px] uppercase text-ink placeholder:normal-case placeholder:text-ink-3"
          />
        </label>
        <button type="submit" disabled={busy || code.length !== 3} className="ms-btn ms-btn--primary" style={{ height: 44 }}>
          {busy ? 'Asking openFDA…' : 'Check on openFDA'}
        </button>
      </form>
      <p className="mt-2 text-[13px] text-ink-3">
        {used} of {SESSION_CHECKS} checks used in this browser session; a code checked in the last 6 hours is shown from this
        browser without asking again.
      </p>
      {out && !out.ok && (
        <div role="alert" className="ms-banner ms-banner--err mt-4">
          <div>
            <p className="ws-wrap m-0">{out.message}</p>
            {out.kind !== 'invalid' && out.kind !== 'limit' && (
              <p className="ws-wrap m-0 mt-1">
                No result is shown, because none was read from openFDA. The Streamlit app runs the same live check from its
                own server:{' '}
                <a className="font-semibold underline" href={STREAMLIT_URL} target="_blank" rel="noreferrer">
                  open the live check in the Streamlit app
                </a>
                .
              </p>
            )}
            {out.kind === 'limit' && (
              <p className="m-0 mt-1">
                <a className="font-semibold underline" href={STREAMLIT_URL} target="_blank" rel="noreferrer">
                  Open the Streamlit app
                </a>
              </p>
            )}
          </div>
        </div>
      )}
      {out?.ok && <Result r={out.result} cached={out.cached} />}
    </div>
  )
}
