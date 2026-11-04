// /validation (PRD-18, PRD-26): "This build is not validated", what is tested (measured, with the command), the FDA
// AI/ML guidance path for a QMS software tool, what a manufacturer must still do, the evidence lifecycle log (read from
// lifecycle.json, generated from the repo), the LLZ keyword-matching measurement and the planned study protocol. Never "FDA validated", "FDA approved"
// or "AI validated".
import { useEffect, useState } from 'react'
import type { WorkspaceData } from '../types'
import { BUILD_COMMIT, BUILD_VERSION } from './build'
import { DataAsOfBanner, storedAsOf } from './DataAsOf'

export const NOT_VALIDATED =
  'This build is not validated. It is a hackathon build. Nothing on this page says it is fit for your quality system; that is your decision, made in your own environment.'

/** Measured on 2026-11-03 (outputs in release-out/2026-11-03/, see TEST-REPORT-2026-11-03.md). A test pins the gate count to the fixture. */
export const TESTED: { what: string; result: string; how: string }[] = [
  { what: 'Python unit tests', result: 'Python 3.12: 2,574 passed, 0 skipped, 85% line + branch coverage (pytest-cov, rounded). Python 3.11: 2,573 passed, 1 skipped (lxml not installed). Run 2026-11-03.', how: 'pytest tests/unit --cov=src/maudesignal --cov-branch' },
  { what: 'Web unit tests', result: '722 passed in 34 files (vitest, run 2026-11-03)', how: 'cd web && npx vitest run' },
  { what: 'Claim gate adversarial set', result: '139 cases (90 must be withheld, 49 must pass): 0 false passes, 0 false blocks. 9 were added on 2026-11-03: report-mix share, quote pinned to the wrong report, number with no claim, date-shifted year, zero on a no-data range.', how: 'tests/fixtures/gate/adversarial.jsonl via tests/unit/test_gate.py' },
  {
    what: 'Hand-check of recorded answers',
    result:
      '27 of 28 answers fully correct. Retrospective, on fixed demo questions, checked by Claude; an independent check by Charan is pending. This is not a field accuracy rate.',
    how: 'docs/hackathon/HAND_CHECK.md',
  },
  { what: 'Audit tamper test', result: 'Editing one stored entry breaks the chain at that entry and is detected (database, exported trail, and this browser’s trail)', how: 'tests/unit/test_pms.py, test_copilot_agent.py; web/src/pms/pms.test.ts' },
  { what: 'Spend caps', result: 'Code defaults (environment can override): keyed ask $0.25 per call and $2.00 a day; live website $3.00 a day in total; Streamlit copilot $1 and 20 calls per session and $10 a day. A cap hit makes no model call (94 cap and ledger tests passed 2026-11-03).', how: 'tests/unit/test_spend.py, test_call_ledger.py, test_connector_batch_o.py' },
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
  'The Muse Wonder review of the evidence pack is findings only. It is a model, not a human reviewer, and it decides nothing.',
  'Live data: the stored snapshot (137 MAUDE reports, newest 2026-08-31) is not refreshed by a scraper. The live path is the openFDA check on Investigate, which shows its own check date on every run.',
  'Own devices: there is no own-devices page from MAUDE alone. The closest paths are Signals (reports you did not file), Investigate by product code, and the PMS board.',
]

export interface KeywordMeasurement {
  product_code: string
  term: string
  match_rule: string
  problem: string
  stored_reports: number
  matched: number
  same_problem: number
  different_image_problem: number
  mention_only: number
  pct_same_problem: number
  pct_too_broad: number
  adjudicator: string
  sample: string
  rows: { report_id: string; label: string; reason: string }[]
  recalls: { stored: number; mention_image_any_field: number; mention_image_in_reason: number; mention_image_in_product_description: number }
  limits: string[]
  method: string
}

function useJson<T>(name: string): T | null | 'error' {
  const [v, setV] = useState<T | null | 'error'>(null)
  useEffect(() => {
    let live = true
    fetch(`${import.meta.env.BASE_URL ?? './'}data/${name}`)
      .then((r) => (r.ok ? (r.json() as Promise<T>) : Promise.reject(new Error(String(r.status)))))
      .then((d) => live && setV(d))
      .catch(() => live && setV('error'))
    return () => {
      live = false
    }
  }, [name])
  return v
}

