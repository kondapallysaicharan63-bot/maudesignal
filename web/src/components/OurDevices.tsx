import { useAlertPanel } from '../alertPanelContext'
import { MentionsBox } from './MentionsBox'
import { useEffect, useState, type ReactNode } from 'react'
import { CLASS_LABEL } from '../artifacts'
import { NEEDS_REVIEW, sortedDevices, statusesByPriority } from '../dashboard'
import { isoDay } from '../data'
import { Icon } from '../icons'
import { nextStatuses } from '../myCompany'
import { useMine } from '../useMyCompany'
import { MakeItYours, MineBar } from './MakeItYours'
import type { Company, CompanyDevice, CompanyPattern } from '../types'
import type { Tone } from './artifacts/common'

/** Shown on every view of this workflow (text comes from company.json; a test checks it is the contract string). */
export function CompanyBanner({ company }: { company: Company }) {
  // Amber is for the simulated company only; the person's own company gets the success tint and a lock (the privacy line).
  if (company.mine === true)
    return (
      <p className="ms-banner ms-banner--mine m-0" data-testid="company-banner">
        <Icon name="lock" size={18} />
        <span className="ws-wrap font-semibold">{company.banner}</span>
      </p>
    )
  return (
    <p className="ms-banner ms-banner--warn m-0" data-testid="company-banner">
      <span className="ws-wrap font-semibold">{company.banner}</span>
    </p>
  )
}

/** True below 480 px: the device table then renders as stacked cards. */
function useNarrow(max = 480): boolean {
  const q = `(max-width: ${max - 1}px)`
  const get = () => (typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia(q).matches : false)
  const [n, setN] = useState(get)
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const m = window.matchMedia(q)
    const on = () => setN(m.matches)
    on()
    m.addEventListener('change', on)
    return () => m.removeEventListener('change', on)
  }, [q])
  return n
}

const STATUS_TONE: Record<string, Tone> = {
  'Needs review': 'bad',
  'Testing in progress': 'warn',
  'Already covered': 'ok',
  'Not applicable to our device': 'neutral',
  'Monitoring — nothing open': 'neutral',
}
const toneOf = (label: string): Tone => STATUS_TONE[label] ?? 'neutral'

// Class names are written out in full so Tailwind can see them.
const CHIP: Record<Tone, string> = {
  ok: 'bg-success-soft text-success ws-pill--ring',
  bad: 'bg-critical text-[var(--on-critical)]',
  warn: 'bg-warning-soft text-warning ws-pill--ring',
  neutral: 'bg-sunk text-ink-2 ws-pill--ring',
}
/** Dot and bar colours that match the chips. */
const FILL: Record<Tone, string> = { ok: 'bg-success', bad: 'bg-critical', warn: 'bg-warning', neutral: 'bg-ink-3' }
/** The status card on a device: a thick coloured edge and a tinted body. */
const CARD: Record<Tone, string> = {
  ok: 'border-l-[10px] border-l-success bg-success-soft',
  bad: 'border-l-[10px] border-l-critical bg-critical-soft',
  warn: 'border-l-[10px] border-l-warning bg-warning-soft',
  neutral: 'border-l-[10px] border-l-ink-3 bg-sunk',
}

/** The status as a chip. The words carry the meaning; the colour only helps. "Needs review" is the one filled chip. */
export function StatusChip({ label, large = false }: { label: string; large?: boolean }) {
  return (
    <span
      className={`ws-pill ws-wrap !shrink max-w-full text-left ${CHIP[toneOf(label)]} ${large ? '!px-3 !py-1 !text-[20px]' : ''}`}
      data-testid="status-chip"
    >
      {label}
    </span>
  )
}

/** "20260930" as "2026-09-30". */
const day = (d: string | null): string => (d ? isoDay(d) : 'not stored')

/** Section heading: a real heading in sentence case, so the page has a visible hierarchy. */
function SectionTitle({ children, id }: { children: ReactNode; id?: string }) {
  return (
    <h3 id={id} className="m-0 font-serif text-[22px] font-semibold leading-tight text-ink">
      {children}
    </h3>
  )
}

