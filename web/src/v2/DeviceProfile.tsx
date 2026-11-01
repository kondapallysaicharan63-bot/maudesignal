// A simulated device's full lifecycle profile (/devices/<id>): seven tabs, one open at a time. Everything is
// SIMULATED sample data from company_profiles.json, except the boxes marked "Real FDA data": the product code, its FDA
// name, class and regulation number (stored openFDA data), and on Post-market the real MAUDE problem patterns already
// stored in company.json for that product code. The two are kept visually apart. One banner per page says so (and the
// document title); cards that mix real and simulated data carry the small "Simulated — sample data" tag.
import { useEffect, type ReactNode } from 'react'
import type { Company, CompanyDevice } from '../types'
import {
  DECISION_VERB,
  daysBetween,
  investigateHref,
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
import { DecisionPaths, showPath } from './DecisionPath'

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
  const cls = r === 'pass' ? 'ms2-pill ms2-pill--ok' : r === 'fail' ? 'ms2-pill ms2-pill--bad' : 'ms2-pill'
  return (
    <span className={cls} data-testid="result-chip" data-result={r}>
      {r === 'pass' ? 'Pass' : r === 'fail' ? 'Fail' : 'Planned'}
    </span>
  )
}

/** The key dates as a dated list on a drawn line (CSS only, neutral tokens): date first, then the title. */
export function Timeline({ p }: { p: Profile }) {
  const ms = p.milestones
  if (ms.length === 0) return null
  return (
    <div data-testid="timeline">
      <ol className="ms2-tl" aria-label="Key dates">
        {ms.map((m) => (
          <li key={m.key} data-planned={m.planned || undefined} data-testid="milestone" data-key={m.key} data-date={m.date}>
            <span className="ms-num ms2-tl-date">{niceDate(m.date)}</span>
            <span>
              {m.label}
              {m.planned && <span className="ms2-pill ml-2">planned</span>}
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
          {o.classification_fetched ? `, fetched ${niceDate(o.classification_fetched)}` : ''}.
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

/** "DC-21" from "... (design change DC-21)". */
const changeId = (s: string): string => /design change (DC-\d+)/.exec(s)?.[1] ?? 'the change'

function VV({ p }: { p: Profile }) {
  const v = p.vv
  const retests = new Set(v.problems.map((x) => x.retest_id))
  return (
    <div className="space-y-4">
      <Card title="Test protocols" testid="protocols">
        <ul className="ms2-list">
          {v.protocols
            .filter((t) => !retests.has(t.id))
            .map((t) => {
              const prob = v.problems.find((x) => x.found_in === t.id)
              return (
                <li key={t.id} data-testid="protocol" data-result={t.result}>
                  <p className="ms2-trow">
                    <span className="ms-code">{t.id}</span>
                    <ResultChip r={t.result} />
                  </p>
                  <p className="m-0 font-semibold">{t.title}</p>
                  <p className="ms2-muted m-0 text-[15px]">
                    {t.standard ? `${t.standard} · ` : ''}
                    {when(t)} · report {t.report}
                  </p>
                  {prob && (
                    <div className="ms2-story" data-testid="problem-story">
                      <p className="m-0">
                        <span className="font-semibold">Problem found</span> ({prob.id}): {prob.description}
                      </p>
                      <p className="m-0">
                        <span className="font-semibold">What changed:</span> {prob.change}
                      </p>
                      <p className="m-0">
                        <span className="font-semibold">Retest after change {changeId(prob.change)}:</span> {prob.retest_id} · {niceDate(prob.retest_date)} · <ResultChip r={prob.retest_result} />
                      </p>
                    </div>
                  )}
                </li>
              )
            })}
        </ul>
      </Card>
      {v.problems.length === 0 && <p className="ms2-muted m-0">No test failed for this device.</p>}
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
  const pma = r.pathway === 'PMA'
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
        <p className="ms2-muted m-0 mb-3 text-[14px]">Numbers in this format (K-SIM-, DEN-SIM-, P-SIM-, Q-SIM-) are fictional and are not FDA numbers.</p>
        <Facts
          rows={[
            ['Submission number', <span className="ms-code !text-[15px] !text-ink" data-testid="submission-number">{r.submission.number}</span>],
            ['Submitted', when(r.submission)],
            [pma ? 'FDA major deficiency letter' : 'FDA Additional Information request', r.ai_request ? `${when(r.ai_request)}. ${r.ai_request.summary}` : 'none'],
            [pma ? 'Response to the letter' : 'Response to the request', r.ai_response ? `${when(r.ai_response)}. ${r.ai_response.summary}` : 'none'],
            ['FDA decision', <span data-testid="decision">{r.decision ? `${verb} on ${when(r.decision)}` : 'pending'}</span>],
            ...(r.fda_days !== null && r.hold_days !== null
              ? ([['Review time', `${r.fda_days} FDA days + ${r.hold_days} days on hold (waiting on the response)`]] as [string, ReactNode][])
              : []),
            ...(r.predicate ? ([['Predicate', r.predicate]] as [string, ReactNode][]) : []),
          ]}
        />
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

/**
 * Monthly complaints as a list of horizontal bars (neutral tokens): every month has its own labelled row, the text is
 * 14 px or more at every width, and the figure reads as a list for a screen reader.
 */
export function ComplaintsChart({ rows }: { rows: { month: string; count: number }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.count))
  const total = rows.reduce((s, r) => s + r.count, 0)
  const summary = `Complaints per month, ${niceMonth(rows[0].month)} to ${niceMonth(rows[rows.length - 1].month)}: ${rows.map((r) => `${niceMonth(r.month)} ${r.count}`).join(', ')}. ${total} in all.`
  return (
    <figure className="m-0" data-testid="complaints-chart" aria-label={summary}>
      <ul className="ms2-hbars">
        {rows.map((r) => (
          <li key={r.month} data-testid="complaints-row">
            <span className="ms2-hbar-m">{niceMonth(r.month)}</span>
            <span className="ms2-hbar-track" aria-hidden="true">
              <span className="ms2-hbar-fill" style={{ width: `${(r.count / max) * 100}%` }} />
            </span>
            <span className="ms-num ms2-hbar-n">{r.count}</span>
          </li>
        ))}
      </ul>
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
            <li key={pt.id} data-testid="real-pattern" className="space-y-1">
              <p className="m-0 font-semibold">
                {pt.display_label.replace(/^Keyword match \(unreviewed\):\s*/i, '')}
                {pt.kind === 'keyword' ? ' (keyword match)' : ''}
              </p>
              <p className="m-0">
                <span className="ms-num">{pt.count}</span> reports
              </p>
              {pt.kind === 'keyword' && (
                <p className="m-0">
                  <span className="ms2-pill">unreviewed</span>
                </p>
              )}
              {pt.links[0] && (
                <p className="m-0 text-[15px]">
                  <a className="ms2-a" href={pt.links[0].url} target="_blank" rel="noreferrer">
                    {pt.links[0].label}
                  </a>
                </p>
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
                  <p className="ms2-trow">
                    <span className="ms-code">{c.id}</span>
                    <span className={c.state === 'open' ? 'ms2-pill' : 'ms2-pill ms2-pill--ok'}>{c.state === 'open' ? 'Open' : 'Closed'}</span>
                  </p>
                  <p className="m-0 font-semibold">{c.title}</p>
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
          {p.decision.paths.length > 0 && (
            <button type="button" className="ms2-link mt-2 mr-4" onClick={() => showPath(p.decision.paths[0].id)} data-testid="open-decision-path">
              See the decision path for these signals
            </button>
          )}
          <button type="button" className="ms2-link mt-2" onClick={onEvidence} data-testid="open-evidence">
            Open the evidence check for this device
          </button>
        </Card>
      </div>
      <DecisionPaths decision={p.decision} d={d} />
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
  const tiles: [string, number, string, boolean][] = [
    ['In development', s.development, 'development', false],
    ['Under FDA review', s.review, 'review', false],
    ['Decided, not launched', s.decided, 'decided', false],
    ['On market', s.market, 'market', false],
    ['Open CAPAs', s.openCapas, 'capas', true],
    ['Decisions due', s.needDecision, 'decision', true],
  ]
  return (
    <section aria-label="Our devices at a glance (simulated)" data-testid="device-tiles">
      <h2 className="ms2-h2 mb-2">At a glance (simulated)</h2>
      <ul className="ms2-tiles">
        {tiles.map(([label, n, id, attn]) => (
          <li key={id} className={['ms2-tile', attn ? 'ms2-tile--attn' : ''].join(' ')} data-testid={`tile-${id}`} data-attn={attn && n > 0 ? 'on' : undefined}>
            <span className="ms-num ms2-tile-n">{n}</span>
            <span className="ms2-tile-l">{label}</span>
            <span className="ms2-tile-s" data-testid={id === 'decision' ? 'tile-decision-sub' : undefined}>
              {id === 'decision' ? `on ${s.needDecisionDevices} ${s.needDecisionDevices === 1 ? 'device' : 'devices'}` : ''}
            </span>
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
        <p className="ms-banner ms-banner--warn m-0" data-testid="profile-banner">
          <span className="ws-wrap font-semibold">{SIM_LABEL}</span>
        </p>
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
        <p className="m-0 mt-1">
          <a className="ms2-smalllink" href={investigateHref(p.product_code, p.id)} data-testid="investigate-link">
            Investigate a complaint on this device
          </a>
        </p>
      </header>
      <SubTabs id="profile" label={`${p.name} profile`} tabs={PROFILE_TAB_LABELS} value={tab} onChange={onTab}>
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
