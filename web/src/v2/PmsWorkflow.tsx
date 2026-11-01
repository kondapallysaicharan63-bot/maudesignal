// F26 Current workflow vs MaudeSignal. Route /pms-workflow (v2 layout).
// A side-by-side map of how post-market surveillance is done today and where MaudeSignal helps, step by step.
// Every "What MaudeSignal does" line names a function of the product; new ones are marked new. Every step where the
// work is a decision, a signature or a filing says so. No number is typed on this page (counts are computed).
import type { ReactNode } from 'react'
import { HEADLINE } from '../positioning'
import { appRoot, withLayout } from './router'
import './positioning.css'

export type StepKind = 'assist' | 'human'

export interface Step {
  id: string
  /** The name used in the overview strip and as the card title. */
  title: string
  /** The longer name, shown under the title. */
  detail?: string
  kind: StepKind
  /** "New" on the card title (a function being added). */
  isNew?: boolean
  manual: string
  does: string
  /** A function that is new and simulated, said on its own sentence with its own chip. */
  doesNew?: { tag: string; text: string }
  /** What the person decides, written to follow "You decide:". */
  human: string
  clauses: string[]
}

export const HUMAN_ONLY = 'Stays human — MaudeSignal does not decide.'

export const STEPS: Step[] = [
  {
    id: 'complaint',
    title: 'Complaint received',
    kind: 'human',
    manual: 'Log the complaint in your complaint system: device, product code, what happened.',
    does: 'Nothing at intake. Complaint records stay in your own system.',
    human: 'how the complaint is received, logged and first assessed, including whether it must be reported.',
    clauses: ['ISO 13485 §8.2.1 (feedback)', 'ISO 13485 §8.2.2 (complaint handling)', '21 CFR 820 (QMSR)'],
  },
  {
    id: 'investigation',
    title: 'Investigation',
    kind: 'assist',
    isNew: true,
    manual: 'Collect the facts by hand and ask around whether anyone else has seen the same problem.',
    does: 'Investigate a complaint (new): enter the product code and the problem; get the problems reported on devices of the same type (any maker) from FDA data, each fact with its FDA link. For the complaints team: the evidence feeds your known-effects record.',
    human: 'whether the events are really the same problem, and what the investigation concludes.',
    clauses: ['ISO 13485 §8.2.2 (complaint handling)', '21 CFR 820 (QMSR)', 'ISO 14971 (risk management)'],
  },
  {
    id: 'search',
    title: 'FDA search',
    detail: 'MAUDE, recall and 510(k) search',
    kind: 'assist',
    manual: 'Search MAUDE, recalls and 510(k) records one site at a time; copy counts and quotes into a document.',
    does: "Search of problems reported on other makers' devices of the same type: FDA reports, recalls and 510(k) records. The claim gate recomputes every number and matches every quote to its record; a sentence it cannot match is withheld.",
    human: 'the search terms, which reports to read, and which hits matter.',
    clauses: ['ISO 13485 §8.2.1 (feedback)', '21 CFR 7, Subpart C (recalls)'],
  },
  {
    id: 'trend',
    title: 'Trend review',
    kind: 'assist',
    manual: 'Rebuild the counts by hand for the period and compare them with earlier periods.',
    does: 'Weekly change check for each device type you choose: this week against the four weeks before, with fixed rules (reports suddenly increased, more serious than usual, new kind of problem). The AI-device sweep runs the same check over FDA’s AI-enabled device list as the proactive extra.',
    human: 'whether a change matters for your device and your risk file.',
    clauses: ['ISO 13485 §8.2.1 (feedback)', 'ISO 14971 (risk management)', '21 CFR 820 (QMSR)'],
  },
  {
    id: 'board',
    title: 'PMS board',
    kind: 'assist',
    manual: 'Assemble tables and slides for the board from separate sources.',
    does: 'CAPA-need evidence PDF: the figures and quotes for the board, each checked by the claim gate, with an independent Muse Wonder review of the PDF (findings only; it never edits the record).',
    human: 'what the board assesses from the evidence and the review’s findings, and what it documents.',
    clauses: ['ISO 13485 §8.2.1 (feedback)', 'ISO 13485 §8.5.2 (corrective action)', 'ISO 14971 (risk management)'],
  },
  {
    id: 'decision',
    title: 'Decision',
    detail: 'Note to file, CAPA or escalation',
    kind: 'human',
    manual: 'The board decides: note to file, CAPA, or escalation. Someone signs.',
    does: 'Records which named person approved or rejected the evidence pack, in a hash-chained audit trail.',
    doesNew: {
      tag: 'New, simulated',
      text: 'A decision path on simulated device profiles (F22), for fictional devices only.',
    },
    human: `the decision, the signature, and any report or filing (nothing is filed with FDA). ${HUMAN_ONLY}`,
    clauses: [
      'ISO 13485 §8.5.2 (corrective action)',
      'ISO 13485 §8.2.3 (reporting to regulators)',
      '21 CFR 803 (MDR)',
      '21 CFR 806 (corrections and removals)',
      '21 CFR 7, Subpart C (recalls)',
    ],
  },
  {
    id: 'report',
    title: 'PSUR / PMSR',
    detail: 'PSUR or PMSR, and management review',
    kind: 'human',
    manual: 'Collect the period’s evidence again and write the report.',
    does: 'Supplies the same checked figures, quotes and FDA links to paste in. It does not write, review or sign the report.',
    human: 'the report, the management review, and what is documented as assessed.',
    clauses: ['ISO 13485 §8.2.1 (feedback)', 'ISO 14971 (risk management)', '21 CFR 820 (QMSR)'],
  },
  {
    id: 'audit',
    title: 'Audit',
    kind: 'assist',
    manual: 'Trace each number back to its source, one document at a time.',
    does: 'Every number and quote carries its FDA link and passed the claim gate; the audit trail can be re-verified.',
    human: 'the audit itself, and keeping your own quality records in your quality system.',
    clauses: ['ISO 13485 §8.2.1–8.2.3', 'ISO 13485 §8.5.2 (corrective action)', '21 CFR 820 (QMSR)'],
  },
]

