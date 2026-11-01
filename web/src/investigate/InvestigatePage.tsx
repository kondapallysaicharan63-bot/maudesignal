// "Investigate a complaint" (v2, /investigate): a product code and a few words about the device problem go to
// POST /v1/investigate, which answers from openFDA only (no model). The page shows the MAUDE reports for the product code
// (any maker) by month, verbatim quotes, reports not filed by a manufacturer, recalls and 510(k)s, and a plain-text
// "Evidence for the complaint file" to copy or download. Without an API address it shows one recorded run (code LLZ)
// and calls nothing. It does not decide reportability, similarity or CAPA need.
//
// URL contract: /investigate?code=XXX&device=<simulated device id> (both optional); see ./api.ts.
// The description lives in this component's state only: not in the address, storage, a cookie or any log.
import { useMemo, useRef, useState, type ReactNode } from 'react'
import example from '../fixtures/investigateExample.json'
import { Icon } from '../icons'
import {
  AS_ENTERED,
  BANNER,
  evidenceFileName,
  evidenceText,
  investigate,
  MAX_DESCRIPTION,
  MIN_DESCRIPTION,
  NOTICE,
  parseInvestigation,
  sourceName,
  stamp,
  type Fetcher,
  type Investigation,
  type Outcome,
} from './api'
import { hrefFor } from '../v2/router'
import './investigate.css'

const RECORDED = parseInvestigation((example as { answer: unknown }).answer)
const RECORDED_INPUT = (example as { input: { product_code: string; description: string } }).input

