// The four sections of the v2 layout, each with subtabs (ARIA tabs, one open at a time). This is a reorganisation of
// the existing views: every panel reuses an existing component or reads numbers straight from the stored exports.
import { useEffect, useState } from 'react'
import { auditRunFor, capaDrafts } from '../artifacts'
import { useAlertPanel } from '../alertPanelContext'
import { configSnippets, EXAMPLE_QUESTIONS, fetchConnect, FALLBACK_INFO, type ConnectInfo } from '../connect'
import { AlertRows, demoRows, realRows, SourceCaption } from './AlertRows'
import { demoSnapshotLabel, WORKFLOWS } from '../data'
import { Icon } from '../icons'
import { useMine } from '../useMyCompany'
import type { WorkflowId, WorkspaceData } from '../types'
import { StoredList } from '../components/ChatPane'
import { ConnectView, CopyButton } from '../components/ConnectView'
import { MakeItYours, MineBar } from '../components/MakeItYours'
import { CompanyBanner, OurDevices } from '../components/OurDevices'
import { SweepCard, SweepRules } from '../components/SweepCard'
import { AuditTab, CapaTab } from '../components/artifacts/AuditCapaProtocol'
import { BriefTab } from '../components/artifacts/BriefTabs'
import { DossierTab } from '../components/artifacts/DossierVision'
import { rankReal, realDetails, sourceLine, sweepDetails } from './realAlerts'
import { labelForWeek, sweepLabel } from '../sweepLabel'
import type { ConnectTab, DevicesTab, EvidenceTab, SignalsTab } from './router'
import { SubTabs, type TabDef, type TabHow } from './SubTabs'

export const SIGNALS_TAB_LABELS: TabDef<SignalsTab>[] = [
  { id: 'ranked', label: 'Ranked' },
  { id: 'trend', label: 'Trend' },
  { id: 'unfiled', label: "Reports you didn't file" },
  { id: 'alerts', label: 'All alerts' },
]
export const DEVICES_TAB_LABELS: TabDef<DevicesTab>[] = [
  { id: 'apply', label: 'Does this apply to us?' },
  { id: 'yours', label: 'Make it yours' },
]
export const EVIDENCE_TAB_LABELS: TabDef<EvidenceTab>[] = [
  { id: 'capa', label: 'CAPA-need evidence' },
  { id: 'review', label: 'Muse Wonder review' },
  { id: 'approve', label: 'Approve' },
  { id: 'audit', label: 'Audit verified' },
]
export const CONNECT_TAB_LABELS: TabDef<ConnectTab>[] = [
  { id: 'muse', label: 'Muse connector' },
  { id: 'claude', label: 'Claude connector' },
  { id: 'api', label: 'API docs' },
]

function PageHead({ title, lead }: { title: string; lead?: string }) {
  return (
    <header className="ms2-pagehead">
      <h1 className="ms2-h1">{title}</h1>
      {lead && <p className="ms2-lead">{lead}</p>}
    </header>
  )
}

