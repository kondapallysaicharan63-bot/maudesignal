// Home (v2): the three most important real FDA alerts, a separate card for the simulated devices, the AI sweep and
// the trust numbers. Every number is read from the stored exports.
import { VALIDATION_NOTE } from '../roadmap'
import { flaggedRows } from '../artifacts'
import { isoDay } from '../data'
import { Icon } from '../icons'
import { HEADLINE, PITCH, REACTIVE } from '../positioning'
import { flaggedFromData } from '../pms/BoardPage'
import { MascotOwl, useNoctuaHidden } from '../components/mascot/MascotOwl'
import type { WorkspaceData } from '../types'
import { sweepDate } from '../components/SweepCard'
import { InvestigateCard } from '../investigate/entry'
import { AlertRows, demoRows, realRows, SourceCaption } from './AlertRows'
import { devicesToReview, realAlertItems } from './realAlerts'
import './positioning.css'

export const HOME_TOP = 3

export function HomeV2({
  data,
  onAlert,
  onViewAll,
  onDevices,
  onAudit,
  onPms,
  onRoi,
  onInvestigate,
  onBoard,
  onValidation,
}: {
  /** PMS board (PRD-19). */
  onBoard?: () => void
  /** Validation and evidence lifecycle (PRD-18). */
  onValidation?: () => void
  data: WorkspaceData
  onAlert: (id: string, code: string) => void
  /** Signals · All alerts. */
  onViewAll: () => void
  /** Our devices (simulated) · Does this apply to us? */
  onDevices: () => void
  /** Evidence · Audit verified. */
  onAudit: () => void
  /** How MaudeSignal fits your PMS workflow (F26). */
  onPms?: () => void
  /** Time and cost: measured, not claimed (F27). */
  onRoi?: () => void
  /** Investigate a complaint (the one main button of its card). */
  onInvestigate?: () => void
}) {
  const hiddenOwl = useNoctuaHidden()
  // Decorative and calm only: the top bar owl shows while real alerts exist, so Home never shows a second one.
  const calmOwl = !hiddenOwl && realAlertItems(data).length === 0
  const real = realRows(data)
  const demo = demoRows(data)
  const toReview = devicesToReview(data)
  const yours = data.company.mine === true
  const m = data.sweep.meta
  const flagged = flaggedRows(data.sweep).length
  const h = data.manifest.header
  return (
    <div className="ms2-home">
      <h1 className="sr-only">Home</h1>
      <p className="ms2-home-intro" data-testid="home-headline">
        {HEADLINE}
      </p>
      <p className="ms2-home-pitch m-0" data-testid="home-pitch">
        {PITCH}
      </p>
      <p className="ms2-muted m-0 text-[15px]" data-testid="home-reactive">
        {REACTIVE}{' '}
        {onPms && (
          <button type="button" className="ms2-link" onClick={onPms} data-testid="home-hero-pms">
            See how this maps to your PMS workflow →
          </button>
        )}
      </p>
      <div className="ms2-grid">
        {onInvestigate && <InvestigateCard onOpen={onInvestigate} />}
        {onBoard && (
          <section className="ms2-card ms2-span2" aria-labelledby="home-board-h" data-testid="home-board">
            <h2 id="home-board-h" className="ms2-h2">
              {calmOwl && <MascotOwl size={64} className="ms-noctua-inline" />} PMS board
            </h2>
            <p className="ms2-muted m-0 mt-1 text-[15px]">
              Each flagged code with why it was flagged, its status (New, Under review, Note to file, Escalated, Closed), owner and advisory MDR due
              date. Only a named person changes a status; every change is in the audit trail. This is not a QMS.
            </p>
            <button type="button" className="ms-btn mt-2" style={{ minHeight: 44 }} onClick={onBoard} data-testid="home-board-open">
              Open the PMS board · <span className="ms-num" data-testid="home-board-count">{flaggedFromData(data).length}</span> flagged codes
            </button>
          </section>
        )}
        <section className="ms2-card ms2-span2" aria-labelledby="home-alerts-h" data-testid="home-alerts">
          <h2 id="home-alerts-h" className="ms2-h2">
            Weekly sweep — only when a code flags
          </h2>
          <p className="ms2-muted m-0 text-[15px]" data-testid="home-sweep-rule">
            No flag = no action. Real FDA alerts from the latest AI device sweep and the stored brief.
          </p>
          <SourceCaption text={real.source} testid="home-alerts-source" />
          <div className="mt-1">
            <AlertRows rows={real.rows.slice(0, HOME_TOP)} onOpen={onAlert} label="Top real FDA alerts" />
          </div>
          {real.rows.length > 0 && (
            <button type="button" className="ms2-link mt-2" onClick={onViewAll} data-testid="home-view-all">
              View all&nbsp;<span className="ms-num">{real.rows.length}</span>&nbsp;→
            </button>
          )}
        </section>

        {(onPms || onRoi) && (
          <section className="ms2-card ms2-span2" aria-label="Where MaudeSignal fits" data-testid="home-fit">
            {onPms && (
              <button type="button" className="ms2-row" onClick={onPms} data-testid="home-pms-link">
                <span>
                  <span className="font-medium">How MaudeSignal fits your PMS workflow</span> <span className="ms2-tag">New</span>
                </span>
                <Icon name="chevron" size={18} />
              </button>
            )}
            {onRoi && (
              <button type="button" className="ms2-row" onClick={onRoi} data-testid="home-roi-link">
                <span>
                  <span className="font-medium">Time and cost: measured, not claimed</span> <span className="ms2-tag">New</span>
                </span>
                <Icon name="chevron" size={18} />
              </button>
            )}
          </section>
        )}

        {demo.rows.length > 0 && (
          <section className="ms2-sim ms2-span2" aria-labelledby="home-demo-h" data-testid="home-demo">
            <h2 id="home-demo-h" className="ms2-h2">
              Demo snapshot brief
            </h2>
            <p className="ms2-muted m-0 text-[15px]">Real FDA reports from the demo database, not this week's data.</p>
            <SourceCaption text={demo.source} />
            <AlertRows rows={demo.rows} onOpen={onAlert} label="Demo snapshot brief alerts" />
          </section>
        )}

        <section className="ms2-sim ms2-span2" aria-label={yours ? 'Our devices (your company)' : 'Our devices (simulated)'} data-testid="home-devices">
          <button type="button" className="ms2-row !py-1" onClick={onDevices} data-testid="home-devices-link">
            <span>
              <span className="font-medium">{yours ? 'Our devices (your company)' : 'Our devices (simulated)'}</span>
              <span className="ms2-muted"> · </span>
              <span className="ms-num">{toReview}</span> to review
              <span className="ms2-muted block text-[15px]">{yours ? 'Devices you entered in this browser.' : 'Fictional devices, kept apart from the real alerts.'}</span>
            </span>
            <Icon name="chevron" size={18} />
          </button>
        </section>

        <section className="ms2-card" aria-labelledby="home-sweep-h" data-testid="home-sweep">
          <h2 id="home-sweep-h" className="ms2-h2">
            Weekly sweep (proactive extra)
          </h2>
          <p className="m-0 mt-2 text-[20px]">
            <strong className="ms-num">{flagged}</strong> flagged of <strong className="ms-num">{m.codes_on_list}</strong> product codes
          </p>
          <p className="ms2-muted m-0 mt-1" data-testid="home-sweep-label">
            <span className="ms2-tag">Stored</span> <span className="ms2-nowrap">Checked {sweepDate(data.sweep)}</span>{' '}
            <span className="ms2-nowrap">
              · week {isoDay(m.window.current_start)} to {isoDay(m.window.current_end)}
            </span>
          </p>
          <p className="m-0 mt-2 text-[15px]">
            <a className="ms2-a" href={m.source} target="_blank" rel="noreferrer">
              FDA's AI-enabled device list
            </a>
          </p>
        </section>

        <section className="ms2-card" aria-labelledby="home-trust-h" data-testid="home-trust">
          <h2 id="home-trust-h" className="ms2-h2">
            Trust
          </h2>
          <p className="ms2-muted m-0 text-[15px]" data-testid="trust-label">
            <span className="ms2-tag">Stored</span> <span className="ms2-nowrap">{data.manifest.generated_utc.slice(0, 10)}</span>
          </p>
          <dl className="ms2-stats mt-2">
            <div>
              <dt>Claims verified</dt>
              <dd className="ms-num" data-testid="trust-claims">
                {h.claims_verified}
              </dd>
            </div>
            <div>
              <dt>Withheld</dt>
              <dd className="ms-num" data-testid="trust-withheld">
                {h.sentences_withheld}
              </dd>
            </div>
            <div>
              <dt>Audit</dt>
              <dd data-testid="trust-audit">
                {h.audit_chain_ok ? (
                  <span className="ms2-ok">
                    <Icon name="check" size={16} /> Verified
                  </span>
                ) : (
                  <span className="ms2-bad">Not verified</span>
                )}
              </dd>
            </div>
          </dl>
          <p className="ms2-muted m-0 mt-2 text-[15px]" data-testid="trust-validation">{VALIDATION_NOTE}</p>
          {onValidation && (
            <button type="button" className="ms2-quietlink mt-1" onClick={onValidation} data-testid="trust-validation-link">
              What is and is not validated →
            </button>
          )}
          <p className="ms2-muted m-0 mt-2 text-[15px]">Every sentence is checked against stored source records before it is shown.</p>
          <button type="button" className="ms2-quietlink mt-1" onClick={onAudit}>
            Audit trail →
          </button>
        </section>
      </div>
    </div>
  )
}
