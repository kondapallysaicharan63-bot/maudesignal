import { isoDay } from '../../data'
import type { Brief, Sweep } from '../../types'
import { SweepCard } from '../SweepCard'
import { Empty, Segmented } from './common'

const COUNT_LABELS: [keyof Brief['counts'], string][] = [
  ['new', 'New kind of problem'],
  ['more_serious_than_usual', 'More serious than usual'],
  ['reports_suddenly_increased', 'Reports suddenly increased'],
  ['stable', 'No change'],
]

/** Daily briefs from briefs.json, newest first. They are built from the demo database, so they say so. */
export function BriefTab({
  briefs,
  date,
  onDate,
  snapshot,
}: {
  briefs: Brief[]
  date: string | null
  onDate: (d: string) => void
  /** e.g. "Demo snapshot · reports to 2026-08-31" */
  snapshot: string
}) {
  if (briefs.length === 0) return <Empty title="No daily briefs stored yet" />
  const b = briefs.find((x) => x.date === date) ?? briefs[0]
  return (
    <article>
      <p className="ms-kicker">Daily brief · demo snapshot</p>
      <p className="ms-banner ms-banner--warn mt-2 text-[15px]">
        <span className="ws-wrap">
          <strong>{snapshot}.</strong> This brief was made from the demo database for the week{' '}
          <span className="ms-num">
            {isoDay(b.window.current_start)} to {isoDay(b.window.current_end)}
          </span>
          . It is not this week. The newest real data is the AI sweep tab.
        </span>
      </p>
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
            <span className="ms-num shrink-0 text-ink-2">{s.current_count} that week</span>
          </li>
        ))}
      </ul>
      {b.footer && <p className="ws-wrap mt-4 text-[13px] leading-snug text-ink-3">{b.footer}</p>}
    </article>
  )
}

/** The AI device sweep (real data, newest first) with a pointer to the demo brief. */
export function DigestTab({ sweep, brief, snapshot }: { sweep: Sweep; brief: Brief | null; snapshot: string }) {
  return (
    <div>
      <SweepCard sweep={sweep} />
      {brief && (
        <p className="ws-wrap mt-3 text-[14px] text-ink-3">
          The daily brief {brief.date} is a different, older week ({snapshot.toLowerCase()}); see the Brief tab.
        </p>
      )}
    </div>
  )
}
