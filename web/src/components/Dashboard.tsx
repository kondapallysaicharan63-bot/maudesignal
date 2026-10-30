import { CLASS_LABEL } from '../artifacts'
import { alertItems, type AlertItem } from '../dashboard'
import { demoSnapshotLabel, isoDay, visibleWorkflows } from '../data'
import type { WorkflowId, WorkspaceData } from '../types'
import { AlertList } from './AlertBell'
import { MetricsChart } from './MetricsChart'
import { Pill } from './artifacts/common'
import { SweepFlagged, SweepHead } from './SweepCard'

/** The newest daily brief's flags, labelled as a demo snapshot with its dates. */
function FlagsCard({ data, onBrief }: { data: WorkspaceData; onBrief: (date: string) => void }) {
  const b = data.briefs[0]
  const snapshot = demoSnapshotLabel(data.sources)
  return (
    <article className="rounded-md border border-rule-strong bg-surface p-4" aria-label="This week's flags">
      <p className="ms-kicker m-0">This week's flags · demo snapshot</p>
      {!b ? (
        <p className="mt-2 text-ink-2">No daily brief is stored yet.</p>
      ) : (
        <>
          <p className="ms-banner ms-banner--warn mt-2 text-[16px]">
            <span className="ws-wrap">
              <strong>{snapshot}.</strong> Brief <span className="ms-num">{b.date}</span>, week{' '}
              <span className="ms-num">
                {isoDay(b.window.current_start)} to {isoDay(b.window.current_end)}
              </span>
              . Made from the demo database, not this week's openFDA data.
            </span>
          </p>
          <dl className="m-0 mt-3 grid grid-cols-3 gap-2">
            {(
              [
                ['New kind of problem', b.counts.new],
                ['More serious than usual', b.counts.more_serious_than_usual],
                ['Reports suddenly increased', b.counts.reports_suddenly_increased],
              ] as const
            ).map(([k, v]) => (
              <div key={k} className="rounded-md border border-rule bg-paper p-2">
                <dt className="text-[14px] leading-snug text-ink-2">{k}</dt>
                <dd className="t-index ms-num m-0 mt-1">{v}</dd>
              </div>
            ))}
          </dl>
          <ul className="m-0 mt-3 list-none p-0">
            {b.signals
              .filter((s) => s.classification !== 'stable')
              .map((s) => (
                <li key={s.product_code} className="flex flex-wrap items-baseline justify-between gap-2 border-t border-rule py-2">
                  <span>
                    <span className="ms-code mr-2">{s.product_code}</span>
                    <Pill tone={s.classification === 'spike' ? 'warn' : 'bad'}>{CLASS_LABEL[s.classification] ?? s.label}</Pill>
                  </span>
                  <span className="ms-num text-ink-2">{s.current_count} that week</span>
                </li>
              ))}
          </ul>
          {b.signals.every((s) => s.classification === 'stable') && (
            <p className="m-0 mt-2 text-ink-2">No device type was flagged in this brief.</p>
          )}
          <button type="button" className="ms-btn ms-btn--secondary ms-btn--sm mt-3" onClick={() => onBrief(b.date)}>
            Open brief {b.date}
          </button>
        </>
      )}
    </article>
  )
}

/** Home: the whole dashboard in the centre. Every number comes from the stored exports. */
export function Dashboard({
  data,
  onWorkflow,
  onBrief,
  onAlert,
}: {
  data: WorkspaceData
  onWorkflow: (id: WorkflowId) => void
  onBrief: (date: string) => void
  onAlert: (a: AlertItem) => void
}) {
  const tiles = visibleWorkflows(data.investigations.investigations).filter((w) => w.id !== 'ai-sweep')
  const alerts = alertItems(data.sweep, data.briefs)
  return (
    <div>
      <p className="ms-kicker m-0">Postmarket surveillance · FDA-cleared AI/ML devices</p>
      <h1 className="t-headline m-0 mt-1" style={{ fontSize: 'clamp(24px, 4vw, 32px)' }}>
        Dashboard
      </h1>
      {/* Phone: headline, alerts, flags, then the rest. Desktop: headline | alerts on top, flagged codes | this week's flags below. */}
      <div className="mt-3 grid grid-cols-1 gap-4 xl:grid-cols-5">
        <div className="xl:col-span-3 xl:row-start-1">
          <SweepHead sweep={data.sweep} compact />
        </div>
        <article className="order-first rounded-md border border-rule-strong bg-surface p-4 xl:order-none xl:col-span-2 xl:row-start-1" aria-label="Alerts">
          <p className="ms-kicker m-0">Alerts · {alerts.length}</p>
          <div className="mt-1">
            <AlertList items={alerts} onOpen={onAlert} />
          </div>
        </article>
        <div className="xl:col-span-2 xl:col-start-4 xl:row-start-2">
          <FlagsCard data={data} onBrief={onBrief} />
        </div>
        <div className="xl:col-span-3 xl:col-start-1 xl:row-start-2">
          <SweepFlagged sweep={data.sweep} />
        </div>
      </div>
      <section className="mt-4 rounded-md border border-rule-strong bg-surface p-4" aria-label="Recorded runs">
        <p className="ms-kicker m-0">Recorded copilot runs</p>
        <div className="mt-3">
          <MetricsChart threads={data.threads.threads} />
        </div>
      </section>
      <h2 className="ms-kicker mt-8">Workflows</h2>
      <ul className="m-0 mt-3 grid list-none grid-cols-1 gap-3 p-0 sm:grid-cols-2 xl:grid-cols-3">
        {tiles.map((w) => (
          <li key={w.id}>
            <button
              onClick={() => onWorkflow(w.id)}
              className="h-full w-full rounded-md border border-rule bg-surface p-4 text-left hover:border-rule-strong"
            >
              <span className="t-title block">{w.title}</span>
              <span className="mt-1 block text-[16px] leading-snug text-ink-2">{w.blurb}</span>
            </button>
          </li>
        ))}
      </ul>
      <p className="mt-6 max-w-xl text-[16px] text-ink-2">
        Answers here are written from stored public records (MAUDE reports, recalls, 510(k)s, PubMed, MHRA (UK) alerts). Each sentence is
        checked before it is shown; a sentence with no factual claim is marked as such.
      </p>
    </div>
  )
}
