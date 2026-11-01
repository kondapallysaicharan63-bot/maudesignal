// The PMS decision path of a simulated device (F22/F23): triage, PMS review board, outcome, risk review. People decide;
// MaudeSignal shows the stored evidence. Everything company-side is SIMULATED; the evidence panel on the board step
// shows the REAL FDA pattern (stored openFDA data from company.json) beside it, labelled as real.
import type { ReactNode } from 'react'
import type { CompanyDevice, CompanyPattern } from '../types'
import { niceDate, SIM_TAG, type ClauseTag, type DecisionOutcome, type DecisionPath, type DeviceDecision, type RiskCell } from './profiles'

const ymd = (s: string): string => (/^\d{8}$/.test(s) ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6)}` : s)
const dateOf = (x: { date: string; planned: boolean }): string => `${niceDate(x.date)}${x.planned ? ' (planned)' : ''}`
const plain = (s: string): string => s.replace(/^Keyword match \(unreviewed\):\s*/i, '')

/**
 * One text line "Clauses: ISO 13485 §8.2.2, §8.2.3, 21 CFR 820 (QMSR)" (each clause has its reason on hover) and a
 * "Why these clauses" disclosure for touch and keyboard.
 */
export function ClauseLine({ tags }: { tags: ClauseTag[] }) {
  const iso = tags.filter((t) => t.tag.startsWith('ISO 13485 '))
  const rest = tags.filter((t) => !t.tag.startsWith('ISO 13485 '))
  return (
    <div className="ms2-clauses" data-testid="clause-tags">
      <p className="m-0 text-[15px]">
        <span className="ms2-muted">Clauses: </span>
        {rest.map((t, i) => (
          <span key={t.tag}>
            {i > 0 && ', '}
            <span className="ms2-clause" title={t.why} data-testid="clause-chip">
              {t.tag}
            </span>
          </span>
        ))}
        {iso.length > 0 && (
          <>
            {rest.length > 0 && ', '}
            ISO 13485{' '}
            {iso.map((t, i) => (
              <span key={t.tag}>
                {i > 0 && ', '}
                <span className="ms2-clause" title={t.why} data-testid="clause-chip">
                  {t.tag.replace('ISO 13485 ', '')}
                </span>
              </span>
            ))}
          </>
        )}
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

const zoneOf = (s: number, p: number): RiskCell['zone'] => (s * p <= 4 ? 'acceptable' : s * p <= 9 ? 'reduce as far as possible' : 'not acceptable')
const ZONE_CLASS: Record<RiskCell['zone'], string> = {
  acceptable: 'ms2-rg-lo',
  'reduce as far as possible': 'ms2-rg-mid',
  'not acceptable': 'ms2-rg-hi',
}

/** The 5x5 severity x probability matrix: ring = before, dot = after; the band key sits beside it on wide screens. */
export function RiskGrid({ before, after, expected }: { before: RiskCell; after: RiskCell; expected: boolean }) {
  const C = 40
  const L = 34
  const T = 6
  const x = (p: number) => L + (p - 1) * C + C / 2
  const y = (s: number) => T + (5 - s) * C + C / 2
  const same = before.severity === after.severity && before.probability === after.probability
  const W = L + 5 * C + 4
  const H = T + 5 * C + 44
  const desc = `Risk matrix, severity by probability. Before: severity ${before.severity} ${before.severity_label}, probability ${before.probability} ${before.probability_label}, ${before.zone}. After${expected ? ' (expected)' : ''}: severity ${after.severity}, probability ${after.probability}, ${after.zone}.`
  return (
    <figure className="ms2-rg" data-testid="risk-grid">
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} className="ms2-riskgrid" role="img" aria-label={desc}>
        {[5, 4, 3, 2, 1].flatMap((s) =>
          [1, 2, 3, 4, 5].map((p) => (
            <g key={`${s}-${p}`}>
              <rect className={`ms2-rg-cell ${ZONE_CLASS[zoneOf(s, p)]}`} x={L + (p - 1) * C} y={T + (5 - s) * C} width={C} height={C} />
              <text className="ms2-rg-num" x={x(p)} y={y(s) + 5} textAnchor="middle">
                {s * p}
              </text>
            </g>
          )),
        )}
        {[1, 2, 3, 4, 5].map((n) => (
          <g key={n}>
            <text className="ms2-rg-axis" x={L - 8} y={y(n) + 5} textAnchor="end">
              {n}
            </text>
            <text className="ms2-rg-axis" x={x(n)} y={T + 5 * C + 18} textAnchor="middle">
              {n}
            </text>
          </g>
        ))}
        <text className="ms2-rg-axis" x={L + (5 * C) / 2} y={T + 5 * C + 38} textAnchor="middle">
          Probability
        </text>
        <text className="ms2-rg-axis" x={10} y={T + (5 * C) / 2} transform={`rotate(-90 10 ${T + (5 * C) / 2})`} textAnchor="middle">
          Severity
        </text>
        <circle className="ms2-rg-ring" cx={x(before.probability)} cy={y(before.severity)} r={same ? 17 : 15} />
        <circle className="ms2-rg-dot" cx={x(after.probability)} cy={y(after.severity)} r={same ? 7 : 10} />
      </svg>
      <figcaption className="ms2-rg-key">
        <ul className="ms2-list m-0" aria-label="Risk bands">
          <li>
            <span className="ms2-rg-sw ms2-rg-lo" aria-hidden="true" /> Low (1–4): acceptable
          </li>
          <li>
            <span className="ms2-rg-sw ms2-rg-mid" aria-hidden="true" /> Medium (5–9): reduce as far as possible
          </li>
          <li>
            <span className="ms2-rg-sw ms2-rg-hi" aria-hidden="true" /> High (10–25): not acceptable
          </li>
        </ul>
        <p className="m-0 mt-2" data-testid="risk-before">
          Ring, before: severity {before.severity} × probability {before.probability} = {before.score}. Simulated risk file records: ({before.zone}).
        </p>
        <p className="m-0 mt-1" data-testid="risk-after">
          Dot, after{expected ? ' (expected)' : ''}: severity {after.severity} × probability {after.probability} = {after.score}. Simulated risk file records: ({after.zone}).
        </p>
        {same && <p className="m-0 mt-1">Same cell: no change.</p>}
      </figcaption>
    </figure>
  )
}

function Step({
  n,
  id,
  title,
  state,
  summary,
  tags,
  shown,
  children,
}: {
  n: number
  id: string
  title: string
  state: 'done' | 'planned' | 'pending'
  summary: string
  tags?: ClauseTag[]
  /** Always visible under the summary line (the risk grid). */
  shown?: ReactNode
  /** Behind "Show details". */
  children?: ReactNode
}) {
  return (
    <li className="ms2-step" data-testid="dp-step" data-step={id} data-state={state}>
      <div className="ms2-step-body">
        <h3 className="ms2-step-h">
          <span className="ms2-step-n" aria-hidden="true">
            {n}
          </span>
          <span>
            Step {n}: {title}
          </span>
          {state !== 'done' && <span className="ms2-pill">{state === 'planned' ? 'planned' : 'not reached yet'}</span>}
        </h3>
        <p className="m-0 mt-1" data-testid="step-summary">
          {summary}
        </p>
        {shown && <div className="mt-2">{shown}</div>}
        {children && (
          <details className="ms2-more">
            <summary>Show details</summary>
            <div className="mt-2 space-y-2">{children}</div>
          </details>
        )}
        {tags && tags.length > 0 && <ClauseLine tags={tags} />}
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
          <p className="m-0 font-semibold">
            {plain(pt.display_label)}
            {pt.kind === 'keyword' ? ' (keyword match)' : ''}
          </p>
          <p className="m-0">
            <span className="ms-num">{pt.count}</span> MAUDE reports
            {pt.first_received && pt.last_received ? `, received ${niceDate(ymd(pt.first_received))} to ${niceDate(ymd(pt.last_received))}` : ''}
            {pt.kind === 'keyword' ? '. Keyword match, unreviewed: a person must read the reports' : ''}.
          </p>
          <p className="m-0 text-[15px]">
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
    const base = (d.sweep as { baseline_count?: number }).baseline_count
    body = (
      <>
        <p className="m-0 font-semibold">Weekly AI-device sweep: {d.sweep.classification.replace(/_/g, ' ')}</p>
        <p className="m-0">
          As of {niceDate(ymd(d.sweep.as_of))}: <span className="ms-num">{d.sweep.current_count}</span> reports in the 7 days to that date, and{' '}
          {base === undefined ? 'n/a' : <span className="ms-num">{base}</span>} in the 28 days before
          {base === undefined ? '' : ` (about ${Math.round(base / 4)} a week)`}.
        </p>
        <p className="m-0 text-[15px]">
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
      <p className="ms2-muted m-0 mt-1 text-[15px]">These are reports on all devices with this product code, not on our simulated device.</p>
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
      {o.follow_up_capa && (
        <p className="m-0" data-testid="followup-capa">
          <span className="font-semibold">CAPA opened:</span> <span className="ms-code !text-[15px] !text-ink">{o.follow_up_capa.capa_id}</span> · owner {o.follow_up_capa.owner} · due{' '}
          {niceDate(o.follow_up_capa.due)}
          {o.follow_up_capa.due_planned ? ' (planned)' : ''} · {o.follow_up_capa.status}
        </p>
      )}
      <p className="m-0 ms2-muted">
        Signed and dated by {o.signed_by}, {o.signed_role}, {dateOf(o)}. The decision is the board's.
      </p>
    </>
  )
}

export function signalTitle(d: CompanyDevice | undefined, path: DecisionPath): string {
  if (path.signal.kind === 'sweep') return `Weekly sweep signal for ${d?.product_code ?? 'this product code'}`
  const pt = d?.patterns.find((x) => x.id === path.signal.pattern_id)
  if (!pt) return path.signal.pattern_id ?? 'Signal'
  return `${plain(pt.display_label)}${pt.kind === 'keyword' ? ' (keyword match)' : ''}`
}

/** The chip of a path: what the board recorded, with the same "Board ..." prefix when it assessed something. */
export function outcomeChip(path: DecisionPath): string {
  const o = path.outcome
  if (!o) return 'Decision due'
  if (o.kind === 'ntf') return 'Note to file'
  if (o.kind === 'capa') return 'CAPA opened'
  if (o.mdr.result === 'reportable') return 'Board assessed: reportable'
  if (o.recall.result === 'recall not warranted') return 'Board: recall not warranted'
  return 'Board assessed'
}

function outcomeSummary(o: DecisionOutcome | null): string {
  if (!o) return 'No outcome yet. The board decides after the meeting and signs the rationale.'
  if (o.kind === 'ntf') return `Note to file, signed by ${o.signed_by}.`
  if (o.kind === 'capa') return `${o.capa_id} opened, due ${niceDate(o.due)}${o.due_planned ? ' (planned)' : ''}.`
  return `MDR: ${o.mdr.result}. Correction or removal: ${o.correction_removal.result}. Recall: ${o.recall.result}.`
}

export function PathCard({ path, d, open }: { path: DecisionPath; d: CompanyDevice | undefined; open: boolean }) {
  const t = path.triage
  const b = path.board
  const o = path.outcome
  const when = o ? o.date : b.date
  return (
    <details className="ms2-dp" id={`dp-${path.id}`} open={open} data-testid="decision-path" data-state={path.state} data-outcome={o?.kind ?? 'open'}>
      <summary>
        <span className="ms2-dp-title">{signalTitle(d, path)}</span>
        <span className="ms2-dp-meta">
          <span className={path.state === 'open' ? 'ms2-pill ms2-pill--due' : 'ms2-pill'} data-testid="dp-chip">
            {outcomeChip(path)}
          </span>
          <span className="ms-num ms2-muted">{niceDate(when)}</span>
        </span>
      </summary>
      <ol className="ms2-stepper" aria-label="Decision path steps">
        <Step n={1} id="triage" title="Triage" state="done" summary={`Owner ${t.owner}, ${t.role} · ${dateOf(t)}.`} tags={t.tags}>
          <p className="m-0 ms2-muted">{t.note}</p>
        </Step>
        <Step
          n={2}
          id="board"
          title="PMS review board"
          state={b.held ? 'done' : 'planned'}
          summary={b.held ? `Met ${dateOf(b)}${b.decision ? `: ${b.decision}` : ''}` : `Meeting planned ${dateOf(b)}.`}
          tags={b.tags}
        >
          <p className="m-0">
            {b.held ? 'Attended' : 'Invited'}:{' '}
            {b.attendees.map((a) => `${a.name}, ${a.role === 'Design Engineering' ? 'Engineering' : a.role.replace(' Engineering', '').replace('Post-Market Surveillance', 'PMS')}`).join('; ')}
          </p>
          <div className="ms2-grid" data-testid="dp-evidence">
            <RealEvidence d={d} path={path} />
            <section className="ms2-card" aria-label="Company side (simulated)" data-testid="dp-company">
              <p className="ms2-simtag">{SIM_TAG}</p>
              <p className="ms2-h3">Company side</p>
              <p className="m-0">{b.summary}</p>
            </section>
          </div>
        </Step>
        <Step n={3} id="outcome" title="Outcome" state={o ? 'done' : 'pending'} summary={outcomeSummary(o)} tags={o?.tags}>
          {o && <Outcome o={o} />}
        </Step>
        <Step
          n={4}
          id="risk"
          title="Risk review"
          state={path.risk ? 'done' : 'pending'}
          summary={path.risk ? `Risk ${path.risk.before.score} before, ${path.risk.after.score} after${path.risk.after_is_expected ? ' (expected)' : ''}.` : 'Not reached yet: the risk file is reviewed once the board has an outcome.'}
          tags={path.risk?.tags}
          shown={path.risk && <RiskGrid before={path.risk.before} after={path.risk.after} expected={path.risk.after_is_expected} />}
        >
          {path.risk && (
            <>
              <p className="m-0">Health hazard evaluation (HHE) and ISO 14971 risk file. {path.risk.hhe_summary}</p>
              <p className="m-0 ms2-muted">
                Risk file {path.risk.risk_file.ref}: {path.risk.risk_file.change.toLowerCase()} · {dateOf(path.risk.risk_file)}.
              </p>
            </>
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
      <p className="ms2-simtag">{SIM_TAG}</p>
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
          {decision.paths.map((p) => (
            <PathCard key={p.id} path={p} d={d} open={p.state === 'open'} />
          ))}
        </div>
      )}
    </section>
  )
}
