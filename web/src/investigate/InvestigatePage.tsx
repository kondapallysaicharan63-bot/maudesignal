// "Investigate a complaint" (v2, /investigate): a product code and a few words about the device problem go to
// POST /v1/investigate, which answers from openFDA only (no model). The page shows similar MAUDE events at other makers by
// month, verbatim quotes, reports not filed by a manufacturer, recalls and 510(k)s, and a plain-text "Evidence for the
// complaint file" to copy or download. Without an API address it shows one recorded run (code LLZ) and calls nothing.
//
// URL contract: /investigate?code=XXX&device=<simulated device id> (both optional); see ./api.ts.
// The description lives in this component's state only: not in the address, storage, a cookie or any log.
import { useMemo, useRef, useState } from 'react'
import example from '../fixtures/investigateExample.json'
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
import './investigate.css'

const RECORDED = parseInvestigation((example as { answer: unknown }).answer)
const RECORDED_INPUT = (example as { input: { product_code: string; description: string } }).input

const fmt = (x: number): string => x.toLocaleString('en-US')
const day = (s: string | null): string => (s && /^\d{8}$/.test(s) ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}` : (s ?? 'date not stated'))

/** A number that opens the openFDA query behind it (plain text when the answer carried no usable link). */
function Figure({ value, url, label }: { value: number; url: string; label: string }) {
  return url ? (
    <a className="ms2-a ms-num" href={url} target="_blank" rel="noreferrer" aria-label={`${fmt(value)} ${label}, open the openFDA query`}>
      {fmt(value)}
    </a>
  ) : (
    <span className="ms-num">{fmt(value)}</span>
  )
}

function Provenance({ a }: { a: Investigation }) {
  return a.mode === 'recorded' ? (
    <p className="ms2-inv-prov" data-testid="inv-provenance">
      <span className="ms2-tag">Recorded example</span> <span>{a.source_note}</span>
    </p>
  ) : (
    <p className="ms2-inv-prov" data-testid="inv-provenance">
      <span className="ms2-tag">Real FDA data</span> <span>Retrieved from openFDA on {stamp(a.retrieved_utc)}.</span>
    </p>
  )
}

function Months({ a }: { a: Investigation }) {
  const max = Math.max(1, ...a.months.map((m) => m.code_wide))
  const kw = a.total_keyword_matched
  return (
    <>
      <dl className="ms2-stats ms2-inv-stats">
        <div>
          <dt>Whole product code, 12 months</dt>
          <dd data-testid="inv-total-code">
            <Figure value={a.total_code_wide.value} url={a.total_code_wide.url} label="reports for the product code" />
          </dd>
        </div>
        <div>
          <dt>Narrative mentions a keyword</dt>
          <dd data-testid="inv-total-kw">
            {kw ? <Figure value={kw.value} url={kw.url} label="reports that mention a keyword" /> : <span className="ms2-muted text-[15px]">no keywords</span>}
          </dd>
        </div>
      </dl>
      <p className="ms2-muted m-0 mt-2 text-[15px]" data-testid="inv-keywords">
        {a.keywords.length > 0 ? (
          <>
            Keywords from the description:{' '}
            {a.keywords.map((k) => (
              <span key={k} className="ms2-tag mr-1">
                {k}
              </span>
            ))}
          </>
        ) : (
          'The description had no content words to match, so only the whole-code count is shown.'
        )}
      </p>
      <details className="mt-1">
        <summary className="ms2-smalllink cursor-pointer">How keywords are chosen</summary>
        <p className="ms2-muted m-0 mt-1 text-[15px]">{a.keyword_rule}</p>
      </details>
      <div className="ms2-inv-scroll mt-3">
        <table className="ms2-table" data-testid="inv-months">
          <caption className="sr-only">Reports received per month, whole product code and keyword-matched, last 12 months</caption>
          <thead>
            <tr>
              <th scope="col">Month</th>
              <th scope="col" className="ms2-num">
                Whole code
              </th>
              <th scope="col" className="ms2-num">
                Keyword
              </th>
              <th scope="col" className="ms2-inv-barcol" aria-hidden="true" />
            </tr>
          </thead>
          <tbody>
            {a.months.map((m) => (
              <tr key={m.month} data-testid={`inv-month-${m.month}`}>
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
                <td className="ms2-inv-barcol" aria-hidden="true">
                  <span className="ms2-bars">
                    <span className="ms2-bar ms2-bar--base" style={{ width: `${(m.code_wide / max) * 100}%` }} />
                    {m.keyword_matched !== null && <span className="ms2-bar ms2-bar--now" style={{ width: `${(m.keyword_matched / max) * 100}%` }} />}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="ms2-muted m-0 mt-2 text-[15px]">
        The two counts are different questions and are never added: the first is every report for the product code, the second is the
        part of it whose narrative mentions at least one keyword. {a.lag_note}
      </p>
    </>
  )
}

function Quotes({ a }: { a: Investigation }) {
  return (
    <div className="mt-4" data-testid="inv-quotes">
      <h3 className="ms2-h3">Quotes from report narratives</h3>
      {a.quotes.length === 0 ? (
        <p className="ms2-muted m-0 text-[15px]">No narrative sentence passed the checks, so none is shown.</p>
      ) : (
        <ul className="ms2-inv-quotes">
          {a.quotes.map((q) => (
            <li key={q.mdr_report_key} data-testid="inv-quote">
              <blockquote className="m-0">
                &ldquo;{q.quote}&rdquo;{q.truncated ? ' …' : ''}
              </blockquote>
              <p className="ms2-muted m-0 mt-1 text-[15px]">
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
      <p className="ms2-muted m-0 mt-2 text-[15px]" data-testid="inv-own-maker">
        {a.own_maker_note}
      </p>
    </div>
  )
}

function Sources({ a }: { a: Investigation }) {
  const s = a.sources
  if (!s) return <p className="ms2-muted m-0">Who filed the reports could not be read just now.</p>
  return (
    <>
      <p className="m-0 text-[17px]" data-testid="inv-nonmfr">
        <strong>
          <Figure value={s.non_manufacturer.value} url={s.non_manufacturer.url} label="reports not filed by a manufacturer" />
        </strong>{' '}
        of <span className="ms-num">{fmt(a.total_code_wide.value)}</span> reports in these 12 months were not filed by a manufacturer.
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
      {s.note && <p className="ms2-muted m-0 mt-2 text-[15px]">{s.note}</p>}
    </>
  )
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
            <ul className="ms2-inv-plain mt-1">
              {recalls.items.map((r) => (
                <li key={r.recall_number}>
                  <a className="ms2-a" href={r.url || undefined} target="_blank" rel="noreferrer">
                    {r.recall_number}
                  </a>{' '}
                  · {r.firm ?? 'firm not stated'} · {r.status ?? 'status not stated'} · started {r.date_initiated ?? 'date not stated'}
                  {r.reason && <span className="ms2-muted block text-[15px]">{r.reason}</span>}
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="ms2-muted m-0">{recalls.note ?? 'Could not be read just now.'}</p>
        )}
      </div>
      <div data-testid="inv-clearances">
        <h3 className="ms2-h3">510(k) clearances</h3>
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
          <p className="ms2-muted m-0">{clearances.note ?? 'Could not be read just now.'}</p>
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
  const pre = useRef<HTMLPreElement>(null)
  const [copied, setCopied] = useState<'idle' | 'ok' | 'manual'>('idle')
  const copy = async () => {
    if (await copyText(text)) setCopied('ok')
    else {
      setCopied('manual')
      const el = pre.current
      if (el) {
        const range = document.createRange()
        range.selectNodeContents(el)
        const sel = window.getSelection()
        sel?.removeAllRanges()
        sel?.addRange(range)
      }
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
  return (
    <section className="ms2-card" aria-labelledby="inv-evidence-h" data-testid="inv-evidence">
      <h2 id="inv-evidence-h" className="ms2-h2">
        Evidence for the complaint file
      </h2>
      <p className="ms2-muted m-0 mt-1 text-[15px]">
        Plain text to paste into your complaint record. Your description is printed in it {AS_ENTERED}.
      </p>
      <div className="ms2-inv-actions">
        <button type="button" className="ms-btn ms-btn--primary" onClick={() => void copy()} data-testid="inv-copy">
          Copy
        </button>
        <button type="button" className="ms-btn" onClick={download} data-testid="inv-download">
          Download .txt
        </button>
        <span role="status" className="ms2-muted text-[15px]" data-testid="inv-copy-status">
          {copied === 'ok' ? 'Copied.' : copied === 'manual' ? 'Your browser blocked copying. The text is selected: press Ctrl+C.' : ''}
        </span>
      </div>
      <pre ref={pre} className="ms2-inv-evidence" tabIndex={0} aria-label="Evidence text" data-testid="inv-evidence-text">
        {text}
      </pre>
      <p className="m-0 mt-3 text-[15px]" data-testid="inv-notice">
        {NOTICE}
      </p>
    </section>
  )
}

function Results({ a, description }: { a: Investigation; description: string }) {
  return (
    <div className="ms2-inv-results" data-testid="inv-results">
      <Provenance a={a} />
      <p className="m-0 text-[17px]" data-testid="inv-device">
        <strong>{a.product_code}</strong>
        {a.device_type_name ? <> · {a.device_type_name}</> : <span className="ms2-muted"> · FDA device type name not available</span>}
      </p>
      {a.notes.map((n) => (
        <p key={n} className="ms-banner ms-banner--info m-0" role="note">
          {n}
        </p>
      ))}
      <section className="ms2-card" aria-labelledby="inv-similar-h" data-testid="inv-similar">
        <h2 id="inv-similar-h" className="ms2-h2">
          Similar MAUDE events at other makers
        </h2>
        <Months a={a} />
        <Quotes a={a} />
      </section>
      <section className="ms2-card" aria-labelledby="inv-sources-h" data-testid="inv-sources">
        <h2 id="inv-sources-h" className="ms2-h2">
          Reports not filed by a manufacturer
        </h2>
        <p className="ms2-muted m-0 mt-1 mb-2 text-[15px]">
          User facilities, voluntary reporters and distributors. A maker may not see these in its own complaint system.
        </p>
        <Sources a={a} />
      </section>
      <section className="ms2-card" aria-labelledby="inv-related-h">
        <h2 id="inv-related-h" className="ms2-h2">
          Related recalls and 510(k)s
        </h2>
        <Related a={a} />
      </section>
      <Evidence a={a} description={description} />
    </div>
  )
}

export function InvestigatePage({
  apiBase,
  code: initialCode,
  device,
  fetcher,
}: {
  /** Origin of the MaudeSignal API; null shows the one recorded run and calls nothing. */
  apiBase: string | null
  code?: string
  /** Id of a simulated device the address came from (shown, never sent). */
  device?: string
  fetcher?: Fetcher
}) {
  const live = apiBase !== null
  const [code, setCode] = useState(live ? (initialCode ?? '').replace(/[^a-zA-Z]/g, '').slice(0, 3).toUpperCase() : RECORDED_INPUT.product_code)
  const [description, setDescription] = useState(live ? '' : RECORDED_INPUT.description)
  const [busy, setBusy] = useState(false)
  const [out, setOut] = useState<Outcome | null>(null)
  const [asked, setAsked] = useState('')
  const ready = code.length === 3 && description.trim().length >= MIN_DESCRIPTION
  const run = async () => {
    if (!live || busy || !ready) return
    setBusy(true)
    setOut(null)
    const desc = description.trim()
    const o = await investigate(code, desc, { fetcher: fetcher ?? ((u, init) => fetch(u, init)), apiBase })
    setAsked(desc)
    setOut(o)
    setBusy(false)
  }
  return (
    <div className="ms2-inv" data-testid="investigate-page">
      <header className="ms2-pagehead">
        <h1 className="ms2-h1">Investigate a complaint</h1>
        <p className="ms2-lead">
          Check a complaint against what FDA already holds for the device type. Everything below comes from public FDA data, each number has its
          openFDA query, and no AI model is used.
        </p>
      </header>
      <p className="ms-banner ms-banner--warn ms2-inv-banner" role="note" data-testid="inv-banner">
        {BANNER}
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
        <p className="ms2-muted m-0 text-[15px]" data-testid="inv-device-note">
          From the simulated device <code>{device}</code> (a fictional device; its id is not sent anywhere).
        </p>
      )}
      <form
        className="ms2-inv-form"
        onSubmit={(e) => {
          e.preventDefault()
          void run()
        }}
        aria-label="Complaint details"
      >
        <label htmlFor="inv-code" className="ms2-inv-label">
          Product code
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
          <span id="inv-code-hint" className="ms2-muted block text-[14px]">
            Three letters. Not sure? Use Check any device type first.
          </span>
        </label>
        <label htmlFor="inv-desc" className="ms2-inv-label ms2-inv-grow">
          What went wrong with the device
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
            aria-describedby="inv-desc-hint"
          />
          <span id="inv-desc-hint" className="ms2-muted block text-[14px]">
            <span className="ms-num" data-testid="inv-count">
              {description.length}
            </span>{' '}
            of {MAX_DESCRIPTION} characters. Used once to find similar reports; not stored.
          </span>
        </label>
        {live && (
          <div className="ms2-inv-submit">
            <button type="submit" className="ms-btn ms-btn--primary" disabled={busy || !ready} data-testid="inv-run">
              {busy ? 'Searching openFDA…' : 'Investigate'}
            </button>
          </div>
        )}
      </form>
      <div aria-live="polite">
        {busy && (
          <p className="ms2-muted" role="status" data-testid="inv-busy">
            Asking openFDA. This takes a few seconds.
          </p>
        )}
        {out && !out.ok && (
          <p
            role="alert"
            className={`ms-banner ${out.kind === 'patient_data' ? 'ms-banner--warn' : 'ms-banner--err'}`}
            data-testid={`inv-error-${out.kind}`}
          >
            {out.message}
          </p>
        )}
      </div>
      {live && out?.ok && <Results a={out.answer} description={asked} />}
      {!live && RECORDED && <Results a={RECORDED} description={RECORDED_INPUT.description} />}
    </div>
  )
}
