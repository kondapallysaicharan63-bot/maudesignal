import { CLASS_LABEL, flaggedRows } from '../artifacts'
import { isoDay } from '../data'
import type { Sweep } from '../types'
import { Pill } from './artifacts/common'

/** "2026-10-29" from the sweep's generated_utc. */
export const sweepDate = (s: Sweep): string => s.meta.generated_utc.slice(0, 10)

/**
 * The AI device sweep (sweep.json): how many product codes on FDA's AI-enabled device list were flagged,
 * with the flagged codes and the openFDA query links behind each. Every number comes from the file.
 */
export function SweepCard({ sweep, heading = true }: { sweep: Sweep; heading?: boolean }) {
  const m = sweep.meta
  const flagged = flaggedRows(sweep)
  const checked = m.codes_checked
  const ofList = m.codes_on_list
  return (
    <article className="rounded-md border border-rule-strong bg-surface p-4" aria-label="AI device sweep">
      <p className="ms-kicker m-0">Newest real data · AI device sweep</p>
      {heading && (
        <h2 className="t-title-lg m-0 mt-2">
          <span className="ms-num">{flagged.length}</span> flagged of <span className="ms-num">{ofList}</span> product codes
          on FDA's AI-enabled device list
        </h2>
      )}
      <p className="ws-wrap mt-2 text-ink-2">
        Checked <span className="ms-num">{sweepDate(sweep)}</span> against openFDA, counts only.
        {checked !== ofList && (
          <>
            {' '}
            <span className="ms-num">{checked}</span> of {ofList} codes could be checked ({m.errors} errors).
          </>
        )}{' '}
        openFDA's latest week is{' '}
        <span className="ms-num">
          {isoDay(m.window.current_start)} to {isoDay(m.window.current_end)}
        </span>
        , compared with the 4 weeks before (
        <span className="ms-num">
          {isoDay(m.window.baseline_start)} to {isoDay(m.window.baseline_end)}
        </span>
        ). openFDA lags real time by weeks.
      </p>
      <dl className="m-0 mt-3 grid grid-cols-3 gap-2">
        {(
          [
            ['Codes checked', `${checked}`],
            ['Flagged', `${flagged.length}`],
            ['Errors', `${m.errors}`],
          ] as const
        ).map(([k, v]) => (
          <div key={k} className="rounded-md border border-rule bg-paper p-3">
            <dt className="text-[14px] leading-snug text-ink-2">{k}</dt>
            <dd className="t-index ms-num m-0 mt-1">{v}</dd>
          </div>
        ))}
      </dl>
      <h3 className="ms-kicker mt-5">Flagged product codes · {flagged.length}</h3>
      {flagged.length === 0 ? (
        <p className="mt-2 text-ink-2">No product code was flagged in this sweep.</p>
      ) : (
        <ul className="m-0 mt-2 list-none p-0">
          {flagged.map((r) => (
            <li key={r.product_code} className="border-t border-rule py-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span>
                  <span className="ms-code mr-2">{r.product_code}</span>
                  <Pill tone={r.classification === 'spike' ? 'warn' : 'bad'}>
                    {CLASS_LABEL[r.classification] ?? r.classification}
                  </Pill>
                </span>
                <span className="ms-num text-ink-2">
                  {r.current_count} this week · {r.baseline_weekly_mean} a week on average in the 4 weeks before
                </span>
              </div>
              {r.queries && r.queries.length > 0 && (
                <details className="mt-1">
                  <summary className="min-h-10 cursor-pointer py-2 text-[15px] text-ink-2">
                    openFDA queries ({r.queries.length})
                  </summary>
                  <ul className="m-0 list-none p-0">
                    {r.queries.map(([label, url]) => (
                      <li key={url} className="py-1">
                        <a className="ws-wrap text-[15px] text-accent underline" href={url} target="_blank" rel="noreferrer">
                          {label}
                        </a>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-[13px] leading-snug text-ink-3">
        A triage signal for a person to review, not a finding. Source:{' '}
        <a className="underline" href={m.source} target="_blank" rel="noreferrer">
          FDA's list of AI-enabled medical devices
        </a>
        .
      </p>
    </article>
  )
}
