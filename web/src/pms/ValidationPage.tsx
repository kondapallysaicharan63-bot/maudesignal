// /validation (PRD-18, PRD-26): "This build is not validated", what is tested (measured, with the command), the FDA
// AI/ML guidance path for a QMS software tool, what a manufacturer must still do, the evidence lifecycle log (read from
// lifecycle.json, generated from the repo) and the prospective trial protocol. Never "FDA validated", "FDA approved"
// or "AI validated".
import { useEffect, useState } from 'react'
import type { WorkspaceData } from '../types'
import { BUILD_COMMIT, BUILD_VERSION } from './build'
import { DataAsOfBanner, storedAsOf } from './DataAsOf'

export const NOT_VALIDATED =
  'This build is not validated. It is a hackathon trial build. Nothing on this page says it is fit for your quality system; that is your decision, made in your own environment.'

/** Measured on 2026-11-03 (see TEST-REPORT-2026-11-03.md for the run and the command). Counts, not claims. */
export const TESTED: { what: string; result: string; how: string }[] = [
  { what: 'Python unit tests', result: '2,587 passed, 1 skipped (lxml not installed); 85% line + branch coverage', how: 'pytest tests/unit --cov=src/maudesignal (Python 3.11 and 3.12)' },
  { what: 'Web unit tests', result: '735 passed (vitest)', how: 'cd web && npx vitest run' },
  { what: 'Claim gate adversarial set', result: '135 cases (89 must be withheld, 46 must pass): 0 false passes, 0 false blocks', how: 'tests/fixtures/gate/adversarial.jsonl via tests/unit/test_gate.py' },
  {
    what: 'Hand-check of recorded answers',
    result:
      '27 of 28 answers fully correct. Retrospective, on fixed demo questions, checked by Claude; an independent check by Charan is pending. This is not a field accuracy rate.',
    how: 'docs/hackathon/HAND_CHECK.md',
  },
  { what: 'Audit tamper test', result: 'Editing one stored entry breaks the chain at that entry and is detected (database, exported trail, and this browser’s trail)', how: 'tests/unit/test_pms.py, test_copilot_agent.py; web/src/pms/pms.test.ts' },
  { what: 'Spend caps', result: '$0.25 per call and $2.00 a day for asks, $1 and 20 calls per session, $10 a day overall; a cap hit makes no model call', how: 'tests/unit/test_spend.py, connector cap tests' },
]

export const MANUFACTURER_MUST = [
  'Define the intended use of MaudeSignal inside your own QMS (a PMS support tool; not a medical device, not clinical decision support).',
  'Trace your own requirements to tests (a requirements trace matrix for the functions you use).',
  'Run IQ/OQ/PQ, or CSA-style assurance, in your own environment, on your own product codes and your own complaint data.',
  'Add authenticated electronic signatures and access control if records are signed in the tool (this build has no login and no Part 11 signature).',
  'Put the model id, every Skill version and the gate CFR list under change control; re-test after any change.',
  'Re-check periodically: re-run the hand-check and the gate set on your codes, and compare flags with your own complaint and MDR log.',
]

export const KNOWN_LIMITS = [
  'API limits, cost totals, cache and audit are per server instance and in memory; they reset on a cold start.',
  'No login and no 21 CFR Part 11 electronic signature. The board and the browser audit trail live in this browser only.',
  'Demo universe is 4 product codes / 137 stored reports, so no general accuracy is claimed.',
  'Negative answers ("no relevant papers are on file") carry no claim, so the gate does not check them.',
  'Completeness is not gated: the gate checks what is said, not what was left out (one recall answer once missed three stored recalls).',
  'No denominator: MAUDE counts are not rates; units in use are not known.',
  'Own-company separation is not possible from MAUDE alone; a maker must match reports to its own complaint log.',
]

interface Lifecycle {
  build: { version: string; commit: string | null }
  models: Record<string, string>
  skills: Record<string, string>
  gate_cfr_sections: string[]
  gate_superseded_sections: string[]
  sweep: { checked_utc: string | null; window: { current_start?: string; current_end?: string } | null }
  revalidation_trigger: string
}

function useLifecycle(): Lifecycle | null | 'error' {
  const [v, setV] = useState<Lifecycle | null | 'error'>(null)
  useEffect(() => {
    let live = true
    fetch(`${import.meta.env.BASE_URL ?? './'}data/lifecycle.json`)
      .then((r) => (r.ok ? (r.json() as Promise<Lifecycle>) : Promise.reject(new Error(String(r.status)))))
      .then((d) => live && setV(d))
      .catch(() => live && setV('error'))
    return () => {
      live = false
    }
  }, [])
  return v
}

