import { CLASS_LABEL, flaggedRows } from '../../artifacts'
import type { Brief, Sweep } from '../../types'
import { Empty, Pill, Segmented } from './common'

const COUNT_LABELS: [keyof Brief['counts'], string][] = [
  ['new', 'New kind of problem'],
  ['more_serious_than_usual', 'More serious than usual'],
  ['reports_suddenly_increased', 'Reports suddenly increased'],
  ['stable', 'No change'],
]

/** Daily briefs from briefs.json, newest first. */
export function BriefTab({
  briefs,
  date,
  onDate,
}: {
  briefs: Brief[]
  date: string | null
  onDate: (d: string) => void
}) {
  if (briefs.length === 0) return <Empty title="No daily briefs stored yet" />
  const b = briefs.find((x) => x.date === date) ?? briefs[0]
  return (
    <article>
      <p className="ms-kicker">Daily brief</p>
      {briefs.length > 1 && (
        <div className="mt-2">
          <Segmented
            label="Choose a daily brief"
            value={b.date}
            options={briefs.map((x) => ({ id: x.date, label: x.date }))}
            onChange={onDate}
          />
        </div>
      )}
      <h2 className="t-title-lg ms-num m-0 mt-3">{b.date}</h2>
      <p className="ws-wrap mt-2 text-ink-2">{b.headline}</p>
      <p className="m-0 text-[14px] text-ink-3">
        Week {b.window.current_start} to {b.window.current_end}, compared with {b.window.baseline_start} to{' '}
        {b.window.baseline_end}.
      </p>
      <dl className="m-0 mt-4 grid grid-cols-2 gap-2">
        {COUNT_LABELS.map(([k, label]) => (
          <div key={k} className="rounded-md border border-rule bg-surface p-3">
            <dt className="text-[14px] leading-snug text-ink-2">{label}</dt>
            <dd className="t-index ms-num m-0 mt-1">{b.counts[k]}</dd>
          </div>
        ))}
      </dl>
      <h3 className="ms-kicker mt-6">Device types · {b.signals.length}</h3>
      <ul className="m-0 mt-2 list-none p-0">
        {b.signals.map((s) => (
          <li key={s.product_code} className="flex items-baseline justify-between gap-3 border-t border-rule py-2">
            <span>
              <span className="ms-code mr-2">{s.product_code}</span>
              {s.label}
            </span>
            <span className="ms-num shrink-0 text-ink-2">{s.current_count} this week</span>
          </li>
        ))}
      </ul>
      {b.footer && <p className="ws-wrap mt-4 text-[13px] leading-snug text-ink-3">{b.footer}</p>}
    </article>
  )
}

/** Signal digest: the stored AI device sweep (sweep.json) with the openFDA queries behind each flag. */
export function DigestTab({ sweep, brief }: { sweep: Sweep; brief: Brief | null }) {
  const flagged = flaggedRows(sweep)
  const m = sweep.meta
  return (
    <article>
      <p className="ms-kicker">Signal digest</p>
      {brief && (
        <p className="ws-wrap mt-2 text-ink-2">
          Daily brief {brief.date}: {brief.headline}
        </p>
      )}
      <h2 className="t-title-lg m-0 mt-4">AI device sweep</h2>
      <p className="ws-wrap mt-1 text-ink-2">
        Every product code on FDA's AI-enabled device list, openFDA counts saved at <span className="ms-num">{m.generated_utc}</span>: week{' '}
        <span className="ms-num">
          {m.window.current_start} to {m.window.current_end}
        </span>{' '}
        against the 4 weeks before. This is a different week from the daily brief above.
      </p>
      <dl className="m-0 mt-3 grid grid-cols-3 gap-2">
        {(
          [
            ['Codes checked', `${m.codes_checked}`],
            ['Flagged', `${flagged.length}`],
            ['Errors', `${m.errors}`],
          ] as const
        ).map(([k, v]) => (
          <div key={k} className="rounded-md border border-rule bg-surface p-3">
            <dt className="text-[14px] leading-snug text-ink-2">{k}</dt>
            <dd className="t-index ms-num m-0 mt-1">{v}</dd>
          </div>
        ))}
      </dl>
      <h3 className="ms-kicker mt-6">Flagged product codes · {flagged.length}</h3>
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
    </article>
  )
}