function Related({ ids, onWorkflow, title = 'More ways in' }: { ids: WorkflowId[]; onWorkflow: (id: WorkflowId) => void; title?: string }) {
  const defs = ids.map((id) => WORKFLOWS.find((w) => w.id === id)).filter((w): w is (typeof WORKFLOWS)[number] => !!w)
  return (
    <section className="ms2-card mt-6" aria-label={title}>
      <h2 className="ms2-h2">{title}</h2>
      <ul className="m-0 mt-2 list-none p-0">
        {defs.map((w) => (
          <li key={w.id}>
            <button type="button" className="ms2-row" onClick={() => onWorkflow(w.id)}>
              <span className="min-w-0">
                <span className="block font-medium">{w.title}</span>
                <span className="ms2-muted block">{w.blurb}</span>
              </span>
              <Icon name="chevron" size={18} />
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** Ranked: the real alerts, most important first, each row opening its detail panel. */
function Ranked({ data }: { data: WorkspaceData }) {
  const { openAlert } = useAlertPanel()
  const real = realRows(data)
  return (
    <>
      <SourceCaption text={real.source} testid="ranked-source" />
      <AlertRows rows={real.rows} onOpen={openAlert} ranked label="Real FDA alerts, ranked" testid="ranked-list" />
    </>
  )
}

/** Trend: the latest sweep's openFDA week against the weekly average of the 4 weeks before (stored numbers only). */
function Trend({ data }: { data: WorkspaceData }) {
  const sw = sweepDetails(data)
  const label = sw.length > 0 && sw.every((d) => labelForWeek(data.sweep, d.window?.this_week)) ? sweepLabel(data.sweep) : null
  const rows = rankReal(realDetails(data)).filter((d) => d.window && d.window.this_week.count != null)
  if (rows.length === 0) return <p className="ms2-muted">No weekly counts are stored.</p>
  const max = Math.max(...rows.map((d) => Math.max(d.window!.this_week.count ?? 0, d.window!.baseline_4wk.weekly_mean ?? 0)), 1)
  const pct = (v: number) => `${Math.max(1.5, (v / max) * 100)}%`
  return (
    <div>
      <p className="ms2-muted m-0">
        {label ? `${label}. ` : ''}Reports in that week against the weekly average of the 4 weeks before. Stored numbers, each
        with its openFDA query.
      </p>
      <ul className="m-0 mt-4 list-none space-y-5 p-0" data-testid="trend-list">
        {rows.map((d) => {
          const w = d.window!
          const now = w.this_week.count ?? 0
          const mean = w.baseline_4wk.weekly_mean
          const times = d.numbers.find((n) => /times/i.test(n.label))
          const q = d.numbers[0]?.openfda_url
          return (
            <li key={d.id} data-testid="trend-row" data-code={d.product_code}>
              <p className="m-0 flex flex-wrap items-baseline gap-x-2">
                <span className="ms-code">{d.product_code}</span>
                {d.device_type && <span className="ws-wrap font-medium">{d.device_type}</span>}
                <span className="ms2-tag" data-testid="trend-label">
                  Stored
                </span>
              </p>
              <div className="ms2-bars mt-2" aria-hidden="true">
                <span className="ms2-bar ms2-bar--now" style={{ width: pct(now) }} />
                {mean != null && <span className="ms2-bar ms2-bar--base" style={{ width: pct(mean) }} />}
              </div>
              <p className="m-0 mt-1 ms-num" data-testid="trend-numbers">
                <strong>{now}</strong> {d.source.kind === 'brief' ? 'that week' : 'in the latest sweep'}
                {mean != null && (
                  <>
                    {' '}
                    vs <strong>{mean}</strong> a week before
                  </>
                )}
                {times && <span className="ms2-muted"> · {times.value}× (stored)</span>}
              </p>
              <p className="ms2-muted m-0 text-[15px]">
                {sourceLine(d)} · week {w.this_week.from} to {w.this_week.to}
                {q && (
                  <>
                    {' · '}
                    <a className="ms2-a" href={q} target="_blank" rel="noreferrer">
                      openFDA query
                    </a>
                  </>
                )}
              </p>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/** Reports filed by someone other than the manufacturer (user facilities, others), from the stored "who filed" counts. */
export const UNFILED_THREAD = '21-not-by-manufacturer'

function Unfiled({ data, onThread }: { data: WorkspaceData; onThread: (id: string) => void }) {
  const { openAlert } = useAlertPanel()
  const rows = rankReal(realDetails(data)).filter((d) => d.who_filed)
  const recorded = data.threads.threads.find((t) => t.id === UNFILED_THREAD)
  const link = recorded && (
    <button type="button" className="ms2-row mt-4" onClick={() => onThread(recorded.id)} data-testid="unfiled-thread">
      <span className="min-w-0">
        <span className="ms2-tag">Recorded</span> <span className="ws-wrap">{recorded.question}</span>
      </span>
      <Icon name="chevron" size={18} />
    </button>
  )
  if (rows.length === 0)
    return (
      <div>
        <p className="ms2-muted">No "who filed" counts are stored.</p>
        {link}
      </div>
    )
  return (
    <div>
      <p className="ms2-muted m-0">
        Reports about these device types that a user facility or someone else filed, not the manufacturer. Counts are of the stored
        reports for the alert's week.
      </p>
      <div className="relative mt-4 overflow-x-auto">
        <table className="ms2-table" data-testid="unfiled-table">
          <caption className="sr-only">Who filed the stored reports, per real alert</caption>
          <thead>
            <tr>
              <th scope="col">Code</th>
              <th scope="col" className="ms2-num">
                Stored
              </th>
              <th scope="col" className="ms2-num">
                Manufacturer
              </th>
              <th scope="col" className="ms2-num">
                User facility
              </th>
              <th scope="col" className="ms2-num">
                Other
              </th>
              <th scope="col">
                <span className="sr-only">Details</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <tr key={d.id}>
                <th scope="row">
                  <span className="ms-code">{d.product_code}</span>
                  <span className="ms2-muted block text-[14px] font-normal">{d.source.kind === 'brief' ? 'demo snapshot' : 'AI sweep'}</span>
                </th>
                <td className="ms2-num">{d.reports_stored ?? '—'}</td>
                <td className="ms2-num">{d.who_filed!.manufacturer}</td>
                <td className="ms2-num">
                  <strong>{d.who_filed!.user_facility}</strong>
                </td>
                <td className="ms2-num">
                  <strong>{d.who_filed!.other}</strong>
                </td>
                <td>
                  <button type="button" className="ms2-link" onClick={() => openAlert(d.id, d.product_code)} aria-label={`Details for ${d.product_code}`}>
                    Details
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {link}
    </div>
  )
}

/** All alerts: every real alert, the full AI device sweep, then the daily briefs (demo snapshot). */
function AllAlerts({ data, briefDate, onBriefDate }: { data: WorkspaceData; briefDate: string | null; onBriefDate: (d: string) => void }) {
  const { openAlert } = useAlertPanel()
  const real = realRows(data)
  const demo = demoRows(data)
  return (
    <div className="space-y-6">
      <section aria-label="Real FDA alerts" data-testid="all-alerts">
        <h2 className="ms2-h2">
          Real FDA alerts · <span className="ms-num">{real.rows.length}</span>
        </h2>
        <SourceCaption text={real.source} />
        <AlertRows rows={real.rows} onOpen={openAlert} label="Real FDA alerts" />
      </section>
      {demo.rows.length > 0 && (
        <section aria-label="Demo snapshot brief" className="ms2-sim" data-testid="demo-alerts">
          <h2 className="ms2-h2">Demo snapshot brief</h2>
          <p className="ms2-muted m-0 text-[15px]">Real FDA reports from the demo database, not this week's data.</p>
          <SourceCaption text={demo.source} />
          <AlertRows rows={demo.rows} onOpen={openAlert} label="Demo snapshot brief alerts" />
        </section>
      )}
      <section aria-label="AI device sweep">
        <SweepCard sweep={data.sweep} />
      </section>
      <section aria-label="Daily briefs" className="ms2-card">
        <BriefTab briefs={data.briefs} date={briefDate} onDate={onBriefDate} snapshot={demoSnapshotLabel(data.sources)} />
      </section>
    </div>
  )
}

export function SignalsPage({
  data,
  tab,
  onTab,
  onWorkflow,
  onThread,
  briefDate,
  onBriefDate,
}: {
  data: WorkspaceData
  tab: SignalsTab
  onTab: (t: SignalsTab, how?: TabHow) => void
  onWorkflow: (id: WorkflowId) => void
  onThread: (id: string) => void
  briefDate: string | null
  onBriefDate: (d: string) => void
}) {
  return (
    <div>
      <PageHead title="Signals" lead="Real FDA data only, for a person to review." />
      <SubTabs id="signals" label="Signals" tabs={SIGNALS_TAB_LABELS} value={tab} onChange={onTab}>
        {tab === 'ranked' && (
          <>
            <Ranked data={data} />
            <SweepRules sweep={data.sweep} collapsed />
            <Related ids={['check-device', 'weekly-signals', 'weekly-investigator', 'recall-sweep', 'ask-copilot']} onWorkflow={onWorkflow} />
          </>
        )}
        {tab === 'trend' && <Trend data={data} />}
        {tab === 'unfiled' && <Unfiled data={data} onThread={onThread} />}
        {tab === 'alerts' && <AllAlerts data={data} briefDate={briefDate} onBriefDate={onBriefDate} />}
      </SubTabs>
    </div>
  )
}

export function DevicesPage({
  data,
  tab,
  onTab,
  device,
  onDevice,
  filter,
  onFilter,
}: {
  data: WorkspaceData
  tab: DevicesTab
  onTab: (t: DevicesTab, how?: TabHow) => void
  device: string | null
  onDevice: (id: string | null) => void
  filter: string | null
  onFilter: (label: string | null) => void
}) {
  const mine = useMine()
  const yours = data.company.mine === true
  return (
    <div>
      <PageHead
        title={yours ? 'Our devices (your company)' : 'Our devices (simulated)'}
        lead={yours ? 'Devices you entered, kept in this browser only.' : 'Fictional devices; the problem evidence is real FDA data.'}
      />
      <SubTabs id="devices" label="Our devices" tabs={DEVICES_TAB_LABELS} value={tab} onChange={onTab}>
        {tab === 'apply' && (
          <div className="ms2-nodup ms2-devices">
          <OurDevices company={data.company} deviceId={device} onDevice={(x) => onDevice(x)} onBack={() => onDevice(null)} filter={filter} onFilter={onFilter} />
          </div>
        )}
        {tab === 'yours' && (
          <div className="space-y-4">
            {mine ? (
              <>
                <MineBar open={mine.mode === 'mine'} onOpen={() => mine.setMode('mine')} />
                <CompanyBanner company={data.company} />
                {mine.mode === 'mine' ? (
                  <MakeItYours onClose={() => onTab('apply')} />
                ) : (
                  <p className="ms2-muted m-0">Press Make it yours to add your own devices. They stay in this browser.</p>
                )}
              </>
            ) : (
              <p className="ms2-muted">Loading…</p>
            )}
          </div>
        )}
      </SubTabs>
    </div>
  )
}

export function EvidencePage({
  data,
  tab,
  onTab,
  onThread,
  onWorkflow,
}: {
  data: WorkspaceData
  tab: EvidenceTab
  onTab: (t: EvidenceTab, how?: TabHow) => void
  onThread: (id: string) => void
  onWorkflow: (id: WorkflowId) => void
}) {
  const def = WORKFLOWS.find((w) => w.id === 'capa-need-evidence') ?? WORKFLOWS[0]
  const capaThread = data.threads.threads.find((t) => t.workflow === 'capa-need-evidence') ?? null
  return (
    <div>
      <PageHead title="Evidence" lead="From the reports to a reviewed, approved and audited decision. Drafts only." />
      <SubTabs id="evidence" label="Evidence" tabs={EVIDENCE_TAB_LABELS} value={tab} onChange={onTab}>
        {tab === 'capa' && (
          <>
            <div className="ms2-nodup">
              <StoredList def={def} data={data} onThread={onThread} />
            </div>
            <Related ids={['vision']} onWorkflow={onWorkflow} title="Label and 510(k) vision" />
          </>
        )}
        {tab === 'review' && (
          <div className="ms2-dossier">
            <DossierTab dossier={data.dossier} v2 />
          </div>
        )}
        {tab === 'approve' && <CapaTab drafts={capaDrafts(data.audit)} evidence={data.evidence} />}
        {tab === 'audit' && (
          <AuditTab audit={data.audit} activeRun={auditRunFor(data.audit, capaThread)?.run_label ?? null} generatedUtc={data.manifest.generated_utc} />
        )}
      </SubTabs>
    </div>
  )
}

function useConnectInfo(apiBase: string | null): ConnectInfo {
  const [info, setInfo] = useState<ConnectInfo>(FALLBACK_INFO)
  useEffect(() => {
    let live = true
    if (apiBase) void fetchConnect(apiBase).then((i) => live && setInfo(i))
    return () => {
      live = false
    }
  }, [apiBase])
  return info
}

function ClaudeConnector({ apiBase }: { apiBase: string | null }) {
  const info = useConnectInfo(apiBase)
  const snippets = configSnippets(info).filter((s) => s.id === 'claude-desktop' || s.id === 'cursor')
  return (
    <div className="space-y-4" data-testid="claude-connector">
      <p className="m-0">
        Add MaudeSignal to Claude Desktop (or Cursor) as an MCP server. It answers from stored public FDA records, read-only.
      </p>
      {snippets.map((sn) => (
        <section key={sn.id} className="ms2-card" aria-label={sn.title}>
          <div className="flex items-center justify-between gap-3">
            <h2 className="ms2-h2">{sn.title}</h2>
            <CopyButton text={sn.text} label={`${sn.title} config`} />
          </div>
          <p className="ms2-muted m-0 mt-1">{sn.where}</p>
          <pre className="ms-code m-0 mt-3 overflow-x-auto whitespace-pre-wrap break-all rounded-md border border-rule p-3 !text-[15px]" tabIndex={0}>
            {sn.text}
          </pre>
        </section>
      ))}
      <p className="ms2-muted m-0">
        MCP address: <span className="ms-code ms2-url">{info.mcp_url}</span>
      </p>
    </div>
  )
}

function ApiDocs({ apiBase }: { apiBase: string | null }) {
  const info = useConnectInfo(apiBase)
  const links: [string, string][] = [
    ['OpenAPI file', info.openapi_url],
    ['MCP address', info.mcp_url],
    ['Privacy', info.privacy_url],
    ['Terms', info.terms_url],
  ]
  return (
    <div className="space-y-4" data-testid="api-docs">
      <p className="m-0">Read-only REST and MCP over stored public FDA records. The key goes in the {info.key_header} header.</p>
      <ul className="m-0 list-none p-0">
        {links.map(([label, url]) => (
          <li key={label}>
            <a className="ms2-row" href={url} target="_blank" rel="noreferrer noopener">
              <span>
                <span className="block font-medium">{label}</span>
                <span className="ms2-muted ms-code ws-wrap block">{url}</span>
              </span>
              <Icon name="chevron" size={18} />
            </a>
          </li>
        ))}
      </ul>
      <section className="ms2-card" aria-label="Ready-made prompts">
        <h2 className="ms2-h2">Ready-made prompts</h2>
        <ul className="m-0 mt-2 list-none space-y-2 p-0">
          {EXAMPLE_QUESTIONS.map((p) => (
            <li key={p.id} className="ws-wrap">
              <code className="ms-code font-semibold">{p.title}</code> <span className="ms2-muted">{p.line}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}

export function ConnectPage({ tab, onTab, apiBase }: { tab: ConnectTab; onTab: (t: ConnectTab, how?: TabHow) => void; apiBase: string | null }) {
  return (
    <div>
      <PageHead title="Connect" lead="Use MaudeSignal from Muse, Claude or your own code." />
      <SubTabs id="connect" label="Connect" tabs={CONNECT_TAB_LABELS} value={tab} onChange={onTab}>
        {tab === 'muse' && (
          <ConnectView apiBase={apiBase} v2 />
        )}
        {tab === 'claude' && <ClaudeConnector apiBase={apiBase} />}
        {tab === 'api' && <ApiDocs apiBase={apiBase} />}
      </SubTabs>
    </div>
  )
}

