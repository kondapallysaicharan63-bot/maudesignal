// Live-model fallback (PRD-22, reviewer desktop check): when a live answer fails, times out (504 live_timeout) or a
// cap is hit, the same screen shows (1) the recorded answer for that question, labelled RECORDED with its date, if one
// exists; (2) four deterministic lookups that make NO model call, over the stored exports in this page; (3) Retry live,
// with its cost. The failure and every fallback choice go to the browser audit trail. Nothing is invented.
import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { closestThread } from '../match'
import type { WorkspaceData } from '../types'
import { realDetails } from '../v2/realAlerts'
import { appendAudit } from './audit'

export type FailureKind = 'timeout' | 'failure' | 'cap'
export interface Fallback {
  kind: FailureKind
  /** The server or client message, shown as is. */
  reason: string
  productCode: string | null
}

export const FallbackData = createContext<Pick<WorkspaceData, 'evidence' | 'alerts' | 'threads'> | null>(null)

/** Retry cost line: the live ask caps (connector/callcap.py, globalcap.py, copilot/spend.py). */
export const RETRY_COST = 'One live Muse Spark call: usually under $0.01, capped at $0.25 per call and $2.00 a day for asks.'
export const KIND_TEXT: Record<FailureKind, string> = {
  timeout: 'The live answer took longer than its time budget, so it was stopped (no answer was invented).',
  failure: 'The live model call failed (no answer was invented).',
  cap: 'A spend or call cap was reached, so no model call was made.',
}

type Lookup = 'live' | 'reports' | 'recalls' | 'summary'
export const LOOKUPS: { id: Lookup; label: string }[] = [
  { id: 'live', label: 'Check this code live' },
  { id: 'reports', label: 'Search stored reports' },
  { id: 'recalls', label: 'Show recalls' },
  { id: 'summary', label: 'Show product summary' },
]

/** A three-letter code named in the question that the stored data knows, or the turn's own code. */
export function codeFor(question: string, given: string | null, known: string[]): string | null {
  if (given && known.includes(given)) return given
  const m = question.toUpperCase().match(/\b[A-Z]{3}\b/g) ?? []
  return m.find((c) => known.includes(c)) ?? given ?? null
}

const STOP = new Set(['the', 'and', 'for', 'with', 'what', 'which', 'this', 'that', 'were', 'was', 'are', 'any', 'how', 'many', 'show', 'reports', 'report', 'week', 'did', 'does', 'from', 'about', 'there', 'have', 'has'])
const words = (q: string): string[] => [...new Set((q.toLowerCase().match(/[a-z]{4,}/g) ?? []).filter((w) => !STOP.has(w)))]

export function knownCodes(d: Pick<WorkspaceData, 'evidence' | 'alerts'>): string[] {
  const s = new Set<string>()
  for (const r of Object.values(d.evidence.reports)) if (r.product_code) s.add(r.product_code)
  for (const a of realDetails(d)) s.add(a.product_code)
  return [...s].sort()
}

export function searchStored(d: Pick<WorkspaceData, 'evidence'>, code: string | null, question: string) {
  const ws = words(question)
  const rows = Object.entries(d.evidence.reports)
    .filter(([, r]) => !code || r.product_code === code)
    .map(([id, r]) => ({ id, r, hits: ws.filter((w) => (r.excerpt ?? '').toLowerCase().includes(w)) }))
  const matched = ws.length ? rows.filter((x) => x.hits.length > 0) : rows
  return { words: ws, total: rows.length, rows: matched.sort((a, b) => b.hits.length - a.hits.length || (b.r.date_received ?? '').localeCompare(a.r.date_received ?? '')).slice(0, 10), matched: matched.length }
}

export function storedRecalls(d: Pick<WorkspaceData, 'alerts'>, code: string | null) {
  const a = realDetails(d).find((x) => x.product_code === code)
  return a ? { total: a.recalls_total, items: a.recalls } : null
}

export function productSummary(d: Pick<WorkspaceData, 'evidence' | 'alerts'>, code: string | null) {
  const reports = Object.values(d.evidence.reports).filter((r) => r.product_code === code)
  const byType: Record<string, number> = {}
  for (const r of reports) byType[r.event_type ?? 'not stated'] = (byType[r.event_type ?? 'not stated'] ?? 0) + 1
  const dates = reports.map((r) => r.date_received).filter(Boolean).sort() as string[]
  const alert = realDetails(d).find((x) => x.product_code === code) ?? null
  return { reports: reports.length, byType, earliest: dates[0] ?? null, latest: dates[dates.length - 1] ?? null, alert }
}

