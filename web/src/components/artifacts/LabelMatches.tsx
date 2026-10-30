import { useEffect, useRef, useState } from 'react'
import {
  buildMatchTrace,
  factSections,
  fmtNumbers,
  fmtUtc,
  groupSearches,
  hasClearLeader,
  keyStats,
  rankLine,
  rankMatches,
  weekChangeDates,
  weekChangeRules,
} from '../../labelMatch'
import { traceSummary } from '../../trace'
import type { LabelMatch, LabelMatchRecord } from '../../types'
import { TraceView } from '../TraceView'
import { Pill } from './common'

const Link = ({ href, children }: { href: string; children: string }) => (
  <a className="text-accent underline" href={href} target="_blank" rel="noreferrer">
    {children}
  </a>
)

function Facts({ rec, code }: { rec: LabelMatchRecord; code: string }) {
  const view = rec.device_type_views[code]
  if (!view) return <p className="m-0 mt-2 text-[17px] text-ink-2">No stored facts for device type {code}.</p>
  const { sections, withheld, typeFact } = factSections(view)
  const stats = keyStats(view)
  return (
    <div data-testid="match-facts" className="rounded-md border border-rule bg-surface p-3">
      <p className="ms-kicker m-0">Device type</p>
      <p className="m-0 mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="ms-chip font-mono">{view.product_code}</span>
      </p>
      <p className="ws-wrap m-0 mt-1 text-[19px] font-semibold leading-snug">{view.device_type_name}</p>
      {typeFact && (
        <p className="ws-wrap m-0 mt-1 text-[17px] text-ink-2">
          {fmtNumbers(typeFact.text)} <Link href={typeFact.query_url}>openFDA query</Link>
        </p>
      )}
      {stats.length > 0 && (
        <dl className="m-0 mt-3 grid grid-cols-3 gap-2" data-testid="key-stats">
          {stats.map((s) => (
            <div key={s.label} className="rounded-md border border-rule bg-paper p-2">
              <dt className="text-[15px] font-semibold uppercase tracking-[0.06em] text-ink-2">{s.label}</dt>
              <dd className="ms-num m-0 mt-1 font-serif text-[24px] leading-none">{s.value}</dd>
              {s.note && <dd className="ws-wrap m-0 mt-1 text-[16px] leading-snug text-ink-2">{s.note}</dd>}
            </div>
          ))}
        </dl>
      )}
      {sections.map((s) => (
        <section key={s.title} className="mt-5">
          <h5 className="m-0 text-[19px] font-semibold">{s.title}</h5>
          <ul className="m-0 mt-1 list-none p-0">
            {s.facts.map((f) => (
              <li key={f.id} className="ws-wrap border-t border-rule py-2 text-[17px]">
                {fmtNumbers(f.text)} <Link href={f.query_url}>openFDA query</Link>
              </li>
            ))}
          </ul>
          {s.title === "This week's change" && (
            <>
              <p className="m-0 text-[17px] text-ink-2">{weekChangeDates(view)}</p>
              {weekChangeRules(view).length > 0 && (
                <div data-testid="week-rules" className="mt-1 text-[17px] text-ink-2">
                  <p className="m-0">A change is flagged only when one of these stored rules is met:</p>
                  <ul className="m-0 list-disc pl-5">
                    {weekChangeRules(view).map((r) => (
                      <li key={r} className="ws-wrap">
                        {r}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </section>
      ))}
      {withheld > 0 && (
        <p className="m-0 mt-4 text-[17px] text-ink-2">
          {withheld} stored {withheld === 1 ? 'fact was' : 'facts were'} held back by the claim gate and {withheld === 1 ? 'is' : 'are'} not shown.
        </p>
      )}
    </div>
  )
}

function Card({
  m,
  rank,
  total,
  leader,
  confirmed,
  onConfirm,
  onUndo,
}: {
  m: LabelMatch
  rank: number
  total: number
  leader: boolean
  confirmed: boolean
  onConfirm: () => void
  onUndo: () => void
}) {
  const ref = useRef<HTMLLIElement>(null)
  useEffect(() => {
    if (confirmed) ref.current?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
  }, [confirmed])
  return (
    <li
      ref={ref}
      data-testid="match-card"
      data-confirmed={confirmed ? 'true' : undefined}
      aria-current={confirmed ? 'true' : undefined}
      className={[
        'mt-3 scroll-mt-2 rounded-md bg-surface p-3',
        confirmed ? 'border-2 border-success bg-success-soft' : 'border border-rule',
      ].join(' ')}
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1" data-testid="match-rank">
        <span className="ms-num text-[17px] font-semibold">{rankLine(rank, total, m.score)}</span>
        {leader && rank === 1 && <Pill tone="neutral">Highest score</Pill>}
        {confirmed && <Pill tone="ok">Confirmed</Pill>}
      </div>
      <p className="ws-wrap m-0 mt-1 text-[19px] font-semibold leading-snug">{m.device_name}</p>
      {confirmed ? (
        <div className="mt-2" data-testid="confirmed-block">
          <p className="m-0 font-semibold text-success">You confirmed this match.</p>
          <p className="m-0 mt-1 text-[16px] text-ink-2">
            <span data-testid="confirmed-note">Confirmed by you in this browser; not saved.</span>{' '}
            <button type="button" onClick={onUndo} className="min-h-11 text-accent underline" data-testid="undo-confirm">
              Undo
            </button>
          </p>
        </div>
      ) : (
        <div className="mt-2" data-testid="confirm-row">
          <button
            type="button"
            onClick={onConfirm}
            className="min-h-11 rounded-xs border border-ink bg-sunk px-4 text-[17px] font-semibold text-ink hover:bg-surface"
          >
            Confirm this match
          </button>
        </div>
      )}
      <dl className="m-0 mt-2 grid grid-cols-[7.5rem_1fr] gap-x-3 gap-y-1 text-[17px]">
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
      </dl>
      {m.why_matched.length > 0 && (
        <div className="mt-3">
          <Pill tone="ok">Why it matched</Pill>
          <ul className="m-0 mt-1 list-disc pl-5 text-[17px]" data-testid="why-matched">
            {m.why_matched.map((w) => (
              <li key={w} className="ws-wrap">
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}
      {m.why_not_matched.length > 0 && (
        <div className="mt-3 rounded-md border-2 border-warning bg-warning-soft p-2" data-testid="mismatch-block">
          <Pill tone="warn">What did not match</Pill>
          <ul className="m-0 mt-1 list-disc pl-5 text-[17px]" data-testid="why-not-matched">
            {m.why_not_matched.map((w) => (
              <li key={w} className="ws-wrap">
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="m-0 mt-3 text-[17px]">
        <Link href={m.query_url}>openFDA search that found this</Link>
      </p>
    </li>
  )
}

/**
 * The stored possible matches for one label. Nothing is picked for the person: a match is confirmed only by a click here,
 * the choice lives in this component's state (local, gone on reload), and nothing is sent anywhere.
 */
export function LabelMatches({ rec }: { rec: LabelMatchRecord | null | undefined }) {
  const [picked, setPicked] = useState<number | null>(null)
  const [none, setNone] = useState(false)
  const head = <h3 className="ms-kicker m-0 mt-8 pt-3 !text-[16px]">Possible matches (a person confirms one)</h3>
  if (!rec) {
    return (
      <section className="mt-4" data-testid="label-matches">
        {head}
        <p className="m-0 mt-1 text-[17px] text-ink-2">No matching run was recorded for this photo.</p>
      </section>
    )
  }
  const ranked = rankMatches(rec.matches)
  const leader = hasClearLeader(ranked)
  const chosen = picked !== null ? ranked[picked] : undefined
  const full = buildMatchTrace(rec)
  const when = fmtUtc(rec.generated_utc)
  return (
    <section className="mt-4" data-testid="label-matches">
      {head}
      {rec.matches.length === 0 ? (
        <div data-testid="no-match" className="mt-2 rounded-md border border-rule bg-sunk p-3">
          <p className="m-0 text-[22px] font-semibold leading-snug">No match found</p>
          <p className="m-0 mt-1 text-[17px] font-semibold" data-testid="no-match-next">
            Next step: take a clearer photo of the label.
          </p>
          <p className="ws-wrap m-0 mt-2 text-[17px] text-ink-2">{rec.note}</p>
        </div>
      ) : (
        <>
          <p className="m-0 mt-1 text-[17px] text-ink-2">
            Up to three records from openFDA, highest score first. None is chosen for you; check them against the photo, then confirm one or none.
          </p>
          {!none && (
            <div className="mt-2" data-testid="none-row">
              <button
                type="button"
                onClick={() => {
                  setNone(true)
                  setPicked(null)
                }}
                className="min-h-11 rounded-xs border border-rule px-3 text-[17px] text-ink-2 hover:bg-sunk"
              >
                None of these
              </button>
            </div>
          )}
          {none && (
            <p className="m-0 mt-2 text-[17px]" data-testid="none-note">
              <span className="font-semibold">You chose none of these.</span> <span className="text-[16px] text-ink-2">Only in this browser; not saved.</span>{' '}
              <button type="button" onClick={() => setNone(false)} className="min-h-11 text-accent underline">
                Undo
              </button>
            </p>
          )}
          <ul className="m-0 list-none p-0">
            {ranked.map((m, i) => (
              <Card
                key={`${m.source}-${m.record_id}-${i}`}
                m={m}
                rank={i + 1}
                total={ranked.length}
                leader={leader}
                confirmed={picked === i}
                onConfirm={() => {
                  setPicked(i)
                  setNone(false)
                }}
                onUndo={() => setPicked(null)}
              />
            ))}
          </ul>
        </>
      )}
      {chosen && (
        <div className="mt-5" data-testid="confirmed-view">
          <Facts rec={rec} code={chosen.product_code} />
        </div>
      )}
      {chosen && (
        <div className="mt-4">
          <TraceView
            trace={groupSearches(full)}
            summary={traceSummary(full)}
            stepCount={full.steps.length}
            shown={99}
            label="Matching steps"
            replayed={false}
            absentLabels
          />
        </div>
      )}
      <p className="mt-4 text-[16px] leading-snug text-ink-2" data-testid="match-recorded-note">
        Recorded data{when ? ` from ${when}` : ''}. Nothing is searched live here.{' '}
        {rec.disclaimer ?? 'Possible matches for a person to confirm. Not medical advice.'}
      </p>
    </section>
  )
}
