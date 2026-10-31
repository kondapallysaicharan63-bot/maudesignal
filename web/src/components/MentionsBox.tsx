import { useState } from 'react'
import { LiveError, postMentions } from '../live/api'
import {
  droppedLine,
  KIND_LABEL,
  MENTION_BADGE,
  MENTIONS_TITLE,
  NO_STORED_SEARCH,
  statusLabel,
  zeroLine,
  type Mention,
  type MentionsResult,
  type SourceTried,
} from '../mentions'
import { Icon } from '../icons'
import { Pill } from './artifacts/common'
import { LiveTrace } from './LiveTrace'

type Fetcher = (url: string, init?: RequestInit) => Promise<Response>

function MentionCard({ m }: { m: Mention }) {
  const official = m.source_kind === 'official'
  return (
    <li className="rounded-md border border-rule bg-surface p-3" data-testid="mention" data-kind={m.source_kind}>
      <p className="m-0 flex flex-wrap items-center gap-x-2 gap-y-1 text-[16px]">
        <span className="ws-wrap font-semibold">{m.source_name}</span>
        {official && (
          <span className="ws-pill bg-success-soft text-success" data-testid="official-badge">
            {KIND_LABEL.official}
          </span>
        )}
        {!official && <span className="ws-pill bg-sunk text-ink-2">{KIND_LABEL[m.source_kind]}</span>}
        {m.date && <span className="ms-num text-ink-2">{m.date}</span>}
      </p>
      <blockquote className="ws-wrap m-0 mt-2 border-l-4 border-rule-strong pl-3 text-[17px] leading-snug text-ink">
        “{m.quote}”
      </blockquote>
      {m.why_matched && (
        <p className="ws-wrap m-0 mt-2 text-[16px] text-ink-2">
          <span className="font-semibold text-ink">Why it matched:</span> {m.why_matched}
        </p>
      )}
      <p className="m-0 mt-2 flex flex-wrap items-center gap-2">
        <span className="ws-pill ws-wrap max-w-full !shrink !whitespace-normal bg-warning-soft text-warning" data-testid="unverified-badge">
          {MENTION_BADGE}
        </span>
      </p>
      <p className="m-0 mt-2">
        <a className="ws-wrap inline-flex min-h-11 items-center text-[17px] text-accent underline" href={m.url} target="_blank" rel="noreferrer noopener">
          Open the page
        </a>
      </p>
    </li>
  )
}

function SourceList({ tried, testid }: { tried: SourceTried[]; testid: string }) {
  if (tried.length === 0) return <p className="m-0 mt-1 text-[15px] text-ink-2" data-testid={testid}>No source list was recorded for this search.</p>
  return (
    <ul className="m-0 mt-1 list-none p-0 text-[15px]" data-testid={testid}>
      {tried.map((s, i) => (
        <li key={`${s.name}-${i}`} className="ws-wrap py-1" data-testid="source-row">
          {s.url ? (
            <a className="text-accent underline" href={s.url} target="_blank" rel="noreferrer noopener">
              {s.name}
            </a>
          ) : (
            s.name
          )}{' '}
          <span className="text-ink-2">
            · {statusLabel(s.status)} · <span className="ms-num">{s.n}</span> {s.n === 1 ? 'page' : 'pages'}
          </span>
        </li>
      ))}
    </ul>
  )
}

/**
 * News and public web mentions of a device type. A separate box, never mixed with the checked FDA facts: every mention
 * is marked unverified. Stored search first (mentions.json); the button runs the live search when the API is connected,
 * and falls back to the stored search on a limit or an error.
 */
