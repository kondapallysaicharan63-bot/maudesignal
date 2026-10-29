import { useEffect, useState } from 'react'
import { chipState, fmtDate, resolveClaim, type ChipState } from '../claims'
import { Icon } from '../icons'
import type { Evidence, Sentence, Thread } from '../types'

const MAX_ROWS = 6
// Threads already streamed in this session show at once when re-opened.
const played = new Set<string>()

const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** Reveals `words` one at a time (streaming look). Instant with prefers-reduced-motion or when skipped. */
function useWordReveal(total: number, runKey: string, instant: boolean): number {
  const [n, setN] = useState(instant ? total : 0)
  useEffect(() => {
    if (instant || reduced()) {
      setN(total)
      return
    }
    setN(0)
    const id = window.setInterval(() => {
      setN((c) => {
        if (c + 1 >= total) window.clearInterval(id)
        return Math.min(total, c + 1)
      })
    }, 28)
    return () => window.clearInterval(id)
  }, [total, runKey, instant])
  return n
}

const CHIP: Record<ChipState, { cls: string; label: string }> = {
  verified: { cls: 'bg-success-soft text-success', label: 'Verified' },
  withheld: { cls: 'bg-critical-soft text-critical', label: 'Withheld' },
  'no-claim': { cls: 'bg-sunk text-ink-2', label: 'No factual claim' },
}

