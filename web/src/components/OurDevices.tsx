import { CLASS_LABEL } from '../artifacts'
import { devicesPerStatus } from '../dashboard'
import { isoDay } from '../data'
import { Icon } from '../icons'
import type { Company, CompanyDevice, CompanyPattern } from '../types'
import { Pill, type Tone } from './artifacts/common'

/** Shown on every view of this workflow (text comes from company.json; a test checks it is the contract string). */
export function CompanyBanner({ company }: { company: Company }) {
  return (
    <p className="ms-banner ms-banner--warn m-0" data-testid="company-banner">
      <span className="ws-wrap font-semibold">{company.banner}</span>
    </p>
  )
}

const STATUS_TONE: Record<string, Tone> = {
  'Needs review': 'bad',
  'Testing in progress': 'warn',
  'Already covered': 'ok',
  'Not applicable to our device': 'neutral',
  'Monitoring — nothing open': 'neutral',
}

/** The status as a chip. The words carry the meaning; the colour only helps. */
export function StatusChip({ label }: { label: string }) {
  return (
    <span className={`ws-pill ws-wrap !shrink max-w-full text-left ${chipTone(label)}`} data-testid="status-chip">
      {label}
    </span>
  )
}

const TONE_CLASS: Record<Tone, string> = {
  ok: 'bg-success-soft text-success',
  bad: 'bg-critical-soft text-critical',
  warn: 'bg-warning-soft text-warning',
  neutral: 'bg-sunk text-ink-2',
}
const chipTone = (label: string): string => TONE_CLASS[STATUS_TONE[label] ?? 'neutral']

/** "20260930" as "2026-09-30". */
const day = (d: string | null): string => (d ? isoDay(d) : 'not stored')