export function ValidationPage({ data, onBoard }: { data: WorkspaceData; onBoard?: () => void }) {
  const lc = useLifecycle()
  return (
    <div data-testid="validation-page">
      <header className="ms2-pagehead">
        <h1 className="ms2-h1">Validation and evidence lifecycle</h1>
        <p className="ms2-lead">What is tested, what is not, and what your quality system still has to do.</p>
      </header>
      <p className="ms-banner ms-banner--warn" role="note" data-testid="not-validated">
        <span>
          <strong>{NOT_VALIDATED}</strong>
        </span>
      </p>
      <p className="ms2-inv-meta m-0">
        Build {BUILD_VERSION} · commit <span className="ms-code" data-testid="validation-commit">{BUILD_COMMIT}</span>
      </p>
      <DataAsOfBanner asOf={storedAsOf(data.manifest)} testid="validation-asof" />

      <section className="ms2-card mt-4" aria-labelledby="v-tested">
        <h2 id="v-tested" className="ms2-h2">
          What is tested (measured, not claimed)
        </h2>
        <table className="ms2-table mt-2" data-testid="validation-tested">
          <thead>
            <tr>
              <th scope="col">Check</th>
              <th scope="col">Result</th>
              <th scope="col">How to reproduce</th>
            </tr>
          </thead>
          <tbody>
            {TESTED.map((t) => (
              <tr key={t.what}>
                <th scope="row">{t.what}</th>
                <td className="ws-wrap">{t.result}</td>
                <td className="ms-code ws-wrap">{t.how}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="ms2-card mt-4" aria-labelledby="v-path">
        <h2 id="v-path" className="ms2-h2">
          FDA AI/ML guidance path
        </h2>
        <p className="m-0 mt-2">
          The validation path follows FDA&apos;s Good Machine Learning Practice (GMLP) guiding principles and its lifecycle and predetermined change
          control thinking for AI-enabled software, applied to MaudeSignal as a <strong>software tool used inside a quality system</strong>, not as a
          cleared device. MaudeSignal is not a medical device, not clinical decision support and not FDA-cleared. For a reviewer the answer is: not
          validated; here is the evidence for a trial build, and here is what your QMS still has to do.
        </p>
      </section>

      <section className="ms2-card mt-4" aria-labelledby="v-must">
        <h2 id="v-must" className="ms2-h2">
          What a manufacturer must still do
        </h2>
        <ol className="m-0 mt-2" data-testid="validation-must">
          {MANUFACTURER_MUST.map((m) => (
            <li key={m}>{m}</li>
          ))}
        </ol>
      </section>

      <section className="ms2-card mt-4" aria-labelledby="v-life">
        <h2 id="v-life" className="ms2-h2">
          Lifecycle log (change control)
        </h2>
        {lc === null ? (
          <p className="ms2-muted">Loading lifecycle.json…</p>
        ) : lc === 'error' ? (
          <p className="ms2-bad">lifecycle.json could not be loaded.</p>
        ) : (
          <div data-testid="validation-lifecycle">
            <dl className="ms2-pms-dl">
              <dt>Build</dt>
              <dd className="ms-code">
                {lc.build.version} · {lc.build.commit ?? 'unknown'} (data export)
              </dd>
              <dt>Models</dt>
              <dd>
                {Object.entries(lc.models)
                  .map(([k, v]) => `${k}: ${v}`)
                  .join(' · ')}
              </dd>
              <dt>Skill versions</dt>
              <dd data-testid="validation-skills">
                {Object.entries(lc.skills)
                  .map(([k, v]) => `${k} ${v}`)
                  .join(' · ')}
              </dd>
              <dt>Gate CFR list</dt>
              <dd>
                Allowed: {lc.gate_cfr_sections.join(', ')}. Blocked as superseded: {lc.gate_superseded_sections.join(', ')}.
              </dd>
              <dt>Sweep</dt>
              <dd data-testid="validation-sweep">
                checked {lc.sweep.checked_utc?.slice(0, 10) ?? 'not stated'} · openFDA week {lc.sweep.window?.current_start} to {lc.sweep.window?.current_end}
              </dd>
              <dt>Re-validation trigger</dt>
              <dd>{lc.revalidation_trigger}</dd>
            </dl>
          </div>
        )}
      </section>

      <section className="ms2-card mt-4" aria-labelledby="v-trial">
        <h2 id="v-trial" className="ms2-h2">
          Next evidence step: a prospective trial on one real code
        </h2>
        <p className="m-0 mt-2" data-testid="validation-protocol">
          One product code the trial team owns, the same week: MaudeSignal&apos;s flags against the team&apos;s own complaint and MDR log, adjudicated
          by a person, with rules for a hit, a miss and a false flag set before the week starts. Recorded: flags raised, flags accepted or rejected,
          signals the team found that the tool missed, time per task, and every human correction (accept/reject, withheld sentences, overrides). The
          retrospective hand-check above is the low end of the evidence hierarchy; this trial is a deployed-system study at N = 1 code, not a
          randomised trial.
        </p>
        <p className="ms2-inv-meta m-0 mt-2">
          Framing: Themes in Clinical AI for 2025-2026, SAIL Year in Review, Table 1, as shared by a regulatory reviewer (themes 1, 2 and 4 only:
          evaluation, workflow integration, regulation). MaudeSignal is not consumer-facing, makes no education claim and trains no foundation model.
        </p>
      </section>

      <section className="ms2-card mt-4" aria-labelledby="v-limits">
        <h2 id="v-limits" className="ms2-h2">
          Known limits that remain
        </h2>
        <ul className="m-0 mt-2" data-testid="validation-limits">
          {KNOWN_LIMITS.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
        {onBoard && (
          <button type="button" className="ms2-link mt-2" onClick={onBoard} style={{ minHeight: 44 }}>
            PMS board →
          </button>
        )}
      </section>
    </div>
  )
}