function EvidencePanel({ s, ev }: { s: Sentence; ev: Evidence }) {
  if (s.status !== 'pass')
    return (
      <div className="mt-2 rounded-md border border-rule bg-surface p-3 text-[15px]">
        <p className="m-0 font-semibold text-critical">Withheld by the gate. Reason:</p>
        <ul className="ws-wrap m-0 mt-1 list-disc pl-5 text-critical">
          {s.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      </div>
    )
  if (s.claims.length === 0)
    return (
      <p className="m-0 mt-2 rounded-md border border-rule bg-surface p-3 text-[15px] text-ink-2">
        This sentence states no checkable fact (for example a limit or a reminder), so there is nothing to look up.
      </p>
    )
  return (
    <div className="mt-2 space-y-3 rounded-md border border-rule bg-surface p-3 text-[15px]">
      {s.claims.map((c, i) => {
        const r = resolveClaim(c, ev)
        const shown = r.reports.slice(0, MAX_ROWS)
        return (
          <div key={i}>
            <p className="m-0 font-semibold">
              <span className="ms-code">{c.kind}</span> <span className="text-success">verified</span>
              <span className="text-ink-2">: {c.reason}</span>
            </p>
            {r.reports.length + r.others.length === 0 && (
              <p className="m-0 mt-1 text-ink-3">No report ids listed; the count was recomputed over the stored data.</p>
            )}
            {c.evidence_ids.length > shown.length + r.others.length && r.reports.length > 0 && (
              <p className="m-0 mt-1 text-ink-3">
                Showing {shown.length} of {c.evidence_ids.length} listed ids, most serious and newest first.
              </p>
            )}
            <ul className="m-0 mt-1 list-none space-y-2 p-0">
              {shown.map(({ id, row }) => (
                <li key={id} className="border-l-2 border-rule-strong pl-3">
                  <p className="ws-wrap m-0 text-ink-2">
                    Report {id} · {row.product_code} · {row.event_type} · {fmtDate(row.date_received)} ·{' '}
                    {row.report_source}
                  </p>
                  <p className="ws-wrap m-0 text-ink-3">&ldquo;{row.excerpt.slice(0, 200)}
                    {row.excerpt.length > 200 ? '…' : ''}&rdquo;</p>
                  <a href={row.maude_url} target="_blank" rel="noreferrer" className="text-[14px] underline">
                    Open in MAUDE
                  </a>
                </li>
              ))}
              {r.others.map(({ id, row }) => (
                <li key={id} className="border-l-2 border-rule-strong pl-3">
                  <p className="ws-wrap m-0 text-ink-2">
                    {row.kind} {id}: {row.label.slice(0, 140)}
                  </p>
                  <a href={row.url} target="_blank" rel="noreferrer" className="text-[14px] underline">
                    Open source
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )
      })}
    </div>
  )
}

function SentenceLine({ s, ev, instant, onDone }: { s: Sentence; ev: Evidence; instant: boolean; onDone?: () => void }) {
  const words = s.text.split(' ')
  const n = useWordReveal(words.length, s.text, instant)
  const done = n >= words.length
  const [hover, setHover] = useState(false)
  const [pinned, setPinned] = useState(false)
  useEffect(() => {
    if (done && onDone) onDone()
  }, [done]) // eslint-disable-line react-hooks/exhaustive-deps
  const state = chipState(s)
  const c = CHIP[state]
  const open = hover || pinned
  return (
    <li className="py-1.5">
      <span className={`ws-wrap ${state === 'withheld' ? 'text-ink-3 line-through' : ''}`}>
        {words.slice(0, n).join(' ')}
      </span>
      {done && (
        <>
          {' '}
          <button
            className={`ws-pill ml-1 cursor-pointer align-middle ${c.cls}`}
            aria-expanded={open}
            aria-label={`${c.label}${s.claims.length ? `, ${s.claims.length} claim${s.claims.length > 1 ? 's' : ''}` : ''}: show evidence`}
            onClick={() => setPinned((p) => !p)}
            onMouseEnter={() => setHover(true)}
            onMouseLeave={() => setHover(false)}
          >
            {state === 'verified' && <Icon name="check" size={12} />}
            {c.label}
            {state === 'verified' && ` · ${s.claims.length}`}
          </button>
          {open && <EvidencePanel s={s} ev={ev} />}
          {state === 'withheld' && !open && s.reasons[0] && (
            <p className="ws-wrap m-0 mt-1 text-[15px] text-critical">Gate: {s.reasons[0]}</p>
          )}
        </>
      )}
    </li>
  )
}

function FirstPass({ t }: { t: Thread }) {
  if (!t.repaired || !t.first_pass) return null
  return (
    <details className="rounded-md border border-rule bg-surface px-3 py-2 text-[15px]">
      <summary className="cursor-pointer font-semibold">What the gate blocked first</summary>
      <p className="m-0 mt-2 text-ink-2">
        First draft: {t.first_pass.passed} sentences passed, {t.first_pass.blocked} blocked. The model was asked to
        repair it; the answer above is the second pass.
      </p>
      <ul className="m-0 mt-2 list-none p-0">
        {t.first_pass.sentences.map((s, i) => {
          const st = chipState(s)
          return (
            <li key={i} className="py-1">
              <span className={`ws-pill mr-2 ${CHIP[st].cls}`}>{CHIP[st].label}</span>
              <span className={`ws-wrap ${st === 'withheld' ? 'text-ink-3 line-through' : ''}`}>{s.text}</span>
              {st === 'withheld' &&
                s.reasons.map((r) => (
                  <span key={r} className="ws-wrap block text-critical">
                    Gate: {r}
                  </span>
                ))}
            </li>
          )
        })}
      </ul>
    </details>
  )
}

export function ThreadView({ t, ev, siblings, onThread }: {
  t: Thread
  ev: Evidence
  siblings: Thread[]
  onThread: (id: string) => void
}) {
  const instant = played.has(t.id)
  // Units: tool steps first, then sentences one after another.
  const [stage, setStage] = useState(instant || reduced() ? 1000 : 0)
  const [replay, setReplay] = useState(0)
  useEffect(() => {
    if (stage >= t.tool_steps.length + t.sentences.length) played.add(t.id)
  }, [stage, t])
  useEffect(() => {
    if (stage >= t.tool_steps.length || reduced()) return
    const id = window.setTimeout(() => setStage((s) => s + 1), 350)
    return () => window.clearTimeout(id)
  }, [stage, t.tool_steps.length])

  const heard = t.voice ? t.voice.transcript_text : null
  const heardWords = (heard ?? '').split(' ')
  const hn = useWordReveal(heardWords.length, `${t.id}-${replay}`, replay === 0)
  const seconds = t.voice ? t.voice.audio_seconds.toFixed(1) : ''

  return (
    <div className="space-y-5">
      {siblings.length > 1 && (
        <details className="text-[15px]">
          <summary className="cursor-pointer text-ink-2">
            Other questions in this workflow ({siblings.length - 1})
          </summary>
          <ul className="m-0 mt-2 list-none p-0">
            {siblings
              .filter((x) => x.id !== t.id)
              .map((x) => (
                <li key={x.id}>
                  <button className="ws-side-item items-start border-b border-rule" onClick={() => onThread(x.id)}>
                    <span className="ws-wrap">{x.question}</span>
                    <Icon name="chevron" size={18} />
                  </button>
                </li>
              ))}
          </ul>
        </details>
      )}
      <div className="ml-auto max-w-[85%] rounded-md bg-sunk px-4 py-3">
        {t.voice ? (
          <>
            <p className="ws-wrap m-0">
              <span className="font-semibold">Heard:</span> &ldquo;{heardWords.slice(0, hn).join(' ')}&rdquo;
            </p>
            <p className="m-0 mt-2 flex flex-wrap items-center gap-2 text-[13px] text-ink-3">
              <button
                className="ws-icon-btn !h-8 border-rule-strong"
                aria-label="Replay the recorded transcript"
                onClick={() => setReplay((r) => r + 1)}
              >
                <Icon name="mic" size={16} />
              </button>
              <span>
                Recorded voice question · {seconds} s · {t.voice.language}. The button replays the recorded
                transcript; the audio itself is not stored in this page.
              </span>
            </p>
          </>
        ) : (
          <p className="ws-wrap m-0">{t.question}</p>
        )}
      </div>
      {t.tool_steps.length > 0 && (
        <ul className="m-0 list-none space-y-1 p-0 text-[15px] text-ink-2" aria-label="Steps taken">
          {t.tool_steps.slice(0, stage).map((s, i) => (
            <li key={i} className="flex gap-2">
              <span className="ms-code shrink-0">{s.name}</span>
              <span className="ws-wrap">{s.summary}</span>
            </li>
          ))}
        </ul>
      )}
      <ul className="m-0 list-none p-0">
        {t.sentences.slice(0, Math.max(0, stage - t.tool_steps.length + 1)).map((s, i) => (
          <SentenceLine
            key={`${t.id}-${i}`}
            s={s}
            ev={ev}
            instant={instant}
            onDone={() => setStage((c) => Math.max(c, t.tool_steps.length + i + 1))}
          />
        ))}
      </ul>
      <FirstPass t={t} />
      <p className="m-0 text-[13px] text-ink-3">
        Stored run · {t.model} · {t.recorded_at_utc.slice(0, 10)} · replayed from a recording, no live model call
      </p>
    </div>
  )
}