export function MentionsBox({
  code,
  terms,
  apiBase,
  stored,
  fetcher,
}: {
  code: string
  terms?: string[]
  apiBase: string | null
  stored: MentionsResult | null
  fetcher?: Fetcher
}) {
  const [live, setLive] = useState<MentionsResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const shown = live ?? stored

  const search = async () => {
    setNotice(null)
    if (!apiBase) {
      setNotice('The live search is not connected in this build.' + (stored ? ' The stored search is shown.' : ''))
      return
    }
    setBusy(true)
    try {
      const r = await postMentions(code, terms, { apiBase, fetcher: fetcher ?? ((u, i) => fetch(u, i)) })
      setLive(r)
      if (r.mode === 'recorded') setNotice(r.recorded_note ?? 'Shown from a stored search.')
    } catch (e) {
      const err = e instanceof LiveError ? e : new LiveError('network', 'The live search could not be reached.')
      setLive(null)
      setNotice(err.kind === 'rate_limited' ? `Daily live limit reached. ${stored ? 'Showing the stored search.' : NO_STORED_SEARCH + '.'}` : `${err.message} ${stored ? 'Showing the stored search.' : NO_STORED_SEARCH + '.'}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section
      className="rounded-md border-2 border-dashed border-rule-strong bg-sunk p-3 md:p-4"
      aria-label={MENTIONS_TITLE}
      data-testid="mentions-box"
    >
      <h3 className="m-0 font-serif text-[20px] font-semibold">{MENTIONS_TITLE}</h3>
      <p className="ms-banner ms-banner--warn m-0 mt-2" data-testid="mentions-banner">
        <span className="ws-wrap">Pages found on the web and in the news. They are not checked against FDA records and are kept apart from the checked facts.</span>
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button type="button" className="ms-btn ms-btn--secondary" style={{ height: 44 }} onClick={() => void search()} disabled={busy} aria-busy={busy} data-testid="search-outside">
          <Icon name="search" size={18} /> {busy ? 'Searching…' : 'Search outside sources'}
        </button>
        {shown && (
          <Pill tone={shown.mode === 'live' ? 'ok' : 'neutral'}>
            {shown.mode === 'live' ? 'Live search' : `Stored search${shown.searched_utc ? `, ${shown.searched_utc.slice(0, 10)}` : ''}`}
          </Pill>
        )}
      </div>
      <p className="m-0 mt-2 text-[15px] text-ink-2">{terms && terms.length ? 'Only the three-letter product code and short device terms are sent.' : 'Only the three-letter product code is sent.'} No personal details.</p>
      {notice && (
        <p role="status" className="ws-wrap m-0 mt-2 text-[16px] text-ink" data-testid="mentions-notice">
          {notice}
        </p>
      )}
      {!shown ? (
        <p className="m-0 mt-3 text-ink-2" data-testid="mentions-none">
          {NO_STORED_SEARCH}
        </p>
      ) : (
        <div className="mt-3" data-testid="mentions-result" data-mode={shown.mode}>
          <p className="m-0 text-[16px] text-ink" data-testid="mentions-dropped">
            {droppedLine(shown.mentions.length, shown.dropped)}
          </p>
          {shown.dropped.off_topic > 0 && <p className="m-0 mt-1 text-[15px] text-ink-2">{shown.dropped.off_topic} more were off topic and are not shown.</p>}
          {shown.mentions.length === 0 ? (
            <div className="mt-2" data-testid="mentions-zero">
              <p className="ws-wrap m-0 text-[17px] font-semibold text-ink" data-testid="mentions-zero-line">
                {zeroLine(shown.searched_utc)}
              </p>
              <p className="m-0 mt-1 text-[15px] text-ink-2">Sources checked, with what each one returned:</p>
              <SourceList tried={shown.sources_tried} testid="sources-checked" />
            </div>
          ) : (
            <ul className="m-0 mt-3 list-none space-y-3 p-0" aria-label="Mentions">
              {shown.mentions.map((m, i) => (
                <MentionCard key={`${m.url}-${i}`} m={m} />
              ))}
            </ul>
          )}
          {shown.mentions.length > 0 && shown.sources_tried.length > 0 && (
            <details className="mt-3">
              <summary className="min-h-11 cursor-pointer py-2 text-[16px] text-ink-2">Sources tried ({shown.sources_tried.length})</summary>
              <SourceList tried={shown.sources_tried} testid="sources-tried" />
            </details>
          )}
          {shown.trace.length > 0 && (
            <div className="mt-2">
              <LiveTrace steps={shown.trace} label="Steps of this search" />
            </div>
          )}
          {shown.limits && shown.mode === 'live' && (
            <p className="m-0 mt-2 text-[15px] text-ink-2">
              {shown.limits.remaining_today} live {shown.limits.remaining_today === 1 ? 'search' : 'searches'} left today
            </p>
          )}
        </div>
      )}
    </section>
  )
}