const KIND_TEXT: Record<StepKind, string> = { assist: 'MaudeSignal helps', human: 'Stays human' }

/** The address of another v2 page, keeping the app folder, ?r= and ?layout. */
function pageHref(segment: string): string {
  const loc = typeof window === 'undefined' ? { pathname: '/', search: '' } : window.location
  return `${appRoot(loc.pathname)}${segment}${withLayout(loc.search, import.meta.env.VITE_LAYOUT_DEFAULT as string | undefined)}`
}

/** The overview strip (wide screens): one numbered anchor per step with an arrow to the next. */
function Overview() {
  return (
    <nav className="ms2-strip" aria-label="The eight steps" data-testid="pms-overview">
      <ol>
        {STEPS.map((s, i) => (
          <li key={s.id} className={s.kind === 'assist' ? 'ms2-strip-li ms2-strip-li--assist' : 'ms2-strip-li'}>
            <a href={`#step-${i + 1}`} className="ms2-strip-a">
              <span className="ms2-strip-n" aria-hidden="true">
                {i + 1}
              </span>
              <span className="ms2-strip-t">{s.title}</span>
              <span className="ms2-strip-k">{KIND_TEXT[s.kind]}</span>
            </a>
          </li>
        ))}
      </ol>
    </nav>
  )
}

function Field({ label, children, id, className = '' }: { label: string; children: ReactNode; id: string; className?: string }) {
  return (
    <div className={`ms2-step-f ${className}`} role="group" aria-labelledby={id}>
      <h3 id={id} className="ms2-step-fh">
        {label}
      </h3>
      {children}
    </div>
  )
}

export function PmsWorkflow({ onRoi, onHome, onInvestigate }: { onRoi?: () => void; onHome?: () => void; onInvestigate?: () => void }) {
  const helped = STEPS.filter((s) => s.kind === 'assist').length
  const human = STEPS.length - helped
  return (
    <div className="ms2-pos" data-testid="pms-page">
      {onHome && (
        <nav aria-label="Breadcrumb" className="ms2-crumb">
          <button type="button" className="ms2-quietlink" onClick={onHome} data-testid="crumb-home">
            ← Home
          </button>
        </nav>
      )}
      <header className="ms2-pagehead">
        <h1 className="ms2-h1">How MaudeSignal fits your PMS workflow</h1>
        <p className="ms2-lead">{HEADLINE}</p>
        <p className="ms2-lead">
          Post-market surveillance usually starts when a complaint arrives and is reviewed on a schedule: trend reviews, the PMS board, the PSUR or PMSR, management review and audits. This map follows that order. It shows what is done by hand today, what MaudeSignal does at each step, and what stays with your people.
        </p>
      </header>

      <Overview />
      <p className="ms2-muted ms2-step-sum" data-testid="pms-summary">
        {STEPS.length} steps · {helped} where MaudeSignal helps · {human} stay human
      </p>

      <ol className="ms2-steps" aria-label="Workflow steps" data-testid="pms-steps">
        {STEPS.map((s, i) => (
          <li key={s.id} id={`step-${i + 1}`} className={`ms2-step ms2-step--${s.kind}`} data-testid={`pms-step-${s.id}`} aria-labelledby={`pms-${s.id}-h`}>
            <div className="ms2-step-head">
              <span className="ms2-step-n" aria-hidden="true">
                {i + 1}
              </span>
              <h2 id={`pms-${s.id}-h`} className="ms2-h2">
                {s.title}
              </h2>
              {s.isNew && (
                <span className="ms2-tag" data-testid={`pms-tag-${s.id}`}>
                  New
                </span>
              )}
              <span className="ms2-tag ms2-tag--kind" data-testid={`pms-kind-${s.id}`}>
                {KIND_TEXT[s.kind]}
              </span>
            </div>
            {s.detail && <p className="ms2-step-detail">{s.detail}</p>}
            <div className="ms2-step-grid">
              <Field id={`pms-${s.id}-m`} label="Manual today" className="ms2-step-f--manual">
                <p>{s.manual}</p>
              </Field>
              <Field id={`pms-${s.id}-d`} label="What MaudeSignal does">
                <p>{s.does}</p>
                {s.id === 'investigation' && (
                  <p>
                    <a
                      className="ms2-a"
                      href={pageHref('investigate')}
                      data-testid="pms-investigate-link"
                      onClick={(e) => {
                        if (onInvestigate && e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey) {
                          e.preventDefault()
                          onInvestigate()
                        }
                      }}
                    >
                      Open Investigate a complaint
                    </a>
                  </p>
                )}
                {s.doesNew && (
                  <p>
                    <span className="ms2-tag" data-testid={`pms-tag-${s.id}`}>
                      {s.doesNew.tag}
                    </span>{' '}
                    {s.doesNew.text}
                  </p>
                )}
              </Field>
              <Field id={`pms-${s.id}-h2`} label="What stays human" className="ms2-step-f--human">
                <p>
                  <strong>You decide:</strong> {s.human}
                </p>
              </Field>
              <Field id={`pms-${s.id}-c`} label="Related clauses" className="ms2-step-f--clauses">
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
