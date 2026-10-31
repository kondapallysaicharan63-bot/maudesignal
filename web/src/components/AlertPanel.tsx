import { useEffect, useRef } from 'react'
import {
  gateLine,
  NO_DETAIL_TEXT,
  rangeLine,
  safeUrl,
  showingLine,
  SIMULATED_BANNER,
  type AlertDetail,
} from '../alerts'
import { dialogKey } from '../feedback'
import { Icon } from '../icons'
import type { MentionsResult } from '../mentions'
import { Pill } from './artifacts/common'
import { MentionsBox } from './MentionsBox'

const FOCUSABLE = 'a[href], button:not([disabled]), summary, [tabindex]:not([tabindex="-1"])'

const RULE_TONE = { 'more serious than usual': 'bad', 'new kind of problem': 'bad', 'reports suddenly increased': 'warn' } as const

function Link({ href, children }: { href: string | null | undefined; children: string }) {
  const u = safeUrl(href)
  if (!u) return <span className="text-ink-2">{children}</span>
  return (
    <a className="ws-wrap inline-flex min-h-11 items-center text-accent underline" href={u} target="_blank" rel="noreferrer noopener">
      {children}
    </a>
  )
}

const H = ({ children, id }: { children: string; id: string }) => (
  <h3 id={id} className="ms-kicker m-0 mt-5 border-b border-rule-strong pb-1 !text-[16px]">
    {children}
  </h3>
)

/**
 * The full panel of one alert: a side sheet from 768 px up, the whole screen on a phone. Esc closes it, Tab stays inside it
 * and focus returns to the alert that was clicked (the caller restores it). Every number and sentence comes from alerts.json.
 */