const fmt = (x: number): string => x.toLocaleString('en-US')
const day = (s: string | null): string => (s && /^\d{8}$/.test(s) ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}` : (s ?? 'date not stated'))
const KEY_SENTENCE = 'MaudeSignal does not decide reportability, similarity, or whether a CAPA is needed; your team does.'

/** A number that opens the openFDA query behind it. A zero or a number without a usable link is plain text. */
function Figure({ value, url, label }: { value: number; url: string; label: string }) {
  return url && value > 0 ? (
    <a className="ms2-a ms-num" href={url} target="_blank" rel="noreferrer" aria-label={`${fmt(value)} ${label}, open the openFDA query`}>
      {fmt(value)}
    </a>
  ) : (
    <span className="ms-num">{fmt(value)}</span>
  )
}

/** "Real FDA data · retrieved ..." or "Recorded example · stored copy of ...", repeated on every section. */
function Badge({ a }: { a: Investigation }) {
  return a.mode === 'recorded' ? (
    <p className="ms2-inv-badge" data-testid="inv-badge">
      <span className="ms2-tag">Recorded example</span> stored copy of {a.retrieved_date}
    </p>
  ) : (
    <p className="ms2-inv-badge" data-testid="inv-badge">
      <span className="ms2-tag">Real FDA data</span> retrieved {stamp(a.retrieved_utc)}
    </p>
  )
}

function Months({ a }: { a: Investigation }) {
  const [allMonths, setAllMonths] = useState(false)
  const zeros = a.months.filter((m) => m.code_wide === 0).length
  const max = Math.max(1, ...a.months.map((m) => m.code_wide))
  const kw = a.total_keyword_matched
  return (
    <>
      <div className="ms2-inv-two ms2-inv-figs">
        <div className="ms2-inv-fig" data-testid="inv-total-code">
          <p className="ms2-inv-figlabel">All reports for {a.product_code}, 12 months</p>
          <p className="ms2-inv-bigfig">
            <Figure value={a.total_code_wide.value} url={a.total_code_wide.url} label="reports for the product code" />
          </p>
        </div>
        <div className="ms2-inv-fig ms2-inv-fig--kw" data-testid="inv-total-kw">
          <p className="ms2-inv-figlabel">&hellip;of those, the narrative mentions a keyword</p>
          <p className="ms2-inv-bigfig">
            {kw ? <Figure value={kw.value} url={kw.url} label="reports that mention a keyword" /> : <span className="ms2-muted text-[15px]">no keywords</span>}
          </p>
        </div>
      </div>
      <p className="ms2-inv-meta m-0 mt-3" data-testid="inv-keywords">
        {a.keywords.length > 0 ? (
          <>
            Keywords taken from your description (a text match, not a finding of similarity):{' '}
            {a.keywords.map((k) => (
              <span key={k} className="ms2-tag mr-1">
                {k}
              </span>
            ))}
          </>
        ) : (
          'The description had no content words to match, so only the count for the whole product code is shown.'
        )}
      </p>
      <details className="mt-1">
        <summary className="ms2-smalllink cursor-pointer">How keywords are chosen</summary>
        <p className="ms2-inv-meta m-0 mt-1">{a.keyword_rule}</p>
      </details>
      {a.total_code_wide.value > 0 && (
      <ul className="ms2-inv-legend" aria-label="Chart key">
        <li>
          <span className="ms2-bar ms2-bar--base ms2-inv-swatch" aria-hidden="true" /> All reports for the product code
        </li>
        <li>
          <span className="ms2-bar ms2-bar--now ms2-inv-swatch" aria-hidden="true" /> Narrative mentions a keyword
        </li>
      </ul>
      )}
      {a.total_code_wide.value === 0 && (
        <p className="ms2-inv-meta m-0 mt-2" data-testid="inv-zero-hint">
          No reports for this product code in these 12 months. Check the product code or widen the wording.
        </p>
      )}
      {a.total_code_wide.value > 0 && a.total_keyword_matched && a.total_keyword_matched.value === 0 && (
        <p className="ms2-inv-meta m-0 mt-2" data-testid="inv-zero-hint">
          No narrative mentions these keywords. Widen the wording.
        </p>
      )}
      <div className="ms2-inv-scroll">
        <table className={`ms2-table${allMonths ? ' is-all' : ''}`} data-testid="inv-months">
          <caption className="ms2-inv-caption">
            Reports received per month, last 12 months.<span className="ms2-inv-barsonly"> The table is the text version of the bars.</span>
          </caption>
          <thead>
            <tr>
              <th scope="col">Month</th>
              <th scope="col" className="ms2-num">
                All reports
              </th>
              <th scope="col" className="ms2-num">
                Keyword
              </th>
              <th scope="col" className="ms2-inv-barcol">
                <span className="sr-only">Bars</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {a.months.map((m) => (
              <tr key={m.month} data-testid={`inv-month-${m.month}`} className={m.code_wide === 0 ? 'ms2-inv-zero' : undefined}>
                <th scope="row">
                  {m.month}
                  {m.partial && <span className="ms2-muted"> (partial)</span>}
                </th>
                <td className="ms2-num">
                  <Figure value={m.code_wide} url={m.code_wide_url} label={`reports in ${m.month}, whole product code`} />
                </td>
                <td className="ms2-num">
                  {m.keyword_matched === null ? (
                    <span className="ms2-muted">-</span>
                  ) : (
                    <Figure value={m.keyword_matched} url={m.keyword_url ?? ''} label={`reports in ${m.month} that mention a keyword`} />
                  )}
                </td>
                <td className="ms2-inv-barcol" aria-hidden="true" data-bars={`${m.month}: ${m.code_wide} all reports${m.keyword_matched === null ? '' : `, ${m.keyword_matched} keyword`}`}>
                  <span className="ms2-bars">
                    {m.code_wide > 0 && (
                      <span className="ms2-inv-barrow">
                        <span className="ms2-bar ms2-bar--base" style={{ width: `${(m.code_wide / max) * 80}%` }} />
                        <span className="ms2-inv-barval">{fmt(m.code_wide)}</span>
                      </span>
                    )}
                    {m.keyword_matched !== null && m.keyword_matched > 0 && (
                      <span className="ms2-inv-barrow">
                        <span className="ms2-bar ms2-bar--now" style={{ width: `${(m.keyword_matched / max) * 80}%` }} />
                        <span className="ms2-inv-barval">{fmt(m.keyword_matched)}</span>
                      </span>
                    )}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {zeros > 0 && zeros < a.months.length && (
        <button type="button" className="ms2-link ms2-inv-allmonths" onClick={() => setAllMonths((v) => !v)} aria-expanded={allMonths} data-testid="inv-allmonths">
          {allMonths ? 'Show only months with reports' : `Show all ${a.months.length} months`}
        </button>
      )}
      <p className="ms2-inv-meta m-0 mt-2">
        The two counts answer different questions and are never added. Months with no reports are dimmed and not linked. {a.lag_note}
      </p>
    </>
  )
}

function Quotes({ a }: { a: Investigation }) {
  return (
    <div className="mt-4" data-testid="inv-quotes">
      <h3 className="ms2-h3">Quotes from report narratives</h3>
      <p className="ms2-inv-meta m-0 mb-2">Text as filed, not edited (older reports are often in capitals). Each was checked against its own report.</p>
      {a.quotes.length === 0 ? (
        <p className="ms2-inv-meta m-0">No narrative sentence passed the checks, so none is shown.</p>
      ) : (
        <ul className="ms2-inv-quotes">
          {a.quotes.map((q) => (
            <li key={q.mdr_report_key} data-testid="inv-quote">
              <blockquote className="m-0">
                &ldquo;{q.quote}&rdquo;{q.truncated ? ' …' : ''}
              </blockquote>
              <p className="ms2-inv-meta m-0 mt-1">
                Report <span className="ms-num">{q.report_number ?? q.mdr_report_key}</span> · received {day(q.date_received)} · filed by{' '}
                {sourceName(q.source)}
                {q.maker ? ` · maker as written: ${q.maker}` : ''} · checked: {q.gate} in this report
                {q.url && (
                  <>
                    {' · '}
                    <a className="ms2-a" href={q.url} target="_blank" rel="noreferrer">
                      open the report query
                    </a>
                  </>
                )}
              </p>
            </li>
          ))}
        </ul>
      )}
      {a.quotes.length > 0 && (
        <p className="ms2-inv-meta m-0 mt-2" data-testid="inv-own-maker">
          {a.own_maker_note}
        </p>
      )}
    </div>
  )
}

function Sources({ a }: { a: Investigation }) {
  const s = a.sources
  if (!s) return <p className="ms2-inv-meta m-0">Who filed the reports could not be read this time.</p>
  const n = s.non_manufacturer.value
  const total = a.total_code_wide.value
  return (
    <>
      <p className="m-0 text-[17px]" data-testid="inv-nonmfr">
        {n > 0 ? (
          <>
            <strong>
              <Figure value={n} url={s.non_manufacturer.url} label="reports not filed by a manufacturer" />
            </strong>{' '}
            of <span className="ms-num">{fmt(total)}</span> reports in these 12 months were not filed by a manufacturer.
          </>
        ) : s.manufacturer_count === total && total > 0 ? (
          <>
            None of the <span className="ms-num">{fmt(total)}</span> reports in these 12 months was filed by anyone but a manufacturer. All{' '}
            <span className="ms-num">{fmt(total)}</span> were manufacturer reports.
          </>
        ) : (
          <>None of the reports with a filer type on them was filed by anyone but a manufacturer.</>
        )}
      </p>
      <ul className="ms2-inv-plain mt-2">
        {s.buckets.map((b) => (
          <li key={b.source}>
            {b.source}: <span className="ms-num">{fmt(b.count)}</span>
          </li>
        ))}
        {s.no_source_count > 0 && (
          <li>
            No filer type on the report: <span className="ms-num">{fmt(s.no_source_count)}</span>
          </li>
        )}
      </ul>
      {s.buckets_url && (
        <p className="m-0 mt-1 text-[15px]">
          <a className="ms2-a" href={s.buckets_url} target="_blank" rel="noreferrer">
            openFDA query: reports by filer type
          </a>
        </p>
      )}
      {s.reports.length > 0 && (
        <>
          <h3 className="ms2-h3 mt-3">Newest of these reports</h3>
          <ul className="ms2-inv-plain">
            {s.reports.map((r) => (
              <li key={r.mdr_report_key}>
                Report <span className="ms-num">{r.report_number ?? r.mdr_report_key}</span> · {day(r.date_received)} · {sourceName(r.source)}
                {r.maker ? ` · ${r.maker}` : ''}
                {r.url && (
                  <>
                    {' · '}
                    <a className="ms2-a" href={r.url} target="_blank" rel="noreferrer">
                      open
                    </a>
                  </>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      {s.note && <p className="ms2-inv-meta m-0 mt-2">{s.note}</p>}
    </>
  )
}

/** Recalls with the same reason text are shown under that text once. */
function groupByReason<T extends { reason: string }>(items: T[]): { reason: string; items: T[] }[] {
  const out: { reason: string; items: T[] }[] = []
  for (const it of items) {
    const g = out.find((x) => x.reason === it.reason)
    if (g) g.items.push(it)
    else out.push({ reason: it.reason, items: [it] })
  }
  return out
}

function Related({ a }: { a: Investigation }) {
  const { recalls, clearances } = a
  return (
    <div className="ms2-inv-two">
      <div data-testid="inv-recalls">
        <h3 className="ms2-h3">Recalls</h3>
        {recalls.total ? (
          <>
            <p className="m-0">
              <Figure value={recalls.total.value} url={recalls.total.url} label="recall records" /> recall records for this product code, all dates.
              Newest:
            </p>
            {groupByReason(recalls.items).map((g) => (
              <div key={g.reason + g.items[0].recall_number} className="mt-2" data-testid="inv-recall-group">
                {g.reason && (
                  <p className="ms2-inv-meta m-0">
                    {g.reason}
                    {g.items.length > 1 && <strong> (×{g.items.length}, same reason)</strong>}
                  </p>
                )}
                <ul className="ms2-inv-plain mt-1">
                  {g.items.map((r) => (
                    <li key={r.recall_number}>
                      <span className="ms-num">{r.recall_number}</span> · {r.firm ?? 'firm not stated'} · {r.status ?? 'status not stated'} · started{' '}
                      {r.date_initiated ?? 'date not stated'}{' '}
                      {r.url && (
                        <a className="ms2-a" href={r.url} target="_blank" rel="noreferrer" aria-label={`Full record of recall ${r.recall_number} on openFDA`}>
                          Full record
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            <p className="ms2-inv-meta m-0 mt-1">Numbers and dates are as filed with FDA.</p>
          </>
        ) : (
          <p className="ms2-inv-meta m-0">{recalls.note ?? 'Could not be read this time.'}</p>
        )}
      </div>
      <div data-testid="inv-clearances">
        <h3 className="ms2-h3">510(k)s</h3>
        {clearances.total ? (
          <>
            <p className="m-0">
              <Figure value={clearances.total.value} url={clearances.total.url} label="510(k) records" /> 510(k) records for this product code, all
              dates. Newest decisions:
            </p>
            <ul className="ms2-inv-plain mt-1">
              {clearances.items.map((c) => (
                <li key={c.k_number}>
                  <a className="ms2-a" href={c.url || undefined} target="_blank" rel="noreferrer">
                    {c.k_number}
                  </a>{' '}
                  · {c.device_name}
                  {c.applicant ? ` · ${c.applicant}` : ''} · decision {c.decision_date ?? 'date not stated'}
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="ms2-inv-meta m-0">{clearances.note ?? 'Could not be read this time.'}</p>
        )}
      </div>
    </div>
  )
}

/** Copy to the clipboard; false when the browser refuses (the text is then selected for Ctrl+C). */
async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

function Evidence({ a, description }: { a: Investigation; description: string }) {
  const text = useMemo(() => evidenceText(a, description), [a, description])
  const lines = useMemo(() => text.split('\n').length, [text])
  const pre = useRef<HTMLPreElement>(null)
  const [copied, setCopied] = useState<'idle' | 'ok' | 'manual'>('idle')
  const [all, setAll] = useState(false)
  const copy = async () => {
    if (await copyText(text)) setCopied('ok')
    else {
      setCopied('manual')
      setAll(true)
      window.setTimeout(() => {
        const el = pre.current
        if (!el) return
        const range = document.createRange()
        range.selectNodeContents(el)
        const sel = window.getSelection()
        sel?.removeAllRanges()
        sel?.addRange(range)
      }, 0)
    }
  }
  const download = () => {
    const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = evidenceFileName(a)
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  const [lead] = NOTICE.split(KEY_SENTENCE)
  return (
    <section className="ms2-card" id="inv-evidence" aria-labelledby="inv-evidence-h" data-testid="inv-evidence">
      <h2 id="inv-evidence-h" className="ms2-h2">
        Evidence for the complaint file
      </h2>
      <Badge a={a} />
      <p className="m-0 mt-2 text-[15px]" data-testid="inv-notice">
        {lead}
        <strong>{KEY_SENTENCE}</strong>
      </p>
      <p className="ms2-inv-meta m-0 mt-1">Plain text to paste into your complaint record. Your description is printed in it {AS_ENTERED}.</p>
      <div className="ms2-inv-actions">
        <button type="button" className="ms-btn ms-btn--primary" onClick={() => void copy()} data-testid="inv-copy">
          Copy
        </button>
        <button type="button" className="ms-btn" onClick={download} data-testid="inv-download">
          Download .txt
        </button>
        <span role="status" className="ms2-inv-meta" data-testid="inv-copy-status">
          {copied === 'ok' ? 'Copied.' : copied === 'manual' ? 'Your browser blocked copying. The text is selected: press Ctrl+C.' : ''}
        </span>
      </div>
      <pre ref={pre} className={`ms2-inv-evidence${all ? ' is-open' : ''}`} tabIndex={0} aria-label="Evidence text" data-testid="inv-evidence-text">
        {text}
      </pre>
      <button type="button" className="ms2-link" onClick={() => setAll((v) => !v)} aria-expanded={all} data-testid="inv-evidence-toggle">
        {all ? 'Show less' : `Show all ${fmt(lines)} lines`}
      </button>
    </section>
  )
}

function Section({ id, title, a, children }: { id: string; title: string; a: Investigation; children: ReactNode }) {
  return (
    <section className="ms2-card" id={id} aria-labelledby={`${id}-h`} data-testid={id}>
      <h2 id={`${id}-h`} className="ms2-h2">
        {title}
      </h2>
      <Badge a={a} />
      <div className="mt-2">{children}</div>
    </section>
  )
}

const JUMPS: [string, string][] = [
  ['inv-similar', 'Reports'],
  ['inv-sources', 'Not filed by a manufacturer'],
  ['inv-related', 'Recalls and 510(k)s'],
  ['inv-evidence', 'Evidence'],
]

function Results({ a, description }: { a: Investigation; description: string }) {
  return (
    <div className="ms2-inv-results" data-testid="inv-results">
      <p className="m-0 text-[17px]" data-testid="inv-device">
        <strong>{a.product_code}</strong>
        {a.device_type_name ? <> · {a.device_type_name}</> : <span className="ms2-muted"> · FDA device type name not available</span>}
      </p>
      {a.notes.map((n) => (
        <p key={n} className="ms-banner ms-banner--info m-0" role="note" data-testid="inv-note">
          {n}
        </p>
      ))}
      <Section id="inv-similar" title="MAUDE reports for this product code (any maker)" a={a}>
        <p className="ms2-inv-meta m-0 mb-1">With a second count for reports whose narrative mentions your keywords.</p>
        <Months a={a} />
        <Quotes a={a} />
      </Section>
      <Section id="inv-sources" title="Reports not filed by a manufacturer" a={a}>
        <p className="ms2-inv-meta m-0 mb-2">User facilities, voluntary reporters and distributors. A maker may not see these in its own complaint system.</p>
        <Sources a={a} />
      </Section>
      <Section id="inv-related" title="Recalls and 510(k)s for this product code" a={a}>
        <Related a={a} />
      </Section>
      <Evidence a={a} description={description} />
      <p className="ms2-muted m-0 text-[15px]" data-testid="inv-attach">
        Attach to the complaint file / known-effects record. MaudeSignal never decides reportability.
      </p>
    </div>
  )
}

function jump(id: string) {
  const el = document.getElementById(id)
  if (!el) return
  el.scrollIntoView({ behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' })
  const h = el.querySelector<HTMLElement>('h2')
  if (h) {
    h.setAttribute('tabindex', '-1')
    h.focus({ preventScroll: true })
  }
}

export function InvestigatePage({
  apiBase,
  code: initialCode,
  device,
  fetcher,
  onCheckDevice,
}: {
  /** Origin of the MaudeSignal API; null shows the one recorded run and calls nothing. */
  apiBase: string | null
  code?: string
  /** Id of a simulated device the address came from (shown, never sent). */
  device?: string
  fetcher?: Fetcher
  /** Opens "Check any device type" (a plain link is used when absent). */
  onCheckDevice?: () => void
}) {
  const live = apiBase !== null
  const [code, setCode] = useState(live ? (initialCode ?? '').replace(/[^a-zA-Z]/g, '').slice(0, 3).toUpperCase() : RECORDED_INPUT.product_code)
  const [description, setDescription] = useState(live ? '' : RECORDED_INPUT.description)
  const [busy, setBusy] = useState(false)
  const [out, setOut] = useState<Outcome | null>(null)
  const [asked, setAsked] = useState('')
  const [editing, setEditing] = useState(false)
  const errRef = useRef<HTMLParagraphElement>(null)
  const ready = code.length === 3 && description.trim().length >= MIN_DESCRIPTION
  const why = code.length !== 3 ? 'Enter the three-letter product code.' : `Describe the problem in at least ${MIN_DESCRIPTION} characters.`
  const ran = out?.ok === true || !live
  const collapsed = ran && !editing
  const run = async () => {
    if (!live || busy || !ready) return
    setBusy(true)
    setOut(null)
    const desc = description.trim()
    const o = await investigate(code, desc, { fetcher: fetcher ?? ((u, init) => fetch(u, init)), apiBase })
    setAsked(desc)
    setOut(o)
    setEditing(!o.ok)
    setBusy(false)
    if (!o.ok) window.setTimeout(() => errRef.current?.scrollIntoView?.({ block: 'center', behavior: 'auto' }), 0)
  }
  const shown = !live ? RECORDED_INPUT.description : asked
  const summary = shown.length > 90 ? `${shown.slice(0, 90).trimEnd()}…` : shown
  return (
    <div className="ms2-inv" data-testid="investigate-page">
      <header className="ms2-pagehead">
        <h1 className="ms2-h1">Investigate a complaint</h1>
        <p className="ms2-lead">
          Check a complaint against what FDA already holds for the device type. Everything below comes from public FDA data, each number has its
          openFDA query, and no AI model is used. It is made for the complaints team: the evidence it produces feeds the
          company's known-effects record.
        </p>
      </header>
      <p className={`ms-banner ms-banner--warn ms2-inv-banner${collapsed ? ' ms2-inv-banner--after' : ''}`} role="note" data-testid="inv-banner">
        <Icon name="warn" size={20} />
        <span>{BANNER}</span>
      </p>
      {!live && (
        <p className="ms-banner ms-banner--info" role="note" data-testid="inv-recorded-note">
          <span>
            <strong>Recorded example.</strong> This site is not connected to the live service, so nothing you type would be searched. Below is one
            stored run for product code LLZ.
          </span>
        </p>
      )}
      {device && (
        <p className="ms2-inv-meta m-0" data-testid="inv-device-note">
          From the simulated device <code>{device}</code> (a fictional device; its id is not sent anywhere).
        </p>
      )}
      {collapsed ? (
        <div className="ms2-inv-summary" data-testid="inv-summary">
          <p className="m-0">
            <strong>{code}</strong> · <span data-testid="inv-summary-text">{summary}</span>
          </p>
          {live && (
            <button type="button" className="ms-btn ms-btn--sm" onClick={() => setEditing(true)} data-testid="inv-edit">
              Edit
            </button>
          )}
        </div>
      ) : (
        <form
          className="ms2-inv-form"
          onSubmit={(e) => {
            e.preventDefault()
            void run()
          }}
          aria-label="Complaint details"
        >
          <div className="ms2-inv-field">
            <label htmlFor="inv-code" className="ms2-inv-label">
              Product code
            </label>
            <input
              id="inv-code"
              data-testid="inv-code"
              className="ms2-inv-input ms2-inv-code"
              value={code}
              readOnly={!live}
              onChange={(e) => setCode(e.target.value.replace(/[^a-zA-Z]/g, '').slice(0, 3).toUpperCase())}
              maxLength={3}
              autoComplete="off"
              autoCapitalize="characters"
              spellCheck={false}
              placeholder="e.g. LLZ"
              aria-describedby="inv-code-hint"
            />
            <span id="inv-code-hint" className="ms2-inv-hint">
              Three letters. Not sure of the code?{' '}
              <a
                className="ms2-a"
                href={hrefFor({ page: 'workflow', id: 'check-device' })}
                data-testid="inv-check-link"
                onClick={(e) => {
                  if (onCheckDevice) {
                    e.preventDefault()
                    onCheckDevice()
                  }
                }}
              >
                Check any device type
              </a>
            </span>
          </div>
          <div className="ms2-inv-field ms2-inv-grow">
            <label htmlFor="inv-desc" className="ms2-inv-label">
              What went wrong with the device
            </label>
            <textarea
              id="inv-desc"
              data-testid="inv-desc"
              className="ms2-inv-input ms2-inv-text"
              rows={4}
              value={description}
              readOnly={!live}
              maxLength={MAX_DESCRIPTION}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="A few words about the problem with the device. No patient details."
              aria-describedby={out && !out.ok ? 'inv-desc-hint inv-error' : 'inv-desc-hint'}
              aria-invalid={out && !out.ok && out.kind === 'patient_data' ? true : undefined}
            />
            <span id="inv-desc-hint" className="ms2-inv-hint">
              <span className="ms-num" data-testid="inv-count">
                {description.length}
              </span>{' '}
              of {MAX_DESCRIPTION} characters. Used once to pick keywords for the search; not stored.
            </span>
            {out && !out.ok && (
              <p
                ref={errRef}
                id="inv-error"
                role="alert"
                className={`ms-banner ${out.kind === 'patient_data' ? 'ms-banner--warn' : 'ms-banner--err'} ms2-inv-error`}
                data-testid={`inv-error-${out.kind}`}
              >
                {out.message}
              </p>
            )}
          </div>
          {live && (
            <div className="ms2-inv-submit">
              <button
                type="submit"
                className={`ms-btn ${ran ? '' : 'ms-btn--primary'}`}
                disabled={busy || !ready}
                aria-describedby={ready ? undefined : 'inv-why'}
                data-testid="inv-run"
              >
                {busy ? 'Searching openFDA…' : ran ? 'Run again' : 'Investigate'}
              </button>
              {!ready && !busy && (
                <span id="inv-why" className="ms2-inv-hint" data-testid="inv-why">
                  {why}
                </span>
              )}
            </div>
          )}
        </form>
      )}
      {ran && out?.ok !== false && (
        <nav className="ms2-inv-jumps" aria-label="Jump to a section" data-testid="inv-jumps">
          {JUMPS.map(([id, label]) => (
            <button key={id} type="button" className="ms2-smalllink" onClick={() => jump(id)}>
              {label}
            </button>
          ))}
        </nav>
      )}
      <div>
        {busy && (
          <p className="ms2-muted" role="status" data-testid="inv-busy">
            Asking openFDA. This can take up to 30 seconds.
          </p>
        )}
      </div>
      {live && out?.ok && <Results a={out.answer} description={asked} />}
      {!live && RECORDED && <Results a={RECORDED} description={RECORDED_INPUT.description} />}
    </div>
  )
}
