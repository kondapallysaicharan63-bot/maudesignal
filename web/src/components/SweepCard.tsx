import { useAlertPanel } from '../alertPanelContext'
import { useState } from 'react'
import { CLASS_LABEL, flaggedRows } from '../artifacts'
import { isoDay } from '../data'
import { sweepRowId, sweepRuleText, sweepStats, sweepStatsText } from '../dashboard'
import { sweepWeek } from '../sweepLabel'
import type { Sweep } from '../types'
import { Pill } from './artifacts/common'

/** "2026-10-29" from the sweep's generated_utc. */
export const sweepDate = (s: Sweep): string => s.meta.generated_utc.slice(0, 10)

/** The rules behind "flagged", and how many codes were too quiet to flag (computed from the rows). */
export function SweepRules({ sweep, collapsed = false }: { sweep: Sweep; collapsed?: boolean }) {
  const r = sweepRuleText()
  const body = (
    <>
      <ul className="m-0 mt-2 list-disc space-y-1 pl-5 text-[17px] leading-snug text-ink-2">
        <li>{r.newKind}</li>
        <li>{r.spike}</li>
        <li>{r.serious}</li>
      </ul>
      <p className="m-0 mt-2 text-[17px] text-ink" data-testid="sweep-stats">
        {sweepStatsText(sweepStats(sweep))}
      </p>
    </>
  )
  return (
    <div className="mt-4 rounded-md border border-rule bg-sunk p-3" data-testid="sweep-rules">
      {collapsed ? (
        <details>
          <summary className="ms-kicker m-0 flex min-h-11 cursor-pointer list-none items-center justify-between gap-2 [&::-webkit-details-marker]:hidden">
            How a code is flagged <span className="text-accent normal-case tracking-normal" aria-hidden="true">Show rules ›</span>
          </summary>
          {body}
        </details>
      ) : (
        <>
          <h3 className="ms-kicker m-0">How a code is flagged</h3>
          {body}
        </>
      )}
    </div>
  )
}

/** Text cut to two lines with a More / Less button. */
function Clamped({ children }: { children: React.ReactNode }) {
  const [more, setMore] = useState(false)
  return (
    <div className="mt-2">
      <p className={['ws-wrap m-0 text-ink-2', more ? '' : 'line-clamp-2'].join(' ')}>{children}</p>
      <button
        type="button"
        className="min-h-11 text-[17px] font-semibold text-accent underline"
        aria-expanded={more}
        onClick={() => setMore((m) => !m)}
      >
        {more ? 'Less' : 'More'}
      </button>
    </div>
  )
}

/** Headline, when it was checked, and the three counts. On Home the paragraph is cut to two lines and the rules fold away. */
export function SweepHead({ sweep, compact = false }: { sweep: Sweep; compact?: boolean }) {
  const m = sweep.meta
  const flagged = flaggedRows(sweep)
  const checked = m.codes_checked
  const ofList = m.codes_on_list
  const para = (
    <>
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
    </>
  )
  return (
    <article className="rounded-md border border-rule-strong bg-surface p-4" aria-label="AI device sweep">
      <p className="ms-kicker m-0">Newest real data · AI device sweep</p>
      <h2 className="t-title-lg m-0 mt-2">
        <span className="ms-num">{flagged.length}</span> flagged of <span className="ms-num">{ofList}</span> product codes on
        FDA's AI-enabled device list
      </h2>
      {compact ? <Clamped>{para}</Clamped> : <p className="ws-wrap mt-2 text-ink-2">{para}</p>}
      <dl className="m-0 mt-3 grid grid-cols-3 gap-2">
        {(
          [
            ['Codes checked', `${checked}`],
            ['Flagged', `${flagged.length}`],
            ['Errors', `${m.errors}`],
          ] as const
        ).map(([k, v]) => (
          <div key={k} className="rounded-md border border-rule bg-paper p-3 max-sm:p-2">
            <dt className="text-[15px] leading-snug text-ink-2">{k}</dt>
            <dd className="t-index ms-num m-0 mt-1">{v}</dd>
          </div>
        ))}
      </dl>
      {compact && <SweepRules sweep={sweep} collapsed />}
    </article>
  )
}

/** The flagged product codes with their openFDA query links. */
export function SweepFlagged({ sweep, focusCode = null }: { sweep: Sweep; focusCode?: string | null }) {
  const m = sweep.meta
  const week = sweepWeek(sweep) ?? 'the latest openFDA week'
  const flagged = flaggedRows(sweep)
  const { openAlert } = useAlertPanel()
  return (
    <article className="rounded-md border border-rule-strong bg-surface p-4" aria-label="Flagged product codes">
      <h3 className="ms-kicker m-0">Flagged product codes · {flagged.length}</h3>
      {flagged.length === 0 ? (
        <p className="mt-2 text-ink-2">No product code was flagged in this sweep.</p>
      ) : (
        <ul className="m-0 mt-2 list-none p-0">
          {flagged.map((r) => (
            <li
              key={r.product_code}
              id={sweepRowId(r.product_code)}
              tabIndex={-1}
              data-focused={focusCode === r.product_code ? 'true' : undefined}
              className={[
                'scroll-mt-4 border-t border-rule py-3 first:border-t-0',
                focusCode === r.product_code ? 'rounded-md bg-accent-soft px-2 outline outline-2 outline-accent' : '',
              ].join(' ')}
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span>
                  <span className="ms-code mr-2">{r.product_code}</span>
                  <Pill tone={r.classification === 'spike' ? 'warn' : 'bad'}>
                    {CLASS_LABEL[r.classification] ?? r.classification}
                  </Pill>
                </span>
                <span className="ms-num text-ink-2">
                  {r.current_count} in {week} · {r.baseline_weekly_mean} a week on average in the 4 weeks before
                </span>
              </div>
              <button
                type="button"
                className="flex min-h-11 items-center text-[17px] font-semibold text-accent underline"
                onClick={() => openAlert(`sweep:${r.product_code}`, r.product_code)}
                aria-label={`Alert details for ${r.product_code}: ${CLASS_LABEL[r.classification] ?? r.classification}`}
                data-testid="sweep-alert-details"
              >
                Alert details
              </button>
              {r.queries && r.queries.length > 0 && (
                <details className="mt-1">
                  <summary className="min-h-11 cursor-pointer py-2 text-[17px] text-ink-2">
                    openFDA queries ({r.queries.length})
                  </summary>
                  <ul className="m-0 list-none p-0">
                    {r.queries.map(([label, url]) => (
                      <li key={url} className="py-1">
                        <a className="ws-wrap text-[17px] text-accent underline" href={url} target="_blank" rel="noreferrer">
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
      <p className="mt-3 text-[15px] leading-snug text-ink-2">
        A triage signal for a person to review, not a finding. Source:{' '}
        <a className="underline" href={m.source} target="_blank" rel="noreferrer">
          FDA's list of AI-enabled medical devices
        </a>
        .
      </p>
    </article>
  )
}

/** The AI device sweep workflow page: headline, rules, then the flagged codes. Every number comes from sweep.json. */
export function SweepCard({ sweep }: { sweep: Sweep }) {
  return (
    <div className="space-y-4">
      <SweepHead sweep={sweep} />
      <SweepRules sweep={sweep} />
      <SweepFlagged sweep={sweep} />
    </div>
  )
}
