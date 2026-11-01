// Home (v2): the three most important real FDA alerts, a separate card for the simulated devices, the AI sweep and
// the trust numbers. Every number is read from the stored exports.
import { flaggedRows } from '../artifacts'
import { isoDay } from '../data'
import { Icon } from '../icons'
import type { WorkspaceData } from '../types'
import { sweepDate } from '../components/SweepCard'
import { InvestigateCard } from '../investigate/entry'
import { AlertRows, demoRows, realRows, SourceCaption } from './AlertRows'
import { devicesToReview } from './realAlerts'

export const HOME_TOP = 3

export function HomeV2({
  data,
  onAlert,
  onViewAll,
  onDevices,
  onAudit,
  onInvestigate,
}: {
  data: WorkspaceData
  onAlert: (id: string, code: string) => void
  /** Signals · All alerts. */
  onViewAll: () => void
  /** Our devices (simulated) · Does this apply to us? */
  onDevices: () => void
  /** Evidence · Audit verified. */
  onAudit: () => void
  /** Investigate a complaint (the one main button of its card). */
  onInvestigate?: () => void
}) {
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
      <div className="ms2-grid">
        {onInvestigate && <InvestigateCard onOpen={onInvestigate} />}
        <section className="ms2-card ms2-span2" aria-labelledby="home-alerts-h" data-testid="home-alerts">
          <h2 id="home-alerts-h" className="ms2-h2">
            Real FDA alerts
          </h2>
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
            AI device sweep
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
          <p className="ms2-muted m-0 mt-2 text-[15px]">Every sentence is checked against stored source records before it is shown.</p>
          <button type="button" className="ms2-quietlink mt-1" onClick={onAudit}>
            Audit trail →
          </button>
        </section>
      </div>
    </div>
  )
}
