// A simulated device's full lifecycle profile (/devices/<id>): seven tabs, one open at a time. Everything is
// SIMULATED sample data from company_profiles.json, except the boxes marked "Real FDA data": the product code, its FDA
// name, class and regulation number (stored openFDA data), and on Post-market the real MAUDE problem patterns already
// stored in company.json for that product code. The two are kept visually apart.
import { useEffect, type ReactNode } from 'react'
import type { Company, CompanyDevice } from '../types'
import {
  DECISION_VERB,
  daysBetween,
  niceDate,
  niceMonth,
  SIM_LABEL,
  summarize,
  type Dated,
  type DeviceProfile as Profile,
  type ProfilesFile,
} from './profiles'
import type { ProfileTab } from './router'
import { SubTabs, type TabDef, type TabHow } from './SubTabs'

export const PROFILE_TAB_LABELS: TabDef<ProfileTab>[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'design', label: 'Design & development' },
  { id: 'vv', label: 'Verification & validation' },
  { id: 'regulatory', label: 'Regulatory' },
  { id: 'market', label: 'Launch & market' },
  { id: 'postmarket', label: 'Post-market' },
  { id: 'people', label: 'People & activity log' },
]

/** The document title of a profile tab; always carries the SIMULATED label. */
export function profileTitle(p: Pick<Profile, 'name'>, tab: ProfileTab): string {
  const t = PROFILE_TAB_LABELS.find((x) => x.id === tab)?.label ?? ''
  return `${p.name} · ${t} · ${SIM_LABEL} · MaudeSignal`
}