type FilterFn = (label: string | null) => void
const rowsOf = (company: Company) => [
  { label: 'All devices', value: null as string | null, count: company.devices.length },
  ...statusesByPriority(company).map((x) => ({ label: x.label, value: x.label as string | null, count: x.count })),
]

/** Devices per status, for the expanded mini-dashboard: a bar per status in the chips' colours; a tap opens the table filtered to it. */
export function StatusBars({ company, onFilter }: { company: Company; onFilter?: FilterFn }) {
  const per = statusesByPriority(company)
  const max = Math.max(1, ...per.map((x) => x.count))
  return (
    <div className="mt-2" data-testid="status-bars">
      <CompanyBanner company={company} />
      <h3 className="m-0 mt-3 font-serif text-[22px] font-semibold">Devices per status</h3>
      <p className="m-0 mb-2 text-[17px] text-ink-2">Tap a bar to see those devices in the table.</p>
      <ul className="m-0 list-none p-0">
        {per.map((x) => (
          <li key={x.label} className="border-t border-rule first:border-t-0">
            <button
              type="button"
              className="block min-h-11 w-full rounded-xs py-2 text-left hover:bg-sunk"
              onClick={() => onFilter?.(x.label)}
              aria-label={`${x.label}: ${x.count} ${x.count === 1 ? 'device' : 'devices'}. Show them in the table.`}
            >
              <span className="flex justify-between gap-2 text-[17px]">
                <span className="ws-wrap">{x.label}</span>
                <span className="ms-num font-semibold">{x.count}</span>
              </span>
              <span className="mt-1 block h-3 rounded-xs bg-sunk" aria-hidden="true">
                <span className={`block h-3 rounded-xs ${FILL[toneOf(x.label)]}`} style={{ width: `${(x.count / max) * 100}%` }} />
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Compact list for the left column: a row per status with its count; a row filters the table. */
export function StatusFilterList({ company, filter, onFilter }: { company: Company; filter: string | null; onFilter: FilterFn }) {
  return (
    <ul className="m-0 list-none p-0" aria-label="Filter devices by status" data-testid="status-filter-list">
      {rowsOf(company).map((r) => (
        <li key={r.label}>
          <button
            type="button"
            aria-pressed={filter === r.value}
            onClick={() => onFilter(r.value)}
            className={[
              'flex min-h-11 w-full items-center gap-2 rounded-xs px-2 py-2 text-left text-[17px] leading-snug hover:bg-sunk',
              filter === r.value ? 'bg-accent-soft font-semibold shadow-[inset_4px_0_0_var(--accent)]' : '',
            ].join(' ')}
          >
            {r.value !== null && <span className={`h-3 w-3 shrink-0 rounded-full ${FILL[toneOf(r.label)]}`} aria-hidden="true" />}
            <span className="ws-wrap min-w-0 flex-1">{r.label}</span>
            <span className="ms-num shrink-0 font-semibold">{r.count}</span>
          </button>
        </li>
      ))}
    </ul>
  )
}

/** Short chip names (the full status is in the chip's label and in the table). */
export const chipName = (label: string | null): string =>
  label === null
    ? 'All'
    : ({
        'Needs review': 'Needs review',
        'Testing in progress': 'Testing',
        'Monitoring — nothing open': 'Monitoring',
        'Already covered': 'Covered',
        'Not applicable to our device': 'Not applicable',
      } as Record<string, string>)[label] ?? label

/** Filter chips with counts (the same filter as the left column). */
function FilterChips({ company, filter, onFilter }: { company: Company; filter: string | null; onFilter: FilterFn }) {
  return (
    <div role="group" aria-label="Filter by status" className="flex gap-2 overflow-x-auto pb-1 sm:flex-wrap sm:overflow-visible sm:pb-0" data-testid="filter-chips">
      {rowsOf(company).map((c) => (
        <button
          key={c.label}
          type="button"
          aria-pressed={filter === c.value}
          aria-label={`${c.label}: ${c.count}`}
          title={c.label}
          onClick={() => onFilter(c.value)}
          className={[
            'min-h-11 shrink-0 whitespace-nowrap rounded-xs border px-3 text-[17px] leading-tight',
            filter === c.value ? 'border-ink bg-inverse font-semibold text-on-inverse' : 'border-rule-strong bg-surface text-ink hover:bg-sunk',
          ].join(' ')}
        >
          {chipName(c.value)} <span className="ms-num font-semibold">{c.count}</span>
        </button>
      ))}
    </div>
  )
}

/** Opens the alert panel of a Needs review device. */
function AlertDetailsButton({ id, code, label }: { id: string; code: string; label: string }) {
  const { openAlert } = useAlertPanel()
  return (
    <button
      type="button"
      className="mt-1 flex min-h-11 items-center text-left text-[16px] font-semibold text-accent underline"
      onClick={() => openAlert(id, code)}
      aria-label={`Alert details for ${label}`}
      data-testid="device-alert-details"
    >
      Alert details
    </button>
  )
}

function DeviceTable({ rows, onDevice, mine = false, v2 = false }: { rows: CompanyDevice[]; onDevice: (id: string) => void; mine?: boolean; v2?: boolean }) {
  // v2 only: the owner's "(simulated)" is dropped from every row (the page title says it), and the whole row opens the device.
  const ownerOf = (o: string) => (v2 ? o.replace(/ \(simulated\)$/, '') : o)
  const th = 'sticky top-0 z-10 border-b border-rule bg-sunk px-2 py-2 font-semibold'
  const narrow = useNarrow()
  if (narrow)
    return (
      <ul className="m-0 list-none space-y-2 p-0" aria-label={mine ? 'Our devices (your company)' : 'Our devices (simulated)'} data-testid="device-cards">
        {rows.map((d) => {
          const need = d.status?.label === NEEDS_REVIEW
          return (
            <li key={d.id} className={['rounded-md border border-rule px-3 py-2', need ? 'bg-critical-soft shadow-[inset_6px_0_0_var(--critical)] pl-4' : 'bg-surface', v2 ? 'ms2-rowlink' : ''].join(' ')} data-needs-review={need || undefined}>
              <button
                type="button"
                className="block min-h-11 w-full text-left text-accent"
                onClick={() => onDevice(d.id)}
                aria-label={`${d.name} ${d.model}, ${d.status?.label ?? 'no status'}. Open.`}
              >
                {v2 ? (
                  <>
                    <span className={['ws-wrap block underline', need ? 'font-semibold' : ''].join(' ')}>{d.name}</span>
                    <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span className="ms-code !text-[16px] !text-ink">{d.product_code}</span>
                      {d.status ? <StatusChip label={d.status.label} /> : <span className="text-ink-2">none</span>}
                    </span>
                    <span className="mt-1 block text-[16px] text-ink-2">
                      {d.model} · {ownerOf(d.owner)}
                    </span>
                  </>
                ) : (
                  <>
                    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span className={['ws-wrap min-w-0 underline', need ? 'font-semibold' : ''].join(' ')}>{d.name}</span>
                      <span className="ms-code !text-[16px] !text-ink">{d.product_code}</span>
                      {d.status ? <StatusChip label={d.status.label} /> : <span className="text-ink-2">none</span>}
                    </span>
                    <span className="mt-0.5 block text-[16px] text-ink-2">
                      {d.model} · {d.owner}
                    </span>
                  </>
                )}
              </button>
              {need && !v2 && <AlertDetailsButton id={`company:${d.id}`} code={d.product_code} label={`${d.name}`} />}
            </li>
          )
        })}
      </ul>
    )
  return (
    <div className="rounded-md border border-rule bg-surface">
      <table className="w-full table-fixed border-collapse text-left text-[17px]" aria-label={mine ? 'Our devices (your company)' : 'Our devices (simulated)'}>
        <thead>
          <tr className="text-[17px] text-ink-2">
            <th className={`${th} w-[44%] px-3`}>Device</th>
            <th className={`${th} w-[16%]`}>Code</th>
            <th className={th}>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((d) => {
            const need = d.status?.label === NEEDS_REVIEW
            return (
              <tr key={d.id} className={['border-t border-rule align-top', need ? 'bg-critical-soft' : '', v2 ? 'ms2-rowlink' : ''].join(' ')} data-needs-review={need || undefined} onClick={v2 ? () => onDevice(d.id) : undefined}>
                <td className={['px-3 py-1', need ? 'pl-4 shadow-[inset_6px_0_0_var(--critical)]' : ''].join(' ')}>
                  <button
                    type="button"
                    className="ws-wrap min-h-11 w-full text-left text-accent"
                    onClick={() => onDevice(d.id)}
                    aria-label={`${d.name} ${d.model}, ${d.status?.label ?? 'no status'}. Open.`}
                  >
                    <span className={['underline', need ? 'font-semibold' : ''].join(' ')}>{d.name}</span>
                    <span className="block text-[16px] text-ink-2">
                      {d.model} · {ownerOf(d.owner)}
                    </span>
                  </button>
                </td>
                <td className="ms-code px-2 py-3 !text-[17px]">{d.product_code}</td>
                <td className="px-2 py-3">
                  {d.status ? <StatusChip label={d.status.label} /> : <span className="text-ink-2">none</span>}
                  {need && !v2 && <AlertDetailsButton id={`company:${d.id}`} code={d.product_code} label={`${d.name}`} />}
                  {v2 && (
                    <span className="ms2-chev" aria-hidden="true">
                      ›
                    </span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function CompanyList({
  company,
  onDevice,
  filter = null,
  onFilter = () => undefined,
  v2 = false,
}: {
  company: Company
  onDevice: (id: string) => void
  /** Status the table is filtered to (null: all). Set from the chips, the left column, the bars or the bell. */
  filter?: string | null
  onFilter?: FilterFn
  /** The v2 layout's list: whole row opens the device, no "Make it yours" bar (it has its own tab), no alert button. */
  v2?: boolean
}) {
  const need = company.devices.filter((d) => d.status?.label === NEEDS_REVIEW).length
  const rows = sortedDevices(company, filter)
  const mine = company.mine === true
  const [editor, setEditor] = useState(false)
  const api = useMine()
  return (
    <div className="space-y-3">
      <div>
        <h1 className="t-title-lg m-0">{mine ? 'Our devices (your company)' : 'Our devices (simulated)'}</h1>
        <p className="mt-1 text-ink-2 max-sm:hidden">
          {mine
            ? `Does this apply to us? ${company.company ?? 'Your company'} has ${company.devices.length} ${company.devices.length === 1 ? 'device' : 'devices'} that you entered. The real FDA reports and recalls on a product code are shown where they are stored.`
            : `Does this apply to us? ${company.company ?? 'A simulated company'} has ${company.devices.length} fictional devices. The real FDA reports and recalls on each product code are shown so a person can decide.`}
        </p>
      </div>
      {api && !v2 && (
        <MineBar
          open={editor}
          onOpen={() => {
            api.setMode('mine')
            setEditor((o) => !o)
          }}
        />
      )}
      <CompanyBanner company={company} />
      {api && editor && api.mode === 'mine' && <MakeItYours onClose={() => setEditor(false)} />}
      {company.devices.length === 0 ? (
        <p className="text-ink-2" data-testid="no-devices">
          {mine ? 'No devices yet. Press Make it yours to add some.' : 'No simulated devices are stored.'}
        </p>
      ) : (
        <>
          <p className="m-0 text-ink" data-testid="need-review-line">
            <span className="ms-num font-semibold">{need}</span> {need === 1 ? 'device needs' : 'devices need'} review.<span className="max-sm:hidden"> Sorted by status, then by the date it was set.</span>
          </p>
          <FilterChips company={company} filter={filter} onFilter={onFilter} />
          {rows.length === 0 ? <p className="text-ink-2">No device has this status.</p> : <DeviceTable rows={rows} onDevice={onDevice} mine={mine} v2={v2} />}
        </>
      )}
      {mine ? (
        <p className="m-0 text-[16px] leading-snug text-ink-2" data-testid="mine-footer">
          A status is set by you, never by the tool, and only moves forward. Changes are listed on the device page and kept only in this
          browser; they are not hash-chained or sent anywhere. Signals for human review, not medical advice.
        </p>
      ) : (
        <p className="m-0 text-[16px] leading-snug text-ink-2">
          A status is set by a named simulated person, never by the tool, and only moves forward. Every change is in a hash-chained audit
          {company.audit.chain_ok === true && ' that was recomputed when this page was built and is intact'}. Signals for human review, not
          medical advice.
        </p>
      )}
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

/** The label without its long "Keyword match (unreviewed): " prefix (the badge says it instead). */
export const shortPatternLabel = (p: CompanyPattern): string => p.display_label.replace(/^Keyword match \(unreviewed\):\s*/i, '')
const isUnreviewed = (p: CompanyPattern): boolean => /unreviewed/i.test(p.display_label) || p.kind === 'keyword'

function Pattern({ p }: { p: CompanyPattern }) {
  return (
    <li className="border-t border-rule py-3 first:border-t-0" data-testid="pattern">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h4 className="ws-wrap m-0 min-w-0 flex-1 text-[19px] font-semibold leading-snug">{shortPatternLabel(p)}</h4>
        <span className="ms-num shrink-0 text-[19px] font-semibold">{p.count} reports</span>
      </div>
      {isUnreviewed(p) && (
        <p className="m-0 mt-1">
          <span className="ws-pill bg-sunk text-ink-2 ws-pill--ring">Unreviewed</span>
        </p>
      )}
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
        <p className="m-0 mt-1 text-[16px] text-ink-2">{p.gate.quotes_withheld} quote not shown: it did not pass the check.</p>
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

/** Why a device has no evidence and what a person does about it. The page itself cannot call openFDA. */
function MissingEvidence({ d }: { d: CompanyDevice }) {
  const [how, setHow] = useState(false)
  const ev = d.evidence
  return (
    <section
      id="dev-evidence"
      aria-label="Evidence"
      className="scroll-mt-16 rounded-md border-2 border-warning bg-warning-soft p-4"
      data-testid="evidence-missing"
    >
      <div className="flex items-start gap-3">
        <span className="mt-1 shrink-0 text-warning">
          <Icon name="warn" size={28} />
        </span>
        <div className="min-w-0">
          <SectionTitle>Real FDA evidence for {d.product_code}</SectionTitle>
          <p className="ws-wrap m-0 mt-2 text-[20px] font-semibold text-ink">{ev.note ?? 'evidence not fetched yet'}</p>
          <p className="ws-wrap m-0 mt-1 text-ink">
            Reason: this product code has no rows in the demo database and no fetched evidence file, so nothing is stored for it
            (origin: {ev.origin}). No count, pattern or quote is shown for this device until the evidence is fetched.
          </p>
          <button
            type="button"
            className="ms-btn ws-btn-primary mt-3"
            style={{ height: 44 }}
            aria-expanded={how}
            aria-controls="fetch-how"
            onClick={() => setHow((h) => !h)}
          >
            Fetch evidence
          </button>
          {how && (
            <p id="fetch-how" className="ws-wrap m-0 mt-3 text-[17px] text-ink">
              This page shows stored data only and cannot call openFDA. A person fetches the evidence with{' '}
              <span className="ms-code !text-[17px] !text-ink">scripts/fetch_company_evidence.py</span> (it stores openFDA counts for the code
              in demo/company/evidence/), then the web export is run again.
            </p>
          )}
        </div>
      </div>
    </section>
  )
}

function Evidence({ d }: { d: CompanyDevice }) {
  const ev = d.evidence
  if (!ev.available) return <MissingEvidence d={d} />
  const rc = ev.recalls
  const keyword = d.patterns.some((p) => p.kind === 'keyword')
  const patterns = [...d.patterns].sort((a, b) => b.count - a.count || a.id.localeCompare(b.id))
  return (
    <div className="space-y-4">
      <section id="dev-evidence" aria-label="Evidence" className="scroll-mt-16 rounded-md border border-rule bg-surface p-4">
        <SectionTitle>Real FDA evidence for {d.product_code}</SectionTitle>
        <dl className="m-0 mt-3 grid grid-cols-2 gap-3">
          <div className="rounded-md border border-rule bg-paper p-3 max-sm:p-2">
            <dt className="text-[17px] leading-snug text-ink-2">MAUDE reports</dt>
            <dd className="ms-num m-0 mt-1 font-serif text-[48px] font-medium leading-none max-sm:text-[40px]" data-testid="report-count">
              {ev.report_count ? ev.report_count.value : 'not stored'}
            </dd>
            {ev.window?.date_from && ev.window.date_to && (
              <dd className="m-0 mt-1 text-[16px] leading-snug text-ink-2">
                received {day(ev.window.date_from)} to {day(ev.window.date_to)}
              </dd>
            )}
          </div>
          <div className="rounded-md border border-rule bg-paper p-3 max-sm:p-2">
            <dt className="text-[17px] leading-snug text-ink-2">Recalls</dt>
            <dd className="ms-num m-0 mt-1 font-serif text-[48px] font-medium leading-none max-sm:text-[40px]" data-testid="recall-count">
              {rc ? rc.stored : 'not stored'}
            </dd>
            {rc && rc.matched_total !== null && rc.matched_total > rc.stored && (
              <dd className="m-0 mt-1 text-[16px] leading-snug text-ink-2">
                {rc.stored} stored of {rc.matched_total} matched
              </dd>
            )}
          </div>
        </dl>
        {ev.report_count && <p className="ws-wrap m-0 mt-3 text-[16px] text-ink-2">Report count: {ev.report_count.reason}.</p>}
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
          <p className="m-0 mt-1 text-[16px] text-ink-2">
            Claim gate (report count, recall count, quotes and recall excerpts shown): {ev.gate_totals.pass} passed,{' '}
            {ev.gate_totals.block} blocked.
            {ev.recomputed && ` Group counts recomputed from the listed reports: ${ev.recomputed.pass}.`}
          </p>
        )}
      </section>

      <section id="dev-patterns" aria-label="Patterns" className="scroll-mt-16 rounded-md border border-rule bg-surface p-4">
        <SectionTitle>
          Patterns in the reports · <span className="ms-num">{d.patterns.length}</span>
        </SectionTitle>
        {d.patterns.length === 0 ? (
          <p className="m-0 mt-2 text-ink-2" data-testid="no-patterns">
            No group of {2} or more reports matched. That is not a finding; a person should still read the reports.
          </p>
        ) : (
          <>
            <p className="m-0 mt-1 text-[16px] text-ink-2">Largest group first.</p>
            <ul className="m-0 mt-1 list-none p-0">
              {patterns.map((p) => (
                <Pattern key={p.id} p={p} />
              ))}
            </ul>
            {keyword && <p className="m-0 mt-2 text-[16px] leading-snug text-ink-2">{KEYWORD_CAPTION}</p>}
          </>
        )}
      </section>

      {rc && rc.latest.length > 0 && (
        <section aria-label="Recalls" className="rounded-md border border-rule bg-surface p-4">
          <SectionTitle>Latest recalls on this code</SectionTitle>
          <ul className="m-0 mt-2 list-none p-0">
            {rc.latest.map((r) => (
              <li key={r.recall_number} className="border-t border-rule py-3 first:border-t-0">
                <p className="ws-wrap m-0 font-semibold">
                  {r.recall_number} · {r.recalling_firm ?? 'firm not stored'}
                </p>
                <p className="m-0 text-[17px] text-ink-2">
                  {r.status ?? 'status not stored'} · initiated {day(r.date_initiated)}
                </p>
                {r.excerpt && (
                  <p className="ws-wrap m-0 mt-1 text-[17px]">
                    “{r.excerpt}
                    {r.excerpt_truncated ? '…' : ''}”
                  </p>
                )}
                {r.url && (
                  <a className="ws-wrap block min-h-11 py-2 text-[17px] text-accent underline" href={r.url} target="_blank" rel="noreferrer">
                    FDA recall page
                  </a>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

/** Your own device: move its status forward, see the K-number check, remove it. */
function MineControls({ d }: { d: CompanyDevice }) {
  const api = useMine()
  const [confirm, setConfirm] = useState(false)
  if (!api || !d.mine) return null
  const next = d.status ? nextStatuses(d.status.label) : []
  return (
    <div className="mt-3 border-t border-rule pt-3" data-testid="mine-controls">
      <p className="m-0 text-[17px]">
        K-number: <span className="ms-code !text-[17px]">{d.mine.k_number ?? 'none given'}</span>
        {d.mine.k_number ? <span data-testid="k-check"> · {d.mine.k_check}</span> : null}
      </p>
      {d.mine.note && (
        <p className="ws-wrap m-0 mt-1 text-[17px] text-ink-2" data-testid="device-note">
          {d.mine.note}
        </p>
      )}
      {next.length > 0 ? (
        <div className="mt-2" role="group" aria-label="Move the status forward">
          <p className="m-0 text-[16px] text-ink-2">A status only moves forward. It is set by you and kept in this browser.</p>
          <div className="mt-1 flex flex-wrap gap-2">
            {next.map((n) => (
              <button key={n} type="button" className="ms-btn ms-btn--secondary" style={{ height: 44 }} onClick={() => api.move(d.id, n)} data-testid="move-status">
                Move to {n}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <p className="m-0 mt-2 text-[16px] text-ink-2" data-testid="no-forward">This status cannot move forward.</p>
      )}
      {!confirm ? (
        <button type="button" className="mt-2 min-h-11 text-[17px] text-accent underline" onClick={() => setConfirm(true)} data-testid="remove-device">
          Remove this device
        </button>
      ) : (
        <p className="m-0 mt-2 text-[17px]">
          Remove it from your company?{' '}
          <button type="button" className="min-h-11 font-semibold text-accent underline" onClick={() => api.remove(d.id)} data-testid="remove-yes">
            Yes, remove
          </button>{' '}
          <button type="button" className="min-h-11 text-accent underline" onClick={() => setConfirm(false)}>
            Keep
          </button>
        </p>
      )}
    </div>
  )
}

function History({ d, chainOk, firstBad }: { d: CompanyDevice; chainOk: boolean | null; firstBad: number | null }) {
  return (
    <section id="dev-history" aria-label="Status history" className="scroll-mt-16 rounded-md border border-rule bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SectionTitle>
          Status history · <span className="ms-num">{d.history.length}</span>
        </SectionTitle>
        {chainOk === true && (
          <span className="ws-pill ws-pill--ring bg-success-soft text-success">
            <Icon name="check" size={16} /> Chain ok
          </span>
        )}
        {chainOk === false && <span className="ws-pill bg-critical text-[var(--on-critical)]">Chain broken at entry {firstBad}</span>}
      </div>
      <ol className="m-0 mt-2 list-none p-0" data-testid="history">
        {d.history.map((h) => (
          <li key={h.seq} className="border-t border-rule py-3 first:border-t-0">
            <p className="ws-wrap m-0 font-semibold">{h.from_status ? `${h.from_status} → ${h.to_status}` : `Registered as ${h.to_status}`}</p>
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
      <p className="m-0 mt-2 text-[16px] leading-snug text-ink-2">
        {d.mine
          ? 'These entries are kept only in this browser. They are not hash-chained.'
          : 'Each entry is chained to the one before it with a SHA-256 hash; the chain was recomputed when this page was built.'}
      </p>
    </section>
  )
}

/** Jump chips: stay at the top of the scrolling page and move to a section. */
function JumpNav({ items }: { items: { id: string; label: string }[] }) {
  return (
    <nav
      aria-label="Sections of this device"
      className="sticky -top-4 z-20 -mx-4 -mt-4 border-b border-rule bg-paper px-4 pb-2 pt-4 md:-top-6 md:-mx-8 md:-mt-6 md:px-8 md:pt-6"
      data-testid="jump-nav"
    >
      <ul className="m-0 flex list-none flex-wrap gap-2 p-0 max-sm:gap-1.5">
        {items.map((i) => (
          <li key={i.id}>
            <button
              type="button"
              className="min-h-11 rounded-xs border border-rule-strong bg-surface px-3 text-[17px] max-sm:px-2.5 max-sm:text-[16px] text-ink hover:bg-sunk"
              onClick={() => document.getElementById(i.id)?.scrollIntoView?.({ block: 'start', behavior: 'smooth' })}
            >
              {i.label}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  )
}

/** The separate "News and public web (unverified)" box for one product code (stored search first). */
function OutsideMentions({ code, terms }: { code: string; terms?: string[] }) {
  const { apiBase, mentionsFor } = useAlertPanel()
  return <MentionsBox code={code} terms={terms} apiBase={apiBase} stored={mentionsFor(code)} />
}

export function CompanyDeviceView({ company, device: d, onBack }: { company: Company; device: CompanyDevice; onBack: () => void }) {
  const tone: Tone = d.status ? toneOf(d.status.label) : 'neutral'
  const nav = [
    { id: 'dev-status', label: 'Status' },
    { id: 'dev-evidence', label: 'Evidence' },
    ...(d.evidence.available && d.patterns.length > 0 ? [{ id: 'dev-patterns', label: 'Patterns' }] : []),
    { id: 'dev-history', label: 'History' },
  ]
  return (
    <div className="space-y-4" data-testid="device-detail">
      <JumpNav items={nav} />
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
      <section id="dev-status" aria-label="Status" className={`scroll-mt-16 rounded-md border border-rule-strong p-4 ${CARD[tone]}`}>
        <SectionTitle>Status</SectionTitle>
        {d.status ? (
          <>
            <p className="m-0 mt-2">
              <StatusChip label={d.status.label} large />
            </p>
            <p className="ws-wrap m-0 mt-2 text-[17px] text-ink">
              Set by {d.status.set_by} on <span className="ms-num">{d.status.date}</span>
              {d.status.detail ? ` · ${d.status.detail}` : ''}
            </p>
          </>
        ) : (
          <p className="m-0 mt-2 text-ink-2">No status is stored.</p>
        )}
        <MineControls d={d} />
        {d.sweep && (
          <p className="ws-wrap m-0 mt-2 text-[17px] text-ink">
            AI device sweep, as of <span className="ms-num">{day(d.sweep.as_of)}</span>:{' '}
            {CLASS_LABEL[d.sweep.classification] ?? d.sweep.classification} ·{' '}
            <a className="text-accent underline" href={d.sweep.query_url} target="_blank" rel="noreferrer">
              openFDA query
            </a>
          </p>
        )}
      </section>
      <Evidence d={d} />
      <OutsideMentions code={d.product_code} terms={d.device_type.name ? [d.device_type.name] : undefined} />
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
  filter = null,
  onFilter,
  v2 = false,
}: {
  company: Company
  deviceId: string | null
  onDevice: (id: string) => void
  onBack: () => void
  filter?: string | null
  onFilter?: FilterFn
  v2?: boolean
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
  return d ? (
    <CompanyDeviceView company={company} device={d} onBack={onBack} />
  ) : (
    <CompanyList company={company} onDevice={onDevice} filter={filter} onFilter={onFilter} v2={v2} />
  )
}
