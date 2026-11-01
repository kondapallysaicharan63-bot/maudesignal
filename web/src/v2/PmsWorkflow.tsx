// F26 Current workflow vs MaudeSignal. Route /pms-workflow (v2 layout).
// A drawn side-by-side map of how post-market surveillance is done today and where MaudeSignal helps, step by step.
// Honest by construction: every "What MaudeSignal does" line names something that exists (or is marked new), and every
// step where the work is a decision, a signature or a filing says so. No number on this page.
import type { ReactNode } from 'react'
import { HEADLINE } from '../positioning'
import './positioning.css'

export type StepKind = 'assist' | 'human'

export interface Step {
  id: string
  title: string
  kind: StepKind
  /** Marks for features that are being added (never shown as done). */
  tags: string[]
  manual: string
  does: string
  human: string
  clauses: string[]
}

export const HUMAN_ONLY = 'Stays human — MaudeSignal does not decide.'

export const STEPS: Step[] = [
  {
    id: 'complaint',
    title: 'Complaint received',
    kind: 'human',
    tags: [],
    manual: 'Log the complaint in your complaint system: device, product code, what happened.',
    does: 'Nothing at intake. Complaint records stay in your own system.',
    human: 'Receiving, logging and first assessing the complaint, including whether it must be reported.',
    clauses: ['ISO 13485 §8.2.1 (feedback)', 'ISO 13485 §8.2.2 (complaint handling)', '21 CFR 820 (QMSR)'],
  },
  {
    id: 'investigation',
    title: 'Investigation',
    kind: 'assist',
    tags: ['new'],
    manual: 'Collect the facts by hand and ask around whether anyone else has seen the same problem.',
    does: 'Investigate a complaint (F25): enter the device type and the problem; get similar events from FDA data, each fact with its FDA link.',
    human: 'Judging whether the events are really the same problem, and writing the investigation conclusion.',
    clauses: ['ISO 13485 §8.2.2 (complaint handling)', '21 CFR 820 (QMSR)', 'ISO 14971 (risk management)'],
  },
  {
    id: 'search',
    title: 'Manual MAUDE / recall / 510(k) search',
    kind: 'assist',
    tags: [],
    manual: 'Search MAUDE, recalls and 510(k) records one site at a time; copy counts and quotes into a document.',
    does: 'Similar-event search over FDA reports, recalls and 510(k) records. The claim gate recomputes every number and matches every quote to its record; a sentence it cannot match is withheld.',
    human: 'Choosing the search terms, reading the reports, and deciding which hits matter.',
    clauses: ['ISO 13485 §8.2.1 (feedback)', '21 CFR 803 (MDR)', '21 CFR 7 (recalls)'],
  },
  {
    id: 'trend',
    title: 'Trend review',
    kind: 'assist',
    tags: [],
    manual: 'Rebuild the counts by hand for the period and compare them with earlier periods.',
    does: 'Weekly change check for each device type you choose: this week against the four weeks before, with fixed rules (reports suddenly increased, more serious than usual, new kind of problem). The AI-device sweep runs the same check over FDA’s AI-enabled device list as the proactive extra.',
    human: 'Deciding whether a change matters for your device and your risk file.',
    clauses: ['ISO 13485 §8.2.1 (feedback)', 'ISO 14971 (risk management)', '21 CFR 820 (QMSR)'],
  },
  {
    id: 'board',
    title: 'PMS board',
    kind: 'assist',
    tags: [],
    manual: 'Assemble tables and slides for the board from separate sources.',
    does: 'CAPA-need evidence PDF: the figures and quotes for the board, each checked by the claim gate, with an independent Muse Wonder review of the PDF (findings only; it never edits the record).',
    human: 'The board assesses the evidence, reads the review’s findings and documents its conclusions.',
    clauses: ['ISO 13485 §8.2.1 (feedback)', 'ISO 13485 §8.5.2 (corrective action)', 'ISO 14971 (risk management)'],
  },
  {
    id: 'decision',
    title: 'Decision: note to file / CAPA / escalation',
    kind: 'human',
    tags: ['new, simulated'],
    manual: 'The board decides: note to file, CAPA, or escalation. Someone signs.',
    does: 'Records which named person approved or rejected the evidence pack, in a hash-chained audit trail. Simulated device profiles (F22) show a decision path for fictional devices only.',
    human: `${HUMAN_ONLY} The decision, the signature, and any report or filing (nothing is filed with FDA) are yours.`,
    clauses: [
      'ISO 13485 §8.5.2 (corrective action)',
      'ISO 13485 §8.2.3 (reporting to regulators)',
      '21 CFR 803 (MDR)',
      '21 CFR 806 (corrections and removals)',
      '21 CFR 7 (recalls)',
    ],
  },
  {
    id: 'report',
    title: 'PSUR / PMSR, management review',
    kind: 'human',
    tags: [],
    manual: 'Collect the period’s evidence again and write the report.',
    does: 'Supplies the same checked figures, quotes and FDA links to paste in. It does not write, review or sign the report.',
    human: 'Writing the report, running the management review, and documenting what was assessed.',
    clauses: ['ISO 13485 §8.2.1 (feedback)', 'ISO 14971 (risk management)', '21 CFR 820 (QMSR)'],
  },
  {
    id: 'audit',
    title: 'Audit',
    kind: 'assist',
    tags: [],
    manual: 'Trace each number back to its source, one document at a time.',
    does: 'Every number and quote carries its FDA link and passed the claim gate; the audit trail can be re-verified.',
    human: 'Auditing, and keeping your own quality records in your quality system.',
    clauses: ['ISO 13485 §8.2.1–8.2.3', 'ISO 13485 §8.5.2 (corrective action)', '21 CFR 820 (QMSR)'],
  },
]