/** "20260701" as "2026-07-01". */
const ymd = (s: string): string => (/^\d{8}$/.test(s) ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6)}` : s)

const when = (x: Dated | null | undefined): string => (x ? `${niceDate(x.date)}${x.planned ? ' (planned)' : ''}` : 'not yet')

function SimTag() {
  return (
    <p className="ms2-simtag" data-testid="sim-tab-label">
      {SIM_LABEL}
    </p>
  )
}

function Card({ title, children, testid, real = false }: { title: string; children: ReactNode; testid?: string; real?: boolean }) {
  return (
    <section className={['ms2-card', real ? 'ms2-realbox' : ''].join(' ')} aria-label={title} data-testid={testid}>
      <h2 className="ms2-h2">{title}</h2>
      <div className="mt-2">{children}</div>
    </section>
  )
}

function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="ms2-facts">
      {rows.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  )
}

function ResultChip({ r }: { r: 'pass' | 'fail' | 'planned' }) {
  const cls = r === 'pass' ? 'ms-chip ms-chip--ok' : r === 'fail' ? 'ms-chip ms-chip--high' : 'ms-chip'
  return (
    <span className={cls} data-testid="result-chip" data-result={r}>
      {r === 'pass' ? 'Pass' : r === 'fail' ? 'Fail' : 'Planned'}
    </span>
  )
}

/** The milestones on one line, placed by date (inline SVG, design tokens only), with the dated list below it. */
export function Timeline({ p }: { p: Profile }) {
  const ms = p.milestones
  if (ms.length === 0) return null
  const t0 = Date.parse(ms[0].date)
  const t1 = Date.parse(ms[ms.length - 1].date)
  const span = Math.max(1, t1 - t0)
  const W = 1000
  const x = (d: string) => 20 + ((Date.parse(d) - t0) / span) * (W - 40)
  return (
    <div data-testid="timeline">
      <svg viewBox={`0 0 ${W} 40`} className="ms2-timeline" role="img" aria-label={`Timeline from ${niceDate(ms[0].date)} to ${niceDate(ms[ms.length - 1].date)}`}>
        <line x1={20} y1={20} x2={W - 20} y2={20} stroke="var(--rule-strong)" strokeWidth={2} />
        {ms.map((m) => (
          <circle
            key={m.key}
            cx={x(m.date)}
            cy={20}
            r={7}
            fill={m.planned ? 'var(--surface)' : 'var(--accent)'}
            stroke={m.planned ? 'var(--ink-3)' : 'var(--accent)'}
            strokeWidth={2}
            strokeDasharray={m.planned ? '3 2' : undefined}
          />
        ))}
      </svg>
      <ol className="ms2-tl" aria-label="Key dates">
        {ms.map((m) => (
          <li key={m.key} data-planned={m.planned || undefined} data-testid="milestone" data-key={m.key} data-date={m.date}>
            <span className="ms-num ms2-tl-date">{niceDate(m.date)}</span>
            <span>
              {m.label}
              {m.planned && <span className="ms2-tag ml-2">planned</span>}
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}

function Overview({ p }: { p: Profile }) {
  const o = p.overview
  return (
    <div className="space-y-4">
      <Card title="Real FDA data (stored)" testid="real-classification" real>
        <Facts
          rows={[
            ['Product code', <span className="ms-code !text-[15px] !text-ink">{p.product_code}</span>],
            ['FDA device name', o.fda_device_name ?? 'FDA name not in stored data'],
            ['Device class', o.device_class ? `Class ${o.device_class}` : 'Not in stored data'],
            ['Regulation number', o.regulation_number ? `21 CFR ${o.regulation_number}` : 'Not in stored data'],
          ]}
        />
        <p className="ms2-muted m-0 mt-2 text-[14px]" data-testid="real-source">
          Source: {o.classification_source}
          {o.classification_fetched ? `, fetched ${niceDate(o.classification_fetched)}` : ''}. Name: {o.fda_name_source}.
        </p>
      </Card>
      <Card title="This device (simulated)" testid="sim-overview">
        <Facts
          rows={[
            ['Name and model', `${p.name} ${p.model}`],
            ['Owner', p.owner],
            ['Regulatory pathway', o.pathway],
            ['Status', <span data-testid="profile-status">{o.status_label}</span>],
            ['Software', o.ai ? 'Yes, with a machine-learning function' : o.software ? 'Yes' : 'No'],
            ['Intended use', o.intended_use],
          ]}
        />
      </Card>
      <Card title="Key dates (simulated)">
        <Timeline p={p} />
      </Card>
    </div>
  )
}

function Design({ p }: { p: Profile }) {
  const g = p.design
  return (
    <div className="space-y-4">
      <div className="ms2-grid">
        <Card title="Design inputs">
          <ul className="ms2-list">
            {g.inputs.map((x) => (
              <li key={x.id}>
                <span className="ms-code">{x.id}</span> {x.text}
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Design outputs">
          <ul className="ms2-list">
            {g.outputs.map((x) => (
              <li key={x.id}>
                <span className="ms-code">{x.id}</span> {x.text}
              </li>
            ))}
          </ul>
        </Card>
      </div>
      <Card title="Risk management (ISO 14971): top hazards" testid="hazards">
        <ul className="ms2-list">
          {g.hazards.map((h) => (
            <li key={h.id}>
              <p className="m-0 font-semibold">
                <span className="ms-code">{h.id}</span> {h.hazard}
              </p>
              <p className="ms2-muted m-0 text-[15px]">
                Harm: {h.harm} · Severity: {h.severity} · Residual risk: {h.residual}
              </p>
              <p className="m-0 text-[15px]">Risk control: {h.control}</p>
            </li>
          ))}
        </ul>
      </Card>
      {g.software && (
        <Card title="Software" testid="software-class">
          <Facts
            rows={[
              ['IEC 62304 software safety class', `Class ${g.software.iec62304_class}`],
              ['FDA software documentation level (formerly level of concern)', g.software.documentation_level],
            ]}
          />
        </Card>
      )}
      <Card title="Design reviews">
        <ul className="ms2-list">
          {g.reviews.map((r) => (
            <li key={r.id}>
              <p className="m-0 font-semibold">
                {r.name} · <span className="ms-num">{when(r)}</span>
              </p>
              <p className="ms2-muted m-0 text-[15px]">Attendees: {r.attendees.map((a) => `${a.name}, ${a.role}`).join('; ')}</p>
              <p className="m-0 text-[15px]">Outcome: {r.outcome}</p>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  )
}

function VV({ p }: { p: Profile }) {
  const v = p.vv
  return (
    <div className="space-y-4">
      <Card title="Test protocols" testid="protocols">
        <ul className="ms2-list">
          {v.protocols.map((t) => (
            <li key={t.id} data-testid="protocol" data-result={t.result}>
              <p className="m-0 flex flex-wrap items-center gap-2">
                <span className="ms-code">{t.id}</span>
                <span className="font-semibold">{t.title}</span>
                <ResultChip r={t.result} />
              </p>
              <p className="ms2-muted m-0 text-[15px]">
                {t.standard ? `${t.standard} · ` : ''}
                {when(t)} · report {t.report}
              </p>
            </li>
          ))}
        </ul>
      </Card>
      {v.problems.length > 0 ? (
        <Card title="Problems found and what changed" testid="problems">
          <ul className="ms2-list">
            {v.problems.map((x) => (
              <li key={x.id}>
                <p className="m-0 font-semibold">
                  <span className="ms-code">{x.id}</span> Found in {x.found_in} on {niceDate(x.date)}
                </p>
                <p className="m-0">{x.description}</p>
                <p className="m-0">What changed: {x.change}</p>
                <p className="m-0">
                  Retest {x.retest_id} on {niceDate(x.retest_date)}: <ResultChip r={x.retest_result} />
                </p>
              </li>
            ))}
          </ul>
        </Card>
      ) : (
        <p className="ms2-muted m-0">No test failed for this device.</p>
      )}
      {v.study && (
        <Card title="Standalone performance study (simulated)" testid="study">
          <Facts
            rows={[
              ['Test set', v.study.test_set],
              ['Reference standard', v.study.reference],
              ['Sensitivity', `${(v.study.sensitivity * 100).toFixed(1)}% (${v.study.true_positives} of ${v.study.positives})`],
              ['Specificity', `${(v.study.specificity * 100).toFixed(1)}% (${v.study.true_negatives} of ${v.study.negatives})`],
              ['Report signed', when(v.study)],
            ]}
          />
          <p className="ms2-muted m-0 mt-2 text-[14px]">{v.study.label}. These are not results of any real device.</p>
        </Card>
      )}
    </div>
  )
}

function Regulatory({ p }: { p: Profile }) {
  const r = p.regulatory
  const verb = DECISION_VERB[r.pathway]
  return (
    <div className="space-y-4">
      <Card title="Pre-Submission (Q-Sub)">
        <Facts rows={[['Number', r.presub.number], ['Meeting', when(r.presub)]]} />
        {r.presub.feedback.length > 0 && (
          <>
            <h3 className="ms2-h3 mt-3">FDA feedback summary</h3>
            <ul className="ms2-list">
              {r.presub.feedback.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          </>
        )}
      </Card>
      <Card title={`${r.pathway} submission`} testid="submission">
        <Facts
          rows={[
            ['Submission number', <span className="ms-code !text-[15px] !text-ink" data-testid="submission-number">{r.submission.number}</span>],
            ['Submitted', when(r.submission)],
            ['FDA Additional Information request', r.ai_request ? `${when(r.ai_request)}. ${r.ai_request.summary}` : 'none'],
            ['Response to the request', r.ai_response ? `${when(r.ai_response)}. ${r.ai_response.summary}` : 'none'],
            ['FDA decision', <span data-testid="decision">{r.decision ? `${verb} on ${when(r.decision)}` : 'pending'}</span>],
            ...(r.fda_days !== null && r.hold_days !== null
              ? ([['Review time', `${r.fda_days} FDA days + ${r.hold_days} days on hold (waiting on the response)`]] as [string, ReactNode][])
              : []),
            ...(r.predicate ? ([['Predicate', r.predicate]] as [string, ReactNode][]) : []),
          ]}
        />
        <p className="ms2-muted m-0 mt-2 text-[14px]">Numbers in this format (K-SIM-, DEN-SIM-, P-SIM-, Q-SIM-) are fictional and are not FDA numbers.</p>
      </Card>
    </div>
  )
}

function Market({ p }: { p: Profile }) {
  const m = p.market
  return (
    <div className="space-y-4">
      <Card title="Launch and market" testid="market">
        <Facts
          rows={[
            ['Launch', m.launch ? when(m.launch) : 'not launched'],
            ['Regions', m.regions.length ? m.regions.join(', ') : 'none yet'],
            ['Sites', m.sites !== null ? <span className="ms-num">{m.sites.toLocaleString('en-US')}</span> : 'none yet'],
            ['Units shipped', m.units_shipped !== null ? <span className="ms-num">{m.units_shipped.toLocaleString('en-US')}</span> : 'none yet'],
            ['UDI-DI', <span className="ms-code !text-[15px] !text-ink" data-testid="udi">{m.udi_di}</span>],
          ]}
        />
        <p className="ms2-muted m-0 mt-2 text-[14px]">The UDI-DI is a fictional placeholder, not a GS1 number.</p>
      </Card>
    </div>
  )
}

/** Monthly complaints as small bars (inline SVG, tokens only). */
export function ComplaintsChart({ rows }: { rows: { month: string; count: number }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.count))
  const W = 600
  const H = 120
  const bw = W / rows.length
  const total = rows.reduce((s, r) => s + r.count, 0)
  return (
    <figure className="m-0" data-testid="complaints-chart">
      <svg viewBox={`0 0 ${W} ${H + 20}`} className="ms2-chart" role="img" aria-label={`Complaints per month, ${niceMonth(rows[0].month)} to ${niceMonth(rows[rows.length - 1].month)}: ${total} in all`}>
        <line x1={0} y1={H} x2={W} y2={H} stroke="var(--rule-strong)" strokeWidth={1} />
        {rows.map((r, i) => {
          const h = (r.count / max) * (H - 16)
          return (
            <g key={r.month}>
              <rect x={i * bw + bw * 0.2} y={H - h} width={bw * 0.6} height={h} fill="var(--accent)" rx={2} />
              <text x={i * bw + bw / 2} y={H - h - 4} textAnchor="middle" fontSize={13} fill="var(--ink-2)">
                {r.count}
              </text>
              {(i === 0 || i === rows.length - 1 || i % 3 === 0) && (
                <text x={i * bw + bw / 2} y={H + 16} textAnchor="middle" fontSize={12} fill="var(--ink-3)">
                  {niceMonth(r.month).slice(0, 3)}
                </text>
              )}
            </g>
          )
        })}
      </svg>
      <figcaption className="ms2-muted text-[14px]">
        {total} complaints, {niceMonth(rows[0].month)} to {niceMonth(rows[rows.length - 1].month)} (simulated).
      </figcaption>
    </figure>
  )
}

function RealPatterns({ d, company }: { d: CompanyDevice | undefined; company: Company }) {
  if (!d) return null
  const ev = d.evidence
  const w = ev.window
  return (
    <section className="ms2-card ms2-realbox" aria-label="Real FDA data" data-testid="real-patterns">
      <p className="ms2-realtag">Real FDA data · MAUDE · product code {d.product_code}</p>
      <h2 className="ms2-h2 mt-1">Problem patterns already stored for {d.product_code}</h2>
      <p className="ms2-muted m-0 mt-1 text-[15px]">
        These are reports on all devices with this product code, not on this simulated device.
        {w?.date_from && w.date_to ? ` Reports received ${niceDate(ymd(w.date_from))} to ${niceDate(ymd(w.date_to))}.` : ''}{' '}
        Stored {niceDate(company.generated_utc)}.
      </p>
      {d.patterns.length === 0 ? (
        <p className="m-0 mt-2" data-testid="no-real-patterns">
          No problem patterns are stored for this product code.
        </p>
      ) : (
        <ul className="ms2-list mt-2">
          {d.patterns.map((pt) => (
            <li key={pt.id} data-testid="real-pattern">
              <span className="font-semibold">{pt.display_label.replace(/^Keyword match \(unreviewed\):\s*/i, '')}</span>{' '}
              <span className="ms-num">· {pt.count} reports</span>
              {pt.kind === 'keyword' && <span className="ms2-tag ml-2">keyword match, unreviewed</span>}
              {pt.links[0] && (
                <>
                  {' '}
                  ·{' '}
                  <a className="ms2-a" href={pt.links[0].url} target="_blank" rel="noreferrer">
                    {pt.links[0].label}
                  </a>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {ev.queries.length > 0 && (
        <p className="ms2-muted m-0 mt-2 text-[14px]">
          Source:{' '}
          {ev.queries.map((q, i) => (
            <span key={q.url}>
              {i > 0 && ' · '}
              <a className="ms2-a" href={q.url} target="_blank" rel="noreferrer">
                {q.label}
              </a>
            </span>
          ))}
        </p>
      )}
    </section>
  )
}

function PostMarket({ p, d, company, onEvidence }: { p: Profile; d: CompanyDevice | undefined; company: Company; onEvidence: () => void }) {
  const pm = p.postmarket
  return (
    <div className="space-y-4">
      <div className="space-y-4" data-testid="sim-postmarket">
        {pm.complaints_by_month.length > 0 ? (
          <Card title="Complaints over time (simulated)">
            <ComplaintsChart rows={pm.complaints_by_month} />
            <h3 className="ms2-h3 mt-3">Complaint categories</h3>
            <ul className="ms2-list">
              {pm.categories.map((c) => (
                <li key={c.name}>
                  {c.name} <span className="ms-num">· {c.count}</span>
                </li>
              ))}
            </ul>
          </Card>
        ) : (
          <Card title="Complaints (simulated)">
            <p className="m-0">Not on the market yet, so there are no complaints.</p>
          </Card>
        )}
        <Card title="CAPAs (simulated)" testid="capas">
          {pm.capas.length === 0 ? (
            <p className="m-0">No CAPA has been opened for this device.</p>
          ) : (
            <ul className="ms2-list">
              {pm.capas.map((c) => (
                <li key={c.id} data-testid="capa" data-state={c.state}>
                  <p className="m-0 flex flex-wrap items-center gap-2">
                    <span className="ms-code">{c.id}</span> <span className="font-semibold">{c.title}</span>
                    <span className={c.state === 'open' ? 'ms-chip' : 'ms-chip ms-chip--ok'}>{c.state === 'open' ? 'Open' : 'Closed'}</span>
                  </p>
                  <p className="ms2-muted m-0 text-[15px]">
                    Owner {c.owner} · opened {niceDate(c.opened)}
                    {c.closed ? ` · closed ${niceDate(c.closed)} (${daysBetween(c.opened, c.closed)} days)` : ''}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="“Does this apply to us?” decision history (simulated)" testid="decision-history">
          {!d || d.history.length === 0 ? (
            <p className="m-0">No decision is recorded.</p>
          ) : (
            <ol className="ms2-list">
              {[...d.history].reverse().map((h) => (
                <li key={h.seq}>
                  <span className="ms-num">{niceDate(h.date)}</span> · {h.actor} · {h.from_status ? `${h.from_status} → ` : ''}
                  <span className="font-semibold">{h.to_status}</span>
                </li>
              ))}
            </ol>
          )}
          <button type="button" className="ms2-link mt-2" onClick={onEvidence} data-testid="open-evidence">
            Open the evidence check for this device
          </button>
        </Card>
      </div>
      <RealPatterns d={d} company={company} />
    </div>
  )
}

function People({ p }: { p: Profile }) {
  return (
    <Card title="Activity log (simulated people)" testid="activity">
      <ol className="ms2-list">
        {p.activity.map((e, i) => (
          <li key={`${e.date}-${i}`} data-testid="activity-entry">
            <span className="ms-num">{niceDate(e.date)}</span> · {e.person} · <span className="ms2-muted">{e.role}</span> · {e.action}
          </li>
        ))}
      </ol>
    </Card>
  )
}

/** The summary tiles above the Our devices list, computed from the profiles and company.json. */
export function DeviceTiles({ file, company }: { file: ProfilesFile; company: Company }) {
  const s = summarize(file, company)
  const tiles: [string, number, string][] = [
    ['In development', s.development, 'development'],
    ['Under FDA review', s.review, 'review'],
    ['FDA decision, launch planned', s.decided, 'decided'],
    ['On market', s.market, 'market'],
    ['Open CAPAs', s.openCapas, 'capas'],
    ['Need a decision', s.needDecision, 'decision'],
  ]
  return (
    <section aria-label="Our devices at a glance (simulated)" data-testid="device-tiles">
      <p className="ms2-simtag">{SIM_LABEL}</p>
      <ul className="ms2-tiles">
        {tiles.map(([label, n, id]) => (
          <li key={id} className="ms2-tile" data-testid={`tile-${id}`}>
            <span className="ms-num ms2-tile-n">{n}</span>
            <span className="ms2-tile-l">{label}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

export function DeviceProfilePage({
  file,
  company,
  id,
  tab,
  onTab,
  onBack,
  onEvidence,
}: {
  file: ProfilesFile | null | undefined
  company: Company
  id: string
  tab: ProfileTab
  onTab: (t: ProfileTab, how?: TabHow) => void
  onBack: () => void
  onEvidence: (id: string) => void
}) {
  const p = file?.profiles[id]
  const d = company.devices.find((x) => x.id === id)
  useEffect(() => {
    const before = document.title
    document.title = p ? profileTitle(p, tab) : `Device profile · ${SIM_LABEL} · MaudeSignal`
    return () => {
      document.title = before
    }
  }, [p, tab])
  const back = (
    <button type="button" className="ms2-link" onClick={onBack} data-testid="profile-back">
      ← Our devices (simulated)
    </button>
  )
  if (file === undefined) return <p className="ms2-muted">Loading…</p>
  if (!p)
    return (
      <div className="space-y-3" data-testid="profile-missing">
        {back}
        <h1 className="ms2-h1">Device profile</h1>
        <p className="ms2-simtag">{SIM_LABEL}</p>
        <p>There is no stored profile for “{id}”.</p>
      </div>
    )
  return (
    <div data-testid="device-profile" data-id={p.id}>
      {back}
      <p className="ms-banner ms-banner--warn m-0 mt-2" data-testid="profile-banner">
        <span className="ws-wrap font-semibold">{file?.banner}</span>
      </p>
      <header className="ms2-pagehead mt-4">
        <h1 className="ms2-h1">
          {p.name} <span className="ms2-muted font-normal">{p.model}</span>
        </h1>
        <p className="ms2-lead">
          <span className="ms-code !text-[15px] !text-ink">{p.product_code}</span> · {p.overview.pathway} · {p.overview.status_label} · owner {p.owner}
        </p>
      </header>
      <SubTabs id="profile" label={`${p.name} profile`} tabs={PROFILE_TAB_LABELS} value={tab} onChange={onTab}>
        <SimTag />
        {tab === 'overview' && <Overview p={p} />}
        {tab === 'design' && <Design p={p} />}
        {tab === 'vv' && <VV p={p} />}
        {tab === 'regulatory' && <Regulatory p={p} />}
        {tab === 'market' && <Market p={p} />}
        {tab === 'postmarket' && <PostMarket p={p} d={d} company={company} onEvidence={() => onEvidence(p.id)} />}
        {tab === 'people' && <People p={p} />}
      </SubTabs>
    </div>
  )
}
