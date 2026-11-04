// Morning brief (PRD-28, /daily): one dated page to read first. Built only from the stored exports (alerts.json,
// briefs.json, sweep.json, manifest.json): no model call, no number computed here, and every number links to the
// openFDA query it came from. It is dated by its data (the latest sweep week and the stored snapshot), never by today.
import type { AlertDetail } from '../alerts'
import { safeUrl } from '../alerts'
import { DataAsOfBanner, storedAsOf } from '../pms/DataAsOf'
import type { WorkspaceData } from '../types'
import { demoDetails, rankReal, sweepDetails } from './realAlerts'

export const DAILY_DISCLAIMER = 'A named person decides what each flag means. Nothing is filed with FDA. Not medical advice.'
export const DAILY_REFRESH =
  'This brief is rebuilt from the stored exports when they are regenerated (the AI device sweep and the monitor workflow in GitHub Actions). It is not a live feed. For a live openFDA check of any product code, use Investigate.'
const BTN = { minHeight: 44 }

/** The date the brief is about: the latest sweep week's end, else the stored snapshot's latest report. */
export function briefDate(data: Pick<WorkspaceData, 'sweep' | 'manifest'>): string | null {
  const w = data.sweep?.meta?.window
  const end = w?.current_end ?? null
  if (end && /^\d{8}$/.test(end)) return `${end.slice(0, 4)}-${end.slice(4, 6)}-${end.slice(6, 8)}`
  if (end) return end
  return data.manifest?.data_as_of?.stored?.latest ?? null
}

export const recallSearchUrl = (code: string): string =>
  `https://api.fda.gov/device/recall.json?search=product_code:${encodeURIComponent(code)}&limit=5`

function NumberList({ a }: { a: AlertDetail }) {
  return (
    <ul className="m-0 pl-5 space-y-1" data-testid={`daily-numbers-${a.product_code}`}>
      {a.numbers.map((n) => {
        const u = safeUrl(n.openfda_url)
        return (
          <li key={n.label}>
            {n.label}:{' '}
            {u ? (
              <a className="ms2-a ms-num" href={u} target="_blank" rel="noreferrer" data-testid="daily-number-link">
                {String(n.value)}
              </a>
            ) : (
              <span className="ms-num">{String(n.value)}</span>
            )}
          </li>
        )
      })}
    </ul>
  )
}

function FlagCard({ a, onInvestigate, onBoard }: { a: AlertDetail; onInvestigate: (code: string) => void; onBoard: () => void }) {
  const recalls = a.recalls.slice(0, 3)
  return (
    <section className="ms2-card" aria-labelledby={`daily-${a.id}-h`} data-testid="daily-flag" data-code={a.product_code}>
      <h3 id={`daily-${a.id}-h`} className="ms2-h2">
        <span className="ms-code">{a.product_code}</span> · {a.rule_words}
      </h3>
      <p className="ms2-muted m-0 text-[15px]">
        {a.device_type ?? 'Device type not named on the stored reports'} · Stored · {a.source.label}
        {a.source.as_of ? `, ${a.source.as_of}` : ''}
        {a.window ? ` · week ${a.window.this_week.from} to ${a.window.this_week.to}` : ''}
      </p>
      {a.mix_sentence && <p className="m-0 mt-1">{a.mix_sentence}</p>}
      <div className="mt-2">
        <NumberList a={a} />
      </div>
      <p className="m-0 mt-2" data-testid={`daily-recalls-${a.product_code}`}>
        Recalls stored for this code: <span className="ms-num">{a.recalls_total}</span> (
        <a className="ms2-a" href={recallSearchUrl(a.product_code)} target="_blank" rel="noreferrer">
          openFDA recall search
        </a>
        ). A listed recall is a past FDA record, not a decision about your device.
      </p>
      {recalls.length > 0 && (
        <ul className="m-0 pl-5 mt-1 space-y-1">
          {recalls.map((r) => {
            const u = safeUrl(r.url)
            return (
              <li key={r.id}>
                {u ? (
                  <a className="ms2-a" href={u} target="_blank" rel="noreferrer">
                    {r.id}
                  </a>
                ) : (
                  r.id
                )}
                {r.date ? ` · ${r.date}` : ''}
              </li>
            )
          })}
        </ul>
      )}
      <div className="flex flex-wrap gap-2 mt-3">
        <button type="button" className="ms-btn ms-btn--sm" style={BTN} onClick={() => onInvestigate(a.product_code)} data-testid={`daily-investigate-${a.product_code}`}>
          Live check on Investigate
        </button>
        <button type="button" className="ms-btn ms-btn--sm" style={BTN} onClick={onBoard} data-testid={`daily-board-${a.product_code}`}>
          Open the PMS board
        </button>
      </div>
    </section>
  )
}

export function DailyBrief({ data, onInvestigate, onBoard }: { data: WorkspaceData; onInvestigate: (code: string) => void; onBoard: () => void }) {
  const sweep = rankReal(sweepDetails(data))
  const demo = demoDetails(data)
  const latestBrief = [...(data.briefs ?? [])].sort((a, b) => b.date.localeCompare(a.date))[0] ?? null
  const m = data.sweep?.meta
  const date = briefDate(data)
  return (
    <div data-testid="daily-page">
      <header className="ms2-pagehead">
        <h1 className="ms2-h1">Morning brief</h1>
        <p className="ms2-lead">
          What the stored data flags, with the openFDA query behind every number. Dated by its data, not by today:{' '}
          <strong data-testid="daily-date">{date ?? 'date not stated'}</strong>.
        </p>
      </header>
      <DataAsOfBanner asOf={storedAsOf(data.manifest)} testid="daily-asof" />
      <p className="ms-banner ms-banner--warn" role="note" data-testid="daily-disclaimer">
        <span>
          <strong>{DAILY_DISCLAIMER}</strong>
        </span>
      </p>

      <section aria-labelledby="daily-new-h" className="mt-4 space-y-3">
        <h2 id="daily-new-h" className="ms2-h2">
          New flags in the latest AI device sweep week
        </h2>
        {m && (
          <p className="ms2-muted m-0" data-testid="daily-sweep-line">
            {m.codes_checked} of {m.codes_on_list} product codes on FDA's AI-Enabled Medical Device List were checked on openFDA (run {m.generated_utc.slice(0, 10)}); {sweep.length} crossed a rule.
          </p>
        )}
        {sweep.length === 0 && <p className="ms2-muted">No real FDA alert is stored for the latest sweep week.</p>}
        {sweep.map((a) => (
          <FlagCard key={a.id} a={a} onInvestigate={onInvestigate} onBoard={onBoard} />
        ))}
      </section>

      <section aria-labelledby="daily-demo-h" className="mt-6 space-y-3">
        <h2 id="daily-demo-h" className="ms2-h2">
          What changed in the stored demo snapshot
        </h2>
        {latestBrief && (
          <p className="m-0" data-testid="daily-brief-headline">
            Week {latestBrief.window.current_start} to {latestBrief.window.current_end}: {latestBrief.headline}.
          </p>
        )}
        {demo.map((a) => (
          <FlagCard key={a.id} a={a} onInvestigate={onInvestigate} onBoard={onBoard} />
        ))}
      </section>

      <p className="ms2-muted mt-6" data-testid="daily-refresh">
        {DAILY_REFRESH}
      </p>
    </div>
  )
}