const ymd = (s: string | null) => (s && /^\d{8}$/.test(s) ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6)}` : (s ?? 'date not stated'))

export function FallbackPanel({ fb, question, onRetry, onLive, recordedShown }: { fb: Fallback; question: string; onRetry: () => void; onLive: (code: string | null) => void; recordedShown: boolean }) {
  const data = useContext(FallbackData)
  const known = useMemo(() => (data ? knownCodes(data) : []), [data])
  const [code, setCode] = useState<string | null>(() => codeFor(question, fb.productCode, known))
  const [open, setOpen] = useState<Lookup | null>(null)
  const logged = useRef(false)
  useEffect(() => {
    if (logged.current) return
    logged.current = true
    void appendAudit({ actor: 'system', action: 'live_failure', entity_id: 'chat:live', payload: { kind: fb.kind, product_code: code ?? '', reason: fb.reason.slice(0, 200) } })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const recorded = data ? closestThread(question, data.threads.threads) : null
  const choose = (id: Lookup) => {
    void appendAudit({ actor: 'system', action: 'fallback_choice', entity_id: 'chat:live', payload: { choice: id, product_code: code ?? '' } })
    if (id === 'live') onLive(code)
    else setOpen(id)
  }
  return (
    <section className="ms2-card" aria-label="Live answer did not complete" data-testid="fallback" data-kind={fb.kind}>
      <p className="m-0" role="status" data-testid="fallback-reason">
        <strong>{KIND_TEXT[fb.kind]}</strong> <span className="ms2-muted">{fb.reason}</span>
      </p>
      <p className="m-0 mt-2" data-testid="fallback-recorded">
        {recorded && recordedShown ? (
          <>
            <span className="ms2-tag">RECORDED</span> The answer above is a recorded run of {(recorded.thread.recorded_at_utc ?? '').slice(0, 10) || 'date not stated'} for the
            closest stored question: &ldquo;{recorded.thread.question}&rdquo;.
          </>
        ) : (
          'No recorded answer is stored for this question.'
        )}
      </p>
      <p className="ms2-inv-meta m-0 mt-2">These lookups make no model call; they read the stored FDA data in this page (or openFDA counts, for the live check).</p>
      {known.length > 0 && (
        <p className="m-0 mt-1">
          <label className="ms2-inv-label" htmlFor="fb-code">
            Product code
          </label>{' '}
          <select id="fb-code" className="ms2-inv-input" style={{ minHeight: 44, width: 'auto' }} value={code ?? ''} onChange={(e) => setCode(e.target.value || null)} data-testid="fallback-code">
            <option value="">choose</option>
            {known.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </p>
      )}
      <div className="mt-2 flex flex-wrap gap-2">
        {LOOKUPS.map((l) => (
          <button key={l.id} type="button" className="ms-btn" style={{ minHeight: 44 }} onClick={() => choose(l.id)} data-testid={`fallback-${l.id}`} disabled={l.id !== 'reports' && !code}>
            {l.label}
          </button>
        ))}
        <button type="button" className="ms-btn ms-btn--secondary" style={{ minHeight: 44 }} onClick={() => {
          void appendAudit({ actor: 'system', action: 'fallback_choice', entity_id: 'chat:live', payload: { choice: 'retry', product_code: code ?? '' } })
          onRetry()
        }} disabled={fb.kind === 'cap'} data-testid="fallback-retry">
          Retry live
        </button>
      </div>
      <p className="ms2-inv-meta m-0 mt-1" data-testid="fallback-cost">
        {fb.kind === 'cap' ? 'Retry is off while the cap is reached.' : RETRY_COST}
      </p>
      {data && open === 'reports' && (() => {
        const s = searchStored(data, code, question)
        return (
          <div className="mt-3" data-testid="fallback-out-reports">
            <p className="m-0">
              <strong className="ms-num">{s.matched}</strong> of <span className="ms-num">{s.total}</span> stored reports{code ? ` for ${code}` : ''} mention
              {s.words.length ? ` ${s.words.join(', ')}` : ' anything (no search words)'} (a text match, not a finding). Newest first:
            </p>
            <ul className="ms2-inv-plain">
              {s.rows.map((x) => (
                <li key={x.id}>
                  <a className="ms2-a ms-num" href={x.r.maude_url} target="_blank" rel="noreferrer">
                    {x.id}
                  </a>{' '}
                  · {x.r.product_code} · {ymd(x.r.date_received)} · {x.r.event_type ?? 'event type not stated'} · filed by {x.r.report_source ?? 'not stated'}
                </li>
              ))}
            </ul>
          </div>
        )
      })()}
      {data && open === 'recalls' && (() => {
        const r = storedRecalls(data, code)
        return (
          <div className="mt-3" data-testid="fallback-out-recalls">
            {r ? (
              <>
                <p className="m-0">
                  <strong className="ms-num">{r.total}</strong> recall records for {code} (stored); newest {r.items.length}:
                </p>
                <ul className="ms2-inv-plain">
                  {r.items.map((x) => (
                    <li key={x.id}>
                      <span className="ms-num">{x.id}</span> · {x.date ?? 'date not stated'} · {x.reason ?? 'reason not stored'}
                      {x.url && (
                        <>
                          {' · '}
                          <a className="ms2-a" href={x.url} target="_blank" rel="noreferrer">
                            FDA record
                          </a>
                        </>
                      )}
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="m-0">No stored recall list for {code}. Open the live check for openFDA counts.</p>
            )}
          </div>
        )
      })()}
      {data && open === 'summary' && (() => {
        const p = productSummary(data, code)
        return (
          <div className="mt-3" data-testid="fallback-out-summary">
            <p className="m-0">
              {code}
              {p.alert?.device_type ? ` · ${p.alert.device_type}` : ''}: <strong className="ms-num">{p.reports}</strong> stored reports in this page
              {p.earliest ? ` (${ymd(p.earliest)} to ${ymd(p.latest)})` : ''}.{' '}
              {Object.entries(p.byType)
                .map(([k, v]) => `${k} ${v}`)
                .join(' · ')}
            </p>
            {p.alert && (
              <p className="m-0 mt-1">
                Latest flag: {p.alert.rule ?? 'none'}
                {p.alert.mix_sentence ? ` — ${p.alert.mix_sentence}` : ''} ({p.alert.source.label}, as of {p.alert.source.as_of ?? 'date not stated'}).
              </p>
            )}
          </div>
        )
      })()}
    </section>
  )
}