/** P1 item G: how often a word match on stored LLZ narratives is about the complaint's problem. Read from keyword_measurement.json. */
export function KeywordMeasurementCard({ km }: { km: KeywordMeasurement | null | 'error' }) {
  return (
    <section className="ms2-card mt-4" aria-labelledby="v-kw" data-testid="validation-keyword">
      <h2 id="v-kw" className="ms2-h2">
        Keyword matching: measured on stored LLZ reports
      </h2>
      {km === null ? (
        <p className="ms2-muted">Loading keyword_measurement.json…</p>
      ) : km === 'error' ? (
        <p className="ms2-bad" data-testid="validation-keyword-missing">
          Measurement not shown: keyword_measurement.json could not be loaded.
        </p>
      ) : (
        <>
          <p className="m-0 mt-2" data-testid="validation-keyword-summary">
            Term <span className="ms-code">{km.term}</span> ({km.match_rule}) on {km.stored_reports} stored {km.product_code} reports: {km.matched} matched. Read
            against the problem &ldquo;{km.problem}&rdquo;: <strong>{km.same_problem} of {km.matched} ({km.pct_same_problem}%)</strong> describe that problem;{' '}
            {km.matched - km.same_problem} of {km.matched} ({km.pct_too_broad}%) are too broad ({km.different_image_problem} a different image problem,{' '}
            {km.mention_only} a mention only). Sample: {km.sample}. Adjudicator: {km.adjudicator}.
          </p>
          <p className="ms-banner ms-banner--warn mt-2" role="note" data-testid="validation-keyword-recalls">
            <span>
              A word match alone is too broad: {km.recalls.mention_image_any_field} of {km.recalls.stored} stored {km.product_code} recall records contain
              &ldquo;image&rdquo; somewhere in the record ({km.recalls.mention_image_in_product_description} in the product description,{' '}
              {km.recalls.mention_image_in_reason} in the recall reason). Investigate shows &ldquo;Why matched&rdquo; on every result for this reason.
            </span>
          </p>
          <div className="ms2-inv-scroll mt-2">
            <table className="ms2-table" data-testid="validation-keyword-rows">
              <caption className="sr-only">Each matched report and its label</caption>
              <thead>
                <tr>
                  <th scope="col">Report</th>
                  <th scope="col">Label</th>
                  <th scope="col">Reason</th>
                </tr>
              </thead>
              <tbody>
                {km.rows.map((r) => (
                  <tr key={r.report_id}>
                    <th scope="row" className="ms-code">
                      {r.report_id}
                    </th>
                    <td>{r.label}</td>
                    <td className="ws-wrap">{r.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="m-0 mt-2" data-testid="validation-keyword-limits">
            {km.limits.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
          <p className="ms2-inv-meta m-0 mt-2">Method: {km.method}.</p>
        </>
      )}
    </section>
  )
}

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
  return useJson<Lifecycle>('lifecycle.json')
}

export function ValidationPage({ data, onBoard }: { data: WorkspaceData; onBoard?: () => void }) {
  const lc = useLifecycle()
  const km = useJson<KeywordMeasurement>('keyword_measurement.json')
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

      <KeywordMeasurementCard km={km} />

      <section className="ms2-card mt-4" aria-labelledby="v-path">
        <h2 id="v-path" className="ms2-h2">
          FDA AI/ML guidance path
        </h2>
        <p className="m-0 mt-2">
          The validation path follows FDA&apos;s Good Machine Learning Practice (GMLP) guiding principles and its lifecycle and predetermined change
          control thinking for AI-enabled software, applied to MaudeSignal as a <strong>software tool used inside a quality system</strong>, not as a
          cleared device. MaudeSignal is not a medical device, not clinical decision support and not FDA-cleared. For a reviewer the answer is: not
          validated; here is the evidence for a hackathon build, and here is what your QMS still has to do.
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
          Next evidence step (planned, not run): a prospective study on one real code
        </h2>
        <p className="m-0 mt-2" data-testid="validation-protocol">
          One product code the study team owns, the same week: MaudeSignal&apos;s flags against the team&apos;s own complaint and MDR log, adjudicated
          by a person, with rules for a hit, a miss and a false flag set before the week starts. Recorded: flags raised, flags accepted or rejected,
          signals the team found that the tool missed, and every human correction (accept/reject, withheld sentences, overrides). The
          retrospective hand-check above is the low end of the evidence hierarchy; this study would be a deployed-system study at N = 1 code, not a
          randomised trial. It has not been run.
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
