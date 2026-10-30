import { useState } from 'react'
import { buildMatchTrace, factSections, weekChangeDates } from '../../labelMatch'
import type { LabelMatch, LabelMatchRecord } from '../../types'
import { TraceView } from '../TraceView'
import { Pill } from './common'

function Facts({ rec, code }: { rec: LabelMatchRecord; code: string }) {
  const view = rec.device_type_views[code]
  if (!view) return <p className="m-0 mt-2 text-ink-2">No stored facts for device type {code}.</p>
  const { sections, withheld, typeFact } = factSections(view)
  return (
    <div data-testid="match-facts">
      <h4 className="ms-kicker mt-3">
        Device type <span className="ms-code">{view.product_code}</span> · {view.device_type_name}
      </h4>
      {typeFact && (
        <p className="ws-wrap m-0 mt-1 text-ink-2">
          {typeFact.text}{' '}
          <a className="text-accent underline" href={typeFact.query_url} target="_blank" rel="noreferrer">
            openFDA query
          </a>
        </p>
      )}
      {sections.map((s) => (
        <section key={s.title} className="mt-2">
          <h5 className="m-0 text-[15px] font-semibold">{s.title}</h5>
          <ul className="m-0 list-none p-0">
            {s.facts.map((f) => (
              <li key={f.id} className="ws-wrap border-t border-rule py-2">
                {f.text}{' '}
                <a className="text-accent underline" href={f.query_url} target="_blank" rel="noreferrer">
                  openFDA query
                </a>
              </li>
            ))}
          </ul>
          {s.title === "This week's change" && <p className="m-0 text-[15px] text-ink-2">{weekChangeDates(view)}</p>}
        </section>
      ))}
      {withheld > 0 && (
        <p className="m-0 mt-2 text-[15px] text-ink-2">
          {withheld} stored {withheld === 1 ? 'fact was' : 'facts were'} held back by the claim gate and {withheld === 1 ? 'is' : 'are'} not shown.
        </p>
      )}
    </div>
  )
}

function Card({ m, confirmed, onConfirm }: { m: LabelMatch; confirmed: boolean; onConfirm: () => void }) {
  return (
    <li
      data-testid="match-card"
      aria-current={confirmed ? 'true' : undefined}
      className={['mt-3 rounded-md border bg-surface p-3', confirmed ? 'border-ink' : 'border-rule'].join(' ')}
    >
      <p className="ws-wrap m-0 font-semibold">{m.device_name}</p>
      <dl className="m-0 mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[15px]">
        <dt className="text-ink-2">Owner</dt>
        <dd className="ws-wrap m-0">{m.owner}</dd>
        <dt className="text-ink-2">Product code</dt>
        <dd className="m-0">
          <span className="ms-code">{m.product_code}</span>
        </dd>
        <dt className="text-ink-2">Device type</dt>
        <dd className="ws-wrap m-0">{m.device_type_name}</dd>
        <dt className="text-ink-2">Record</dt>
        <dd className="ws-wrap m-0">
          {m.source === '510k' ? '510(k)' : m.source.replace(/_/g, ' ')} {m.record_id}
          {m.decision_date ? `, decided ${m.decision_date}` : ''}
        </dd>
        <dt className="text-ink-2">Score</dt>
        <dd className="ms-num m-0">{m.score}</dd>
      </dl>
      {m.why_matched.length > 0 && (
        <div className="mt-2">
          <Pill tone="ok">Why it matched</Pill>
          <ul className="m-0 mt-1 list-disc pl-5" data-testid="why-matched">
            {m.why_matched.map((w) => (
              <li key={w} className="ws-wrap">
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}
      {m.why_not_matched.length > 0 && (
        <div className="mt-2">
          <Pill tone="warn">What did not match</Pill>
          <ul className="m-0 mt-1 list-disc pl-5" data-testid="why-not-matched">
            {m.why_not_matched.map((w) => (
              <li key={w} className="ws-wrap">
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="m-0 mt-2 text-[15px]">
        <a className="text-accent underline" href={m.query_url} target="_blank" rel="noreferrer">
          openFDA search that found this
        </a>
      </p>
      {confirmed ? (
        <p className="m-0 mt-2 font-semibold" data-testid="confirmed-note">
          Confirmed by you in this browser; not saved.
        </p>
      ) : (
        <button
          type="button"
          onClick={onConfirm}
          className="mt-2 min-h-11 rounded-xs border border-ink bg-sunk px-3 text-[15px] font-semibold text-ink hover:bg-surface"
        >
          Confirm this match
        </button>
      )}
    </li>
  )
}

/**
 * The stored possible matches for one label. Nothing is picked for the person: a match is confirmed only by a click here,
 * the choice lives in this component's state (local, gone on reload), and nothing is sent anywhere.
 */
export function LabelMatches({ rec }: { rec: LabelMatchRecord | null | undefined }) {
  const [picked, setPicked] = useState<number | null>(null)
  if (!rec) {
    return (
      <section className="mt-4" data-testid="label-matches">
        <h3 className="ms-kicker">Possible matches (a person confirms one)</h3>
        <p className="m-0 mt-1 text-ink-2">No matching run was recorded for this photo.</p>
      </section>
    )
  }
  const chosen = picked !== null ? rec.matches[picked] : undefined
  return (
    <section className="mt-4" data-testid="label-matches">
      <h3 className="ms-kicker">Possible matches (a person confirms one)</h3>
      {rec.matches.length === 0 ? (
        <div data-testid="no-match">
          <p className="m-0 mt-1 font-semibold">No match found</p>
          <p className="ws-wrap m-0 mt-1 text-ink-2">{rec.note}</p>
        </div>
      ) : (
        <>
          <p className="m-0 mt-1 text-ink-2">
            Up to three records from openFDA. None is chosen for you; check them against the photo, then confirm one or none.
          </p>
          <ul className="m-0 list-none p-0">
            {rec.matches.slice(0, 3).map((m, i) => (
              <Card key={`${m.source}-${m.record_id}-${i}`} m={m} confirmed={picked === i} onConfirm={() => setPicked(i)} />
            ))}
          </ul>
          {picked !== null && (
            <button type="button" onClick={() => setPicked(null)} className="mt-3 min-h-11 rounded-xs border border-rule px-3 text-[15px] text-ink-2 hover:bg-sunk">
              Clear my choice
            </button>
          )}
        </>
      )}
      {chosen && (
        <div className="mt-3" data-testid="confirmed-view">
          <Facts rec={rec} code={chosen.product_code} />
        </div>
      )}
      {chosen && (
        <div className="mt-4">
          <TraceView trace={buildMatchTrace(rec)} shown={99} label="Matching steps" replayed={false} absentLabels />
        </div>
      )}
      <p className="mt-3 text-[15px] leading-snug text-ink-2" data-testid="match-recorded-note">
        Recorded data: these searches were run when the recording was made
        {rec.generated_utc ? ` (${rec.generated_utc})` : ''}. Nothing is searched live on this screen.{' '}
        {rec.disclaimer ?? 'Possible matches for a person to confirm. Not medical advice.'}
      </p>
    </section>
  )
}