export function AlertPanel({
  detail,
  fallbackCode,
  onClose,
  onShow,
  onOpenInChat,
  apiBase,
  mentions,
  mentionsFetcher,
}: {
  /** The stored detail; null shows the "no stored detail" text. */
  detail: AlertDetail | null
  fallbackCode?: string
  onClose: () => void
  /** Goes to where the alert lives in the workspace (the sweep row, the device, the brief). */
  onShow?: () => void
  /** Opens the live chat with the product code and the alert as context. */
  onOpenInChat: (a: { product_code: string; rule: AlertDetail['rule'] }) => void
  apiBase: string | null
  mentions: MentionsResult | null
  mentionsFetcher?: (url: string, init?: RequestInit) => Promise<Response>
}) {
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const t = setTimeout(() => box.current?.querySelector<HTMLElement>('[data-initial-focus]')?.focus(), 0)
    return () => clearTimeout(t)
  }, [])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const code = detail?.product_code ?? fallbackCode ?? ''
  const d = detail
  const simulated = d?.source.kind === 'company' || !!d?.owner
  return (
    <div className="fixed inset-0 z-[70]" data-testid="alert-panel-root" data-popover-open>
      <div className="ws-scrim" onClick={onClose} aria-hidden="true" data-testid="alert-panel-scrim" />
      <div
        ref={box}
        role="dialog"
        aria-modal="true"
        aria-labelledby="alert-panel-title"
        data-testid="alert-panel"
        className="absolute inset-0 flex flex-col overflow-hidden bg-surface md:inset-y-0 md:left-auto md:right-0 md:w-[min(44rem,92vw)] md:border-l md:border-rule-strong"
        style={{ boxShadow: 'var(--shadow-pop)' }}
        onKeyDown={(e) => {
          const els = Array.from(box.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []).filter((el) => el.offsetParent !== null || el === document.activeElement)
          dialogKey(e, els, document.activeElement as HTMLElement | null, (el) => el.focus())
        }}
      >
        <div className="flex shrink-0 items-start justify-between gap-2 border-b border-rule px-4 py-3">
          <div className="min-w-0">
            <p className="ms-kicker m-0">Alert</p>
            <h2 id="alert-panel-title" className="ws-wrap m-0 text-[22px] font-semibold leading-tight">
              <span className="ms-code !text-[22px] !text-ink">{code}</span>
              {d?.device_type ? <span className="font-normal"> · {d.device_type}</span> : null}
            </h2>
            {d?.rule && (
              <p className="m-0 mt-1">
                <Pill tone={RULE_TONE[d.rule]}>{d.rule}</Pill>
              </p>
            )}
          </div>
          <button type="button" className="ws-icon-btn min-h-11 min-w-11 shrink-0" onClick={onClose} aria-label="Close alert details (Esc)" data-initial-focus data-testid="alert-panel-close">
            <Icon name="close" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-8 pt-2" data-testid="alert-panel-scroll">
          {!d ? (
            <p className="m-0 mt-3 text-ink-2" data-testid="alert-no-detail">
              {NO_DETAIL_TEXT} Run <code>python3 scripts/export_alerts.py</code> to build it from the stored data.
            </p>
          ) : (
            <>
              <p className="m-0 mt-2 text-[16px] text-ink-2">
                {d.source.label}
                {d.source.as_of ? <> · as of <span className="ms-num">{d.source.as_of}</span></> : null}
              </p>

              <H id="ap-changed">What changed</H>
              <p className="ws-wrap m-0 mt-2 text-[17px]" data-testid="alert-rule-words">{d.rule_words}</p>
              {d.window && !(d.window.this_week.count === 0 && d.window.baseline_4wk.count === 0 && d.rule === null) ? (
                <>
                  <dl className="m-0 mt-3 grid grid-cols-2 gap-2" data-testid="alert-window">
                    <div className="rounded-md border border-rule bg-paper p-2">
                      <dt className="text-[15px] leading-snug text-ink-2">This week · {rangeLine(d.window.this_week)}</dt>
                      <dd className="t-index ms-num m-0 mt-1">{d.window.this_week.count ?? 'not stored'}</dd>
                    </div>
                    <div className="rounded-md border border-rule bg-paper p-2">
                      <dt className="text-[15px] leading-snug text-ink-2">4 weeks before · {rangeLine(d.window.baseline_4wk)}</dt>
                      <dd className="t-index ms-num m-0 mt-1">
                        {d.window.baseline_4wk.count ?? 'not stored'}
                        {d.window.baseline_4wk.weekly_mean != null && <span className="text-[16px] font-normal text-ink-2"> · {d.window.baseline_4wk.weekly_mean} a week</span>}
                      </dd>
                    </div>
                  </dl>
                  <ul className="m-0 mt-3 list-none p-0" aria-label="Numbers and their openFDA links">
                    {d.numbers.map((n) => (
                      <li key={n.label} className="flex flex-wrap items-baseline justify-between gap-x-3 border-t border-rule py-1" data-testid="alert-number">
                        <span className="ws-wrap">
                          {n.label}: <strong className="ms-num">{n.value}</strong>
                        </span>
                        <Link href={n.openfda_url}>openFDA query</Link>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <p className="m-0 mt-2 text-ink-2">No weekly counts are stored for this device type.</p>
              )}

              <H id="ap-reports">Reports behind it</H>
              {d.reports.length === 0 ? (
                <p className="m-0 mt-2 text-ink-2" data-testid="alert-no-reports">
                  No reports are stored in this workspace for this week. Open the openFDA query above to read them.
                </p>
              ) : (
                <>
                  <p className="m-0 mt-2 text-[16px] text-ink-2" data-testid="alert-showing">
                    {showingLine(d.reports.length, d.reports_total)}
                    {d.reports_stored != null && d.reports_total != null && d.reports_stored < d.reports_total ? ` (${d.reports_stored} are stored here)` : ''}
                  </p>
                  <ul className="m-0 list-none p-0" aria-label="Reports">
                    {d.reports.map((r) => (
                      <li key={r.report_id} className="border-t border-rule py-2" data-testid="alert-report">
                        <p className="m-0 flex flex-wrap items-center gap-x-2 text-[16px]">
                          <span className="ms-code !text-[16px]">{r.report_id}</span>
                          {r.date_received && <span className="ms-num text-ink-2">{r.date_received}</span>}
                          {r.event_type && <span className="text-ink-2">{r.event_type}</span>}
                        </p>
                        {r.quote ? (
                          <blockquote className="ws-wrap m-0 mt-1 border-l-4 border-rule-strong pl-3 text-[17px] leading-snug">“{r.quote}”</blockquote>
                        ) : (
                          <p className="m-0 mt-1 text-[16px] text-ink-2">{r.quote_note ?? 'No sentence of this report could be quoted.'}</p>
                        )}
                        <p className="m-0 flex flex-wrap gap-x-4">
                          <Link href={r.openfda_url}>openFDA record</Link>
                          {r.maude_url && <Link href={r.maude_url}>MAUDE page</Link>}
                        </p>
                      </li>
                    ))}
                  </ul>
                </>
              )}

              <H id="ap-recalls">Recalls and 510(k)</H>
              <p className="m-0 mt-2 text-[16px] font-semibold">Recalls</p>
              {d.recalls.length === 0 ? (
                <p className="m-0 text-ink-2">No recalls are stored for this device type.</p>
              ) : (
                <>
                  <p className="m-0 text-[15px] text-ink-2">Latest {d.recalls.length} of {d.recalls_total} stored</p>
                  <ul className="m-0 list-none p-0" aria-label="Recalls">
                    {d.recalls.map((r) => (
                      <li key={r.id} className="border-t border-rule py-2" data-testid="alert-recall">
                        <p className="m-0 flex flex-wrap items-center gap-x-2 text-[16px]">
                          <span className="ms-code !text-[16px]">{r.id}</span>
                          {r.date && <span className="ms-num text-ink-2">{r.date}</span>}
                        </p>
                        <p className="ws-wrap m-0 text-[17px]">{r.reason ? `${r.reason}${r.reason_truncated ? '…' : ''}` : <span className="text-ink-2">The reason is not shown (no sentence passed the check).</span>}</p>
                        <Link href={r.url}>Recall record</Link>
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <p className="m-0 mt-3 text-[16px] font-semibold">510(k) clearances</p>
              {d.k510.length === 0 ? (
                <p className="m-0 text-ink-2">No 510(k) records are stored for this device type.</p>
              ) : (
                <>
                  <p className="m-0 text-[15px] text-ink-2">Latest {d.k510.length} of {d.k510_total} stored</p>
                  <ul className="m-0 list-none p-0" aria-label="510(k) clearances">
                    {d.k510.map((k) => (
                      <li key={k.k_number} className="border-t border-rule py-2" data-testid="alert-k510">
                        <p className="ws-wrap m-0 text-[17px]">
                          <span className="ms-code !text-[16px]">{k.k_number}</span> · {k.applicant} · <span className="ms-num text-ink-2">{k.decision_date}</span>
                        </p>
                        <Link href={k.url}>510(k) record</Link>
                      </li>
                    ))}
                  </ul>
                </>
              )}

              <H id="ap-who">Who filed</H>
              {d.who_filed ? (
                <p className="m-0 mt-2 text-[17px]" data-testid="alert-who">
                  Of the {d.reports_stored ?? 0} stored reports this week: <strong className="ms-num">{d.who_filed.manufacturer}</strong> by the manufacturer,{' '}
                  <strong className="ms-num">{d.who_filed.user_facility}</strong> by a user facility, <strong className="ms-num">{d.who_filed.other}</strong> by others.
                </p>
              ) : (
                <p className="m-0 mt-2 text-ink-2">Not stored for this alert.</p>
              )}

              <H id="ap-next">Next steps</H>
              <ul className="m-0 mt-2 list-disc pl-5 text-[17px]" data-testid="alert-next-steps">
                {d.next_steps.map((s) => (
                  <li key={s} className="ws-wrap py-0.5">
                    {s}
                  </li>
                ))}
              </ul>
              <p className="m-0 mt-2 text-[16px] font-semibold">A person decides.</p>

              {d.owner && simulated && (
                <>
                  <H id="ap-owner">Owner and status</H>
                  <p className="ms-banner ms-banner--warn m-0 mt-2" data-testid="alert-simulated-banner">
                    <span className="ws-wrap font-semibold">{SIMULATED_BANNER}</span>
                  </p>
                  <p className="ws-wrap m-0 mt-2 text-[17px]" data-testid="alert-owner">
                    {d.owner.device_name ? <>{d.owner.device_name}: </> : null}
                    owner <strong>{d.owner.name}</strong>
                    {d.owner.status ? <>, status <strong>{d.owner.status}</strong></> : null}
                  </p>
                </>
              )}

              <p className="m-0 mt-5 flex items-center gap-2 text-[16px] text-ink" data-testid="alert-gate">
                <Icon name="check" size={16} />
                <span>{gateLine(d.gate)}</span>
              </p>
              {d.notes.length > 0 && (
                <details className="mt-2">
                  <summary className="min-h-11 cursor-pointer py-2 text-[16px] text-ink-2">Notes ({d.notes.length})</summary>
                  <ul className="m-0 list-disc pl-5 text-[16px] text-ink-2">
                    {d.notes.map((n) => (
                      <li key={n} className="ws-wrap">
                        {n}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </>
          )}

          <div className="mt-5 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
            <button type="button" className="ms-btn ws-btn-primary" style={{ height: 48 }} onClick={() => onOpenInChat({ product_code: code, rule: d?.rule ?? null })} disabled={!code} data-testid="open-in-chat">
              <Icon name="chat" size={18} /> Open in chat
            </button>
            {onShow && (
              <button type="button" className="ms-btn ms-btn--secondary" style={{ height: 48 }} onClick={onShow} data-testid="alert-show">
                Show it in the workspace
              </button>
            )}
          </div>
          <div className="mt-5">{code && <MentionsBox code={code} terms={d?.device_type ? [d.device_type] : undefined} apiBase={apiBase} stored={mentions} fetcher={mentionsFetcher} />}</div>
          <p className="m-0 mt-4 text-[15px] text-ink-2">Signals for a person to review. Not medical advice; nothing is filed with FDA.</p>
        </div>
      </div>
    </div>
  )
}