const SHORT: Record<string, string> = {
  search: 'FDA search',
  decision: 'Decision',
  report: 'PSUR / PMSR',
}

/** The overview strip (desktop): one node per step, filled where MaudeSignal helps, outlined where it stays human. */
function Overview() {
  const W = 1000
  const step = W / STEPS.length
  return (
    <svg
      className="ms2-map-svg"
      viewBox={`0 0 ${W} 150`}
      role="img"
      aria-label="Overview: eight steps from complaint received to audit. MaudeSignal helps in the investigation, search, trend review, PMS board and audit steps. Intake, the decision and the report stay human."
      data-testid="pms-overview"
    >
      <title>Current workflow and where MaudeSignal helps</title>
      <line className="ms2-map-line" x1={step / 2} y1="40" x2={W - step / 2} y2="40" />
      {STEPS.map((s, i) => {
        const cx = step * i + step / 2
        return (
          <g key={s.id}>
            <circle className={s.kind === 'assist' ? 'ms2-map-node ms2-map-node--assist' : 'ms2-map-node'} cx={cx} cy="40" r="16" />
            <text className={s.kind === 'assist' ? 'ms2-map-n ms2-map-n--on' : 'ms2-map-n'} x={cx} y="45" textAnchor="middle">
              {i + 1}
            </text>
            <text className="ms2-map-t" x={cx} y="82" textAnchor="middle">
              {SHORT[s.id] ?? s.title}
            </text>
            <text className="ms2-map-k" x={cx} y="106" textAnchor="middle">
              {s.kind === 'assist' ? 'MaudeSignal helps' : 'Stays human'}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

function Field({ label, children, id }: { label: string; children: ReactNode; id: string }) {
  return (
    <div className="ms2-step-f" role="group" aria-labelledby={id}>
      <h3 id={id} className="ms2-step-fh">
        {label}
      </h3>
      {children}
    </div>
  )
}

export function PmsWorkflow({ onRoi }: { onRoi?: () => void }) {
  return (
    <div className="ms2-pos" data-testid="pms-page">
      <header className="ms2-pagehead">
        <h1 className="ms2-h1">How MaudeSignal fits your PMS workflow</h1>
        <p className="ms2-lead">{HEADLINE}</p>
        <p className="ms2-lead">
          Post-market surveillance usually starts when a complaint arrives and is reviewed on a schedule: trend reviews, the PMS board, the PSUR or PMSR, management review and audits. This map follows that order. It shows what is done by hand today, what MaudeSignal does at each step, and what stays with your people.
        </p>
      </header>

      <div className="ms2-map-wrap">
        <Overview />
      </div>

      <ol className="ms2-steps" aria-label="Workflow steps" data-testid="pms-steps">
        {STEPS.map((s, i) => (
          <li key={s.id} className={`ms2-step ms2-step--${s.kind}`} data-testid={`pms-step-${s.id}`} aria-labelledby={`pms-${s.id}-h`}>
            <div className="ms2-step-head">
              <span className="ms2-step-n" aria-hidden="true">
                {i + 1}
              </span>
              <h2 id={`pms-${s.id}-h`} className="ms2-h2">
                {s.title}
              </h2>
              {s.tags.map((t) => (
                <span key={t} className="ms2-tag" data-testid={`pms-tag-${s.id}`}>
                  {t[0].toUpperCase() + t.slice(1)}
                </span>
              ))}
            </div>
            <div className="ms2-step-grid">
              <Field id={`pms-${s.id}-m`} label="Manual today">
                <p>{s.manual}</p>
              </Field>
              <Field id={`pms-${s.id}-d`} label="What MaudeSignal does">
                <p>{s.does}</p>
              </Field>
              <Field id={`pms-${s.id}-h2`} label="What stays human">
                <p>{s.human}</p>
              </Field>
              <Field id={`pms-${s.id}-c`} label="Clauses it serves">
                <ul>
                  {s.clauses.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              </Field>
            </div>
          </li>
        ))}
      </ol>

      <section className="ms2-card mt-6" aria-labelledby="pms-extra-h" data-testid="pms-extra">
        <h2 id="pms-extra-h" className="ms2-h2">
          The proactive extra
        </h2>
        <p className="ms2-muted m-0 mt-1">
          The weekly change check for the device types you choose, and the AI-device sweep, look ahead of any complaint. They feed the trend review above; they do not replace it.
        </p>
      </section>

      {onRoi && (
        <button type="button" className="ms2-link mt-4" onClick={onRoi} data-testid="pms-roi-link">
          Time and cost: measured, not claimed →
        </button>
      )}

      <p className="ms2-muted mt-4 text-[15px]">
        MaudeSignal is not clinical decision support and not an FDA-cleared device. Clause names are the standards’ own headings, listed so you can map the step to your procedures; this page does not say any step satisfies a clause.
      </p>
    </div>
  )
}
