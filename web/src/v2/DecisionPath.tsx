// The PMS decision path of a simulated device (F22/F23): triage, PMS review board, outcome, risk. People decide;
// MaudeSignal shows the stored evidence. Everything company-side is SIMULATED; the evidence panel on the board step
// shows the REAL FDA pattern (stored openFDA data from company.json) beside it, labelled as real.
import type { ReactNode } from 'react'
import type { CompanyDevice, CompanyPattern } from '../types'
import { niceDate, SIM_LABEL, type ClauseTag, type DecisionOutcome, type DecisionPath, type DeviceDecision, type RiskCell } from './profiles'

const ymd = (s: string): string => (/^\d{8}$/.test(s) ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6)}` : s)
const dateOf = (x: { date: string; planned: boolean }): string => `${niceDate(x.date)}${x.planned ? ' (planned)' : ''}`

/** The chips of a step with a one-line reason each (hover) and a "Why these clauses" list (touch and keyboard). */
export function ClauseChips({ tags }: { tags: ClauseTag[] }) {
  return (
    <div className="ms2-clauses" data-testid="clause-tags">
      <p className="m-0 flex flex-wrap gap-2">
        {tags.map((t) => (
          <span key={t.tag} className="ms-chip" title={t.why} data-testid="clause-chip">
            {t.tag}
          </span>
        ))}
      </p>
      <details className="ms2-why">
        <summary>Why these clauses</summary>
        <ul className="ms2-list">
          {tags.map((t) => (
            <li key={t.tag}>
              <span className="font-semibold">{t.tag}</span>: {t.why}
            </li>
          ))}
        </ul>
      </details>
    </div>
  )
}

const ZONE_FILL: Record<RiskCell['zone'], string> = {
  acceptable: 'var(--success-soft)',
  'reduce as far as possible': 'var(--warning-soft)',
  'not acceptable': 'var(--critical-soft)',
}
const zoneOf = (s: number, p: number): RiskCell['zone'] => (s * p <= 4 ? 'acceptable' : s * p <= 9 ? 'reduce as far as possible' : 'not acceptable')

/** The 5x5 severity x probability matrix with the cell before (ring) and after (dot), drawn inline from tokens. */
export function RiskGrid({ before, after, expected }: { before: RiskCell; after: RiskCell; expected: boolean }) {
  const C = 34
  const L = 30
  const T = 6
  const x = (p: number) => L + (p - 1) * C + C / 2
  const y = (s: number) => T + (5 - s) * C + C / 2
  const same = before.severity === after.severity && before.probability === after.probability
  const desc = `Risk matrix, severity by probability. Before: severity ${before.severity} ${before.severity_label}, probability ${before.probability} ${before.probability_label}, ${before.zone}. After${expected ? ' (expected)' : ''}: severity ${after.severity}, probability ${after.probability}, ${after.zone}.`
  return (
    <figure className="m-0" data-testid="risk-grid">
      <svg viewBox={`0 0 ${L + 5 * C + 4} ${T + 5 * C + 40}`} className="ms2-riskgrid" role="img" aria-label={desc}>
        {[5, 4, 3, 2, 1].flatMap((s) =>
          [1, 2, 3, 4, 5].map((p) => (
            <g key={`${s}-${p}`}>
              <rect x={L + (p - 1) * C} y={T + (5 - s) * C} width={C} height={C} fill={ZONE_FILL[zoneOf(s, p)]} stroke="var(--rule)" strokeWidth={1} />
              <text x={x(p)} y={y(s) + 4} textAnchor="middle" fontSize={10} fill="var(--ink-3)">
                {s * p}
              </text>
            </g>
          )),
        )}
        {[1, 2, 3, 4, 5].map((n) => (
          <g key={n}>
            <text x={L - 8} y={y(n) + 4} textAnchor="end" fontSize={11} fill="var(--ink-2)">
              {n}
            </text>
            <text x={x(n)} y={T + 5 * C + 14} textAnchor="middle" fontSize={11} fill="var(--ink-2)">
              {n}
            </text>
          </g>
        ))}
        <text x={L + (5 * C) / 2} y={T + 5 * C + 30} textAnchor="middle" fontSize={11} fill="var(--ink-2)">
          Probability
        </text>
        <text x={8} y={T + (5 * C) / 2} fontSize={11} fill="var(--ink-2)" transform={`rotate(-90 8 ${T + (5 * C) / 2})`} textAnchor="middle">
          Severity
        </text>
        <circle cx={x(before.probability)} cy={y(before.severity)} r={same ? 14 : 12} fill="none" stroke="var(--ink)" strokeWidth={2.5} />
        <circle cx={x(after.probability)} cy={y(after.severity)} r={same ? 6 : 8} fill="var(--ink)" />
      </svg>
      <figcaption className="ms2-muted text-[14px]">
        <span data-testid="risk-before">
          Ring, before: severity {before.severity} × probability {before.probability} = {before.score} ({before.zone}).
        </span>{' '}
        <span data-testid="risk-after">
          Dot, after{expected ? ' (expected)' : ''}: severity {after.severity} × probability {after.probability} = {after.score} ({after.zone}).
        </span>{' '}
        {same && 'Same cell: no change.'} (Simulated.)
      </figcaption>
    </figure>
  )
}

function Step({
  n,
  id,
  title,
  state,
  tags,
  children,
}: {
  n: number
  id: string
  title: string
  state: 'done' | 'planned' | 'pending'
  tags?: ClauseTag[]
  children: ReactNode
}) {
  return (
    <li className="ms2-step" data-testid="dp-step" data-step={id} data-state={state}>
      <span className="ms2-step-n" aria-hidden="true">
        {n}
      </span>
      <div className="ms2-step-body">
        <h3 className="ms2-h3 !m-0 flex flex-wrap items-center gap-2">
          <span>
            Step {n}: {title}
          </span>
          <span className="ms2-tag">{state === 'done' ? 'recorded' : state === 'planned' ? 'planned' : 'not reached yet'}</span>
        </h3>
        <div className="mt-2 space-y-2">{children}</div>
        {tags && tags.length > 0 && <ClauseChips tags={tags} />}
      </div>
    </li>
  )
}

/** The REAL FDA evidence for the signal, read from the stored company.json (never from the simulated file). */
export function RealEvidence({ d, path }: { d: CompanyDevice | undefined; path: DecisionPath }) {
  const head = `Real FDA data · openFDA · product code ${d?.product_code ?? ''}`
  let body: ReactNode = <p className="m-0">Not in stored data.</p>
  if (d && path.signal.kind === 'pattern') {
    const pt: CompanyPattern | undefined = d.patterns.find((x) => x.id === path.signal.pattern_id)
    if (pt)
      body = (
        <>
          <p className="m-0 font-semibold">{pt.display_label.replace(/^Keyword match \(unreviewed\):\s*/i, '')}</p>
          <p className="m-0">
            <span className="ms-num">{pt.count}</span> MAUDE reports
            {pt.first_received && pt.last_received ? `, received ${niceDate(ymd(pt.first_received))} to ${niceDate(ymd(pt.last_received))}` : ''}
            {pt.kind === 'keyword' ? '. Keyword match, unreviewed: a person must read the reports' : ''}.
          </p>
          <p className="m-0 text-[14px]">
            {pt.links.slice(0, 3).map((l, i) => (
              <span key={l.url}>
                {i > 0 && ' · '}
                <a className="ms2-a" href={l.url} target="_blank" rel="noreferrer">
                  {l.label}
                </a>
              </span>
            ))}
          </p>
        </>
      )
  } else if (d && d.sweep) {
    body = (
      <>
        <p className="m-0 font-semibold">Weekly AI-device sweep: {d.sweep.classification.replace(/_/g, ' ')}</p>
        <p className="m-0">
          As of {niceDate(ymd(d.sweep.as_of))}: <span className="ms-num">{d.sweep.current_count}</span> reports this week, <span className="ms-num">{(d.sweep as { baseline_count?: number }).baseline_count ?? 'n/a'}</span> in the 4 weeks before.
        </p>
        <p className="m-0 text-[14px]">
          <a className="ms2-a" href={d.sweep.query_url} target="_blank" rel="noreferrer">
            openFDA query for this sweep
          </a>
        </p>
      </>
    )
  }
  return (
    <section className="ms2-card ms2-realbox" aria-label="Real FDA data" data-testid="dp-real">
      <p className="ms2-realtag">{head}</p>
      <div className="mt-1 space-y-1">{body}</div>
      <p className="ms2-muted m-0 mt-1 text-[13px]">These are reports on all devices with this product code, not on our simulated device.</p>
    </section>
  )
}

function Assess({ label, tag, a }: { label: string; tag: string; a: { result: string; rationale: string } }) {
  return (
    <li data-testid="dp-assessment" data-result={a.result}>
      <p className="m-0 font-semibold">
        {label} <span className="ms-code">{tag}</span>
      </p>
      <p className="m-0">
        Assessed by the board: <span className="font-semibold">{a.result}</span>
      </p>
      <p className="m-0">Rationale: {a.rationale}</p>
    </li>
  )
}

function Outcome({ o }: { o: DecisionOutcome }) {
  if (o.kind === 'ntf')
    return (
      <>
        <p className="m-0 font-semibold">Note to file</p>
        <p className="m-0">Rationale: {o.rationale}</p>
        <p className="m-0 ms2-muted">
          Signed and dated by {o.signed_by}, {o.signed_role}, {dateOf(o)}.
        </p>
      </>
    )
  if (o.kind === 'capa')
    return (
      <>
        <p className="m-0 font-semibold">
          CAPA opened: <span className="ms-code !text-[15px] !text-ink">{o.capa_id}</span>
        </p>
        <p className="m-0">
          Owner {o.owner} · opened {dateOf(o)} · due {niceDate(o.due)}
          {o.due_planned ? ' (planned)' : ''}
        </p>
        <p className="m-0">Status: {o.status}</p>
      </>
    )
  return (
    <>
      <p className="m-0 font-semibold">Escalation assessment, documented by the board on {dateOf(o)}</p>
      <ul className="ms2-list">
        <Assess label="MDR reportability" tag="21 CFR 803" a={o.mdr} />
        <Assess label="Correction or removal" tag="21 CFR 806" a={o.correction_removal} />
        <Assess label="Recall consideration" tag="21 CFR 7" a={o.recall} />
      </ul>
      {o.mdr.clock_note && (
        <p className="ms2-note m-0" data-testid="mdr-clock">
          <span className="font-semibold">The 30-day clock.</span> {o.mdr.clock_note}
          {o.mdr.receipt_date && o.mdr.due_date && o.mdr.submitted_date && (
            <>
              {' '}
              Received {niceDate(o.mdr.receipt_date)} · due by {niceDate(o.mdr.due_date)} · recorded as submitted {niceDate(o.mdr.submitted_date)} (day {o.mdr.day_of_30} of 30).
            </>
          )}
        </p>
      )}
      <p className="m-0 ms2-muted">
        Signed and dated by {o.signed_by}, {o.signed_role}, {dateOf(o)}. The tool decided nothing.
      </p>
    </>
  )
}

export function signalTitle(d: CompanyDevice | undefined, path: DecisionPath): string {
  if (path.signal.kind === 'sweep') return `Weekly sweep signal for ${d?.product_code ?? 'this product code'}`
  const pt = d?.patterns.find((x) => x.id === path.signal.pattern_id)
  return pt ? pt.display_label.replace(/^Keyword match \(unreviewed\):\s*/i, '') : (path.signal.pattern_id ?? 'Signal')
}

const OUTCOME_LABEL = { ntf: 'Note to file', capa: 'CAPA opened', escalation: 'Escalation assessed' } as const

export function outcomeChip(path: DecisionPath): string {
  if (!path.outcome) return 'Decision due'
  const o = path.outcome
  if (o.kind === 'escalation') return o.mdr.result === 'reportable' ? 'Escalation: MDR reportable' : 'Escalation: recall not warranted'
  return OUTCOME_LABEL[o.kind]
}

export function PathCard({ path, d, open }: { path: DecisionPath; d: CompanyDevice | undefined; open: boolean }) {
  const t = path.triage
  const b = path.board
  const o = path.outcome
  return (
    <details className="ms2-dp" id={`dp-${path.id}`} open={open} data-testid="decision-path" data-state={path.state} data-outcome={o?.kind ?? 'open'}>
      <summary>
        <span className="ms2-dp-title">{signalTitle(d, path)}</span>
        <span className={path.state === 'open' ? 'ms-chip ms-chip--high' : 'ms-chip'} data-testid="dp-chip">
          {outcomeChip(path)}
        </span>
      </summary>
      <p className="ms2-simtag mt-3">{SIM_LABEL}</p>
      <ol className="ms2-stepper" aria-label="Decision path steps">
        <Step n={1} id="triage" title="Triage" state="done" tags={t.tags}>
          <p className="m-0">
            Owner assigned: {t.owner}, {t.role} · {dateOf(t)}
          </p>
          <p className="m-0 ms2-muted">{t.note}</p>
        </Step>
        <Step n={2} id="board" title="PMS review board" state={b.held ? 'done' : 'planned'} tags={b.tags}>
          <p className="m-0">
            {b.held ? 'Met' : 'Meeting planned'} {dateOf(b)} · {b.held ? 'Attended' : 'Invited'}:{' '}
            {b.attendees.map((a) => `${a.name}, ${a.role === 'Design Engineering' ? 'Engineering' : a.role.replace(' Engineering', '').replace('Post-Market Surveillance', 'PMS')}`).join('; ')}
          </p>
          <div className="ms2-grid" data-testid="dp-evidence">
            <RealEvidence d={d} path={path} />
            <section className="ms2-card" aria-label="Company side (simulated)" data-testid="dp-company">
              <p className="ms2-simtag">{SIM_LABEL}</p>
              <p className="ms2-h3">Company side</p>
              <p className="m-0">{b.summary}</p>
            </section>
          </div>
          <p className="m-0">
            Board decision: <span className="font-semibold">{b.decision ?? 'not yet taken'}</span>
          </p>
        </Step>
        <Step n={3} id="outcome" title="Outcome" state={o ? 'done' : 'pending'} tags={o?.tags}>
          {o ? <Outcome o={o} /> : <p className="m-0">No outcome yet. The board decides after the meeting, and signs the rationale.</p>}
        </Step>
        <Step n={4} id="risk" title="Risk (HHE and ISO 14971 risk file)" state={path.risk ? 'done' : 'pending'} tags={path.risk?.tags}>
          {path.risk ? (
            <>
              <p className="m-0">{path.risk.hhe_summary}</p>
              <RiskGrid before={path.risk.before} after={path.risk.after} expected={path.risk.after_is_expected} />
              <p className="m-0 ms2-muted">
                Risk file {path.risk.risk_file.ref}: {path.risk.risk_file.change.toLowerCase()} · {dateOf(path.risk.risk_file)}.
              </p>
            </>
          ) : (
            <p className="m-0">Not reached yet: the risk file is reviewed once the board has an outcome.</p>
          )}
        </Step>
      </ol>
    </details>
  )
}

/** Opens a path card and scrolls to it (the link from the "Does this apply to us?" history). */
export function showPath(id: string): void {
  const el = document.getElementById(`dp-${id}`)
  if (!el) return
  ;(el as HTMLDetailsElement).open = true
  el.scrollIntoView({ block: 'start' })
}

export function DecisionPaths({ decision, d }: { decision: DeviceDecision; d: CompanyDevice | undefined }) {
  return (
    <section className="ms2-card" aria-label="Decision path (simulated)" data-testid="decision-paths">
      <p className="ms2-simtag">{SIM_LABEL}</p>
      <h2 className="ms2-h2">Decision path (simulated)</h2>
      <p className="ms2-muted m-0 mt-1 text-[15px]">
        People decide; the tool supplies stored evidence. Each signal goes through triage, the PMS review board, an outcome and a risk review. MaudeSignal files nothing and decides nothing.
      </p>
      {decision.paths.length === 0 ? (
        <p className="m-0 mt-3" data-testid="no-decision-path">
          {decision.none_reason}
        </p>
      ) : (
        <div className="mt-3 space-y-3">
          {decision.paths.map((p, i) => (
            <PathCard key={p.id} path={p} d={d} open={i === 0} />
          ))}
        </div>
      )}
    </section>
  )
}
