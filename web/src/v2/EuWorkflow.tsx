// EU MDR workflow relevance (/eu). Workflow mapping only: this build holds FDA data only and claims no EU data
// coverage. Nothing here says a step satisfies an article; the mapping says where the same evidence would be read.
import { DataAsOfBanner, type AsOf } from '../pms/DataAsOf'

export const EU_LABEL = 'Demo data is FDA-only. No EUDAMED data in this build.'
export const EU_NOT_PUBLIC =
  'EUDAMED is not a public adverse-event database like MAUDE, so EU reports cannot be searched here. No EU national competent authority data is included either.'
export const MDR_URL = 'https://eur-lex.europa.eu/eli/reg/2017/745/oj'

interface Row {
  step: string
  eu: string
  human: string
}

/** Where the same MaudeSignal step would be read in an EU MDR (Regulation (EU) 2017/745) PMS workflow. */
export const EU_ROWS: Row[] = [
  {
    step: 'Morning brief and Signals: what changed for a device type, with the openFDA query behind each number',
    eu: 'Input to the PMS system and PMS plan (Articles 83 and 84): one external source among those the plan names. FDA data only.',
    human: 'Your PMS plan decides which sources count and how often they are reviewed.',
  },
  {
    step: 'Investigate a complaint: similar FDA reports, recalls and clearances for the product code, with why each matched',
    eu: 'Background for the complaint and vigilance assessment of a possible serious incident (Article 87). FDA reports are context, not EU reports.',
    human: 'Whether an event is a serious incident, and any report to a competent authority, is decided by your vigilance team.',
  },
  {
    step: 'PMS board: status, owner and advisory due date for each flagged code',
    eu: 'A record of review that the PMS report or PSUR (Articles 85 and 86) can point to.',
    human: 'The PSUR and its conclusions are written and signed by your people.',
  },
  {
    step: 'Escalation checklist and recall check in the evidence pack',
    eu: 'Questions for trend reporting (Article 88) and for a field safety corrective action assessment (Articles 87 and 89).',
    human: 'The checklist asks; it never decides. FSCA need is decided by your people under your own procedure.',
  },
  {
    step: 'Note to file and the hash-chained audit trail',
    eu: 'Supporting documentation for the PMS file and technical documentation (Annex III).',
    human: 'Your QMS holds the controlled record. MaudeSignal is not a QMS.',
  },
]

export function EuWorkflow({ asOf }: { asOf?: AsOf }) {
  return (
    <div data-testid="eu-page">
      <header className="ms2-pagehead">
        <h1 className="ms2-h1">EU MDR: workflow relevance only</h1>
        <p className="ms2-lead">
          How the same steps would sit in an EU MDR post-market surveillance workflow. This is a map of where the evidence would be read, not EU data and not a
          statement that any step meets an article.
        </p>
      </header>
      <p className="ms-banner ms-banner--warn" role="note" data-testid="eu-label">
        <span>
          <strong>{EU_LABEL}</strong> {EU_NOT_PUBLIC}
        </span>
      </p>
      {asOf && <DataAsOfBanner asOf={asOf} testid="eu-asof" />}
      <div className="ms2-inv-scroll mt-3">
        <table className="ms2-table" data-testid="eu-table">
          <caption className="sr-only">MaudeSignal steps mapped to an EU MDR PMS workflow</caption>
          <thead>
            <tr>
              <th scope="col">MaudeSignal step (FDA data)</th>
              <th scope="col">Where it would be read under EU MDR</th>
              <th scope="col">What stays with your people</th>
            </tr>
          </thead>
          <tbody>
            {EU_ROWS.map((r) => (
              <tr key={r.step} data-testid="eu-row">
                <td className="ws-wrap">{r.step}</td>
                <td className="ws-wrap">{r.eu}</td>
                <td className="ws-wrap">{r.human}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="ms2-muted mt-3" data-testid="eu-source">
        Article numbers refer to{' '}
        <a className="ms2-a" href={MDR_URL} target="_blank" rel="noreferrer">
          Regulation (EU) 2017/745 on EUR-Lex
        </a>
        . No EU MDR data coverage is claimed.
      </p>
    </div>
  )
}