/** Devices per status, for the expanded mini-dashboard: a bar per status, widths from the counts. */
export function StatusBars({ company }: { company: Company }) {
  const per = devicesPerStatus(company)
  const max = Math.max(1, ...per.map((x) => x.count))
  return (
    <div className="mt-4" data-testid="status-bars">
      <h3 className="ms-kicker m-0 mb-2">Devices per status</h3>
      <ul className="m-0 list-none p-0">
        {per.map((x) => (
          <li key={x.label} className="py-1">
            <div className="flex justify-between gap-2 text-[17px]">
              <span className="ws-wrap">{x.label}</span>
              <span className="ms-num">{x.count}</span>
            </div>
            <div className="h-2 rounded-xs bg-sunk" aria-hidden="true">
              <div className="h-2 rounded-xs bg-accent" style={{ width: `${(x.count / max) * 100}%` }} />
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

function DeviceTable({ company, onDevice }: { company: Company; onDevice: (id: string) => void }) {
  return (
    <div className="rounded-md border border-rule">
      <table className="w-full table-fixed border-collapse text-left text-[17px]" aria-label="Our devices (simulated)">
        <thead>
          <tr className="bg-sunk text-[17px] text-ink-2">
            <th className="w-[44%] px-3 py-2 font-semibold">Device</th>
            <th className="w-[14%] px-2 py-2 font-semibold">Code</th>
            <th className="px-2 py-2 font-semibold">Status</th>
          </tr>
        </thead>
        <tbody>
          {company.devices.map((d) => (
            <tr key={d.id} className="border-t border-rule align-top">
              <td className="px-3 py-1">
                <button
                  type="button"
                  className="ws-wrap min-h-11 w-full text-left text-accent"
                  onClick={() => onDevice(d.id)}
                  aria-label={`${d.name} ${d.model}, ${d.status?.label ?? 'no status'}. Open.`}
                >
                  <span className="underline">{d.name}</span>
                  <span className="block text-[15px] text-ink-2">
                    {d.model} · {d.owner}
                  </span>
                </button>
              </td>
              <td className="ms-code px-2 py-3 !text-[17px]">{d.product_code}</td>
              <td className="px-2 py-3">{d.status ? <StatusChip label={d.status.label} /> : <span className="text-ink-2">none</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function CompanyList({ company, onDevice }: { company: Company; onDevice: (id: string) => void }) {
  const need = company.devices.filter((d) => d.status?.label === 'Needs review').length
  return (
    <div className="space-y-4">
      <div>
        <h1 className="t-title-lg m-0">Our devices (simulated)</h1>
        <p className="mt-2 text-ink-2">
          Does this apply to us? {company.company ?? 'A simulated company'} has {company.devices.length} fictional devices. For each one,
          the real FDA reports and recalls on its product code are shown, so a person can decide what to do. Signals for human review, not
          medical advice.
        </p>
      </div>
      <CompanyBanner company={company} />
      {company.devices.length === 0 ? (
        <p className="text-ink-2">No simulated devices are stored.</p>
      ) : (
        <>
          <p className="m-0 text-ink" data-testid="need-review-line">
            <span className="ms-num font-semibold">{need}</span> {need === 1 ? 'device needs' : 'devices need'} review.
          </p>
          <DeviceTable company={company} onDevice={onDevice} />
        </>
      )}
      <p className="m-0 text-[15px] leading-snug text-ink-2">
        A status is set by a named simulated person, never by the tool, and only moves forward. Every change is in a hash-chained audit
        {company.audit.chain_ok === true && ' that was recomputed when this page was built and is intact'}.
      </p>
      {company.notes.length > 0 && (
        <details>
          <summary className="min-h-11 cursor-pointer py-2 text-[17px] text-ink-2">Notes ({company.notes.length})</summary>
          <ul className="m-0 list-disc pl-5 text-[17px] text-ink-2">
            {company.notes.map((n) => (
              <li key={n} className="ws-wrap">
                {n}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

const KEYWORD_CAPTION =
  'Keyword groups are deterministic keyword matches on MAUDE problem terms and narrative phrases. They are not a reviewed classification: a person must read the reports.'

function Pattern({ p }: { p: CompanyPattern }) {
  return (
    <li className="border-t border-rule py-3 first:border-t-0" data-testid="pattern">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="ws-wrap m-0 text-[18px] font-semibold">{p.display_label}</h4>
        <span className="ms-num text-ink-2">{p.count} reports</span>
      </div>
      <p className="ws-wrap m-0 mt-1 text-[17px] text-ink-2">
        {p.first_received && p.last_received ? `Received ${day(p.first_received)} to ${day(p.last_received)}. ` : ''}
        Basis: {p.basis}. Count: {p.gate.reason}.
      </p>
      {p.quotes.map((q) => (
        <blockquote key={q.report_id} className="m-0 mt-2 border-l-4 border-rule-strong pl-3 text-[17px] leading-snug">
          <span className="ws-wrap">“{q.text}”</span>
          <a className="ws-wrap mt-1 block min-h-11 py-2 text-accent underline" href={q.url} target="_blank" rel="noreferrer">
            MAUDE report {q.report_id}
          </a>
        </blockquote>
      ))}
      {p.gate.quotes_withheld > 0 && (
        <p className="m-0 mt-1 text-[15px] text-ink-2">{p.gate.quotes_withheld} quote not shown: it did not pass the check.</p>
      )}
      <details className="mt-1">
        <summary className="min-h-11 cursor-pointer py-2 text-[17px] text-ink-2">Evidence links ({p.links.length})</summary>
        <ul className="m-0 list-none p-0">
          {p.links.map((l) => (
            <li key={l.url} className="py-1">
              <a className="ws-wrap text-[17px] text-accent underline" href={l.url} target="_blank" rel="noreferrer">
                {l.label}
              </a>
            </li>
          ))}
        </ul>
      </details>
    </li>
  )
}

function Evidence({ d }: { d: CompanyDevice }) {
  const ev = d.evidence
  if (!ev.available)
    return (
      <section aria-label="Evidence" className="rounded-md border border-rule bg-sunk p-4" data-testid="evidence-missing">
        <h3 className="ms-kicker m-0">Real FDA evidence for {d.product_code}</h3>
        <p className="m-0 mt-2 font-semibold">{ev.note ?? 'evidence not fetched yet'}</p>
        <p className="m-0 mt-1 text-ink-2">No count, pattern or quote is shown for this device until the evidence is fetched.</p>
      </section>
    )
  const rc = ev.recalls
  const keyword = d.patterns.some((p) => p.kind === 'keyword')
  return (
    <section aria-label="Evidence" className="space-y-4">
      <div className="rounded-md border border-rule bg-surface p-4">
        <h3 className="ms-kicker m-0">Real FDA evidence for {d.product_code}</h3>
        <dl className="m-0 mt-2 grid grid-cols-2 gap-2">
          <div className="rounded-md border border-rule bg-paper p-3 max-sm:p-2">
            <dt className="text-[17px] leading-snug text-ink-2">MAUDE reports</dt>
            <dd className="t-index ms-num m-0 mt-1" data-testid="report-count">
              {ev.report_count ? ev.report_count.value : 'not stored'}
            </dd>
            {ev.window?.date_from && ev.window.date_to && (
              <dd className="m-0 text-[15px] text-ink-2">
                received {day(ev.window.date_from)} to {day(ev.window.date_to)}
              </dd>
            )}
          </div>
          <div className="rounded-md border border-rule bg-paper p-3 max-sm:p-2">
            <dt className="text-[17px] leading-snug text-ink-2">Recalls</dt>
            <dd className="t-index ms-num m-0 mt-1" data-testid="recall-count">
              {rc ? rc.stored : 'not stored'}
            </dd>
            {rc && rc.matched_total !== null && rc.matched_total > rc.stored && (
              <dd className="m-0 text-[15px] text-ink-2">
                {rc.stored} stored of {rc.matched_total} matched
              </dd>
            )}
          </div>
        </dl>
        {ev.report_count && <p className="ws-wrap m-0 mt-2 text-[15px] text-ink-2">Report count: {ev.report_count.reason}.</p>}
        {ev.queries.length > 0 && (
          <details className="mt-1">
            <summary className="min-h-11 cursor-pointer py-2 text-[17px] text-ink-2">openFDA queries ({ev.queries.length})</summary>
            <ul className="m-0 list-none p-0">
              {ev.queries.map((q) => (
                <li key={q.url} className="py-1">
                  <a className="ws-wrap text-[17px] text-accent underline" href={q.url} target="_blank" rel="noreferrer">
                    {q.label}
                  </a>
                </li>
              ))}
            </ul>
          </details>
        )}
        {ev.gate_totals && (
          <p className="m-0 mt-1 text-[15px] text-ink-2">
            Claim gate on this device: {ev.gate_totals.pass} passed, {ev.gate_totals.block} blocked.
          </p>
        )}
      </div>

      <div className="rounded-md border border-rule bg-surface p-4">
        <h3 className="ms-kicker m-0">Patterns in the reports · {d.patterns.length}</h3>
        {d.patterns.length === 0 ? (
          <p className="m-0 mt-2 text-ink-2" data-testid="no-patterns">
            No group of {2} or more reports matched. That is not a finding; a person should still read the reports.
          </p>
        ) : (
          <>
            <ul className="m-0 mt-2 list-none p-0">
              {d.patterns.map((p) => (
                <Pattern key={p.id} p={p} />
              ))}
            </ul>
            {keyword && <p className="m-0 mt-2 text-[15px] leading-snug text-ink-2">{KEYWORD_CAPTION}</p>}
          </>
        )}
      </div>

      {rc && rc.latest.length > 0 && (
        <div className="rounded-md border border-rule bg-surface p-4">
          <h3 className="ms-kicker m-0">Latest recalls on this code</h3>
          <ul className="m-0 mt-2 list-none p-0">
            {rc.latest.map((r) => (
              <li key={r.recall_number} className="border-t border-rule py-3 first:border-t-0">
                <p className="ws-wrap m-0 font-semibold">
                  {r.recall_number} · {r.recalling_firm ?? 'firm not stored'}
                </p>
                <p className="m-0 text-[17px] text-ink-2">
                  {r.status ?? 'status not stored'} · initiated {day(r.date_initiated)}
                </p>
                {r.excerpt && <p className="ws-wrap m-0 mt-1 text-[17px]">“{r.excerpt}”</p>}
                {r.url && (
                  <a
                    className="ws-wrap block min-h-11 py-2 text-[17px] text-accent underline"
                    href={r.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    FDA recall page
                  </a>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

function History({ d, chainOk, firstBad }: { d: CompanyDevice; chainOk: boolean | null; firstBad: number | null }) {
  return (
    <section aria-label="Status history" className="rounded-md border border-rule bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="ms-kicker m-0">Status history · {d.history.length}</h3>
        {chainOk === true && <Pill tone="ok">Chain ok</Pill>}
        {chainOk === false && <Pill tone="bad">Chain broken at entry {firstBad}</Pill>}
      </div>
      <ol className="m-0 mt-2 list-none p-0" data-testid="history">
        {d.history.map((h) => (
          <li key={h.seq} className="border-t border-rule py-3 first:border-t-0">
            <p className="ws-wrap m-0 font-semibold">
              {h.from_status ? `${h.from_status} → ${h.to_status}` : `Registered as ${h.to_status}`}
            </p>
            <p className="ws-wrap m-0 text-[17px] text-ink-2">
              <span className="ms-num">{h.date}</span> · set by {h.actor} · entry {h.seq}
            </p>
            {Object.keys(h.details).length > 0 && (
              <p className="ws-wrap m-0 text-[17px] text-ink-2">
                {Object.entries(h.details)
                  .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${v}`)
                  .join(' · ')}
              </p>
            )}
            {h.note && <p className="ws-wrap m-0 text-[17px]">{h.note}</p>}
          </li>
        ))}
      </ol>
      <p className="m-0 mt-2 text-[15px] leading-snug text-ink-2">
        Each entry is chained to the one before it with a SHA-256 hash; the chain was recomputed when this page was built.
      </p>
    </section>
  )
}

export function CompanyDeviceView({ company, device: d, onBack }: { company: Company; device: CompanyDevice; onBack: () => void }) {
  return (
    <div className="space-y-4" data-testid="device-detail">
      <button type="button" className="ms-btn ms-btn--secondary" style={{ height: 44 }} onClick={onBack}>
        <Icon name="back" size={18} /> All devices
      </button>
      <div>
        <h1 className="t-title-lg ws-wrap m-0">{d.name}</h1>
        <p className="ws-wrap m-0 mt-1 text-ink-2">
          {d.model} · product code <span className="ms-code !text-[17px]">{d.product_code}</span>
          {d.device_type.name ? ` · ${d.device_type.name}` : ''} · owner {d.owner}
        </p>
      </div>
      <CompanyBanner company={company} />
      <section aria-label="Status" className="rounded-md border border-rule-strong bg-surface p-4">
        <h3 className="ms-kicker m-0">Status</h3>
        {d.status ? (
          <>
            <p className="m-0 mt-2">
              <StatusChip label={d.status.label} />
            </p>
            <p className="ws-wrap m-0 mt-2 text-[17px] text-ink-2">
              Set by {d.status.set_by} on <span className="ms-num">{d.status.date}</span>
              {d.status.detail ? ` · ${d.status.detail}` : ''}
            </p>
          </>
        ) : (
          <p className="m-0 mt-2 text-ink-2">No status is stored.</p>
        )}
        {d.sweep && (
          <p className="ws-wrap m-0 mt-2 text-[17px] text-ink-2">
            AI device sweep, as of <span className="ms-num">{day(d.sweep.as_of)}</span>:{' '}
            {CLASS_LABEL[d.sweep.classification] ?? d.sweep.classification} ·{' '}
            <a className="text-accent underline" href={d.sweep.query_url} target="_blank" rel="noreferrer">
              openFDA query
            </a>
          </p>
        )}
      </section>
      <Evidence d={d} />
      <History d={d} chainOk={company.audit.chain_ok} firstBad={company.audit.first_bad_seq} />
    </div>
  )
}

/** The workflow page: the device table, or one device when `deviceId` is set. */
export function OurDevices({
  company,
  deviceId,
  onDevice,
  onBack,
}: {
  company: Company
  deviceId: string | null
  onDevice: (id: string) => void
  onBack: () => void
}) {
  const d = deviceId ? company.devices.find((x) => x.id === deviceId) : undefined
  if (deviceId && !d)
    return (
      <div className="space-y-4">
        <CompanyBanner company={company} />
        <p>That device is not in the stored data.</p>
        <button type="button" className="ms-btn ms-btn--secondary" style={{ height: 44 }} onClick={onBack}>
          All devices
        </button>
      </div>
    )
  return d ? <CompanyDeviceView company={company} device={d} onBack={onBack} /> : <CompanyList company={company} onDevice={onDevice} />
}
