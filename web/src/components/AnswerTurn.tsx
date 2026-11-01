import { useId, useState } from 'react'
import { apiBaseOrNull, resolveRef, sessionStore } from '../feedback'
import { heldBackLine, NOT_MEDICAL_ADVICE, openLabel, type AskResponse, type OpenView, type ResearchItem, type SaveOutcome } from '../live/api'
import { chipFor, copyText, newAnswerId, readableText } from '../live/answerMeta'
import { AnswerActions, type RatingSink } from './AnswerActions'
import { AnswerDetails } from './AnswerDetails'
import { ModelChip } from './ModelChip'
import { ResearchSection } from './ResearchSection'
import './answer.css'

/** "questions left" appears only when this many or fewer remain. */
export const FEW_LEFT = 5

/** Where ratings go by default: the build's API address and this visit's ref code (same as the feedback form). */
export function defaultRatingSink(): RatingSink {
  let refCode: string | null = null
  try {
    refCode = resolveRef(window.location.search, sessionStore())
  } catch {
    refCode = null
  }
  return {
    apiBase: apiBaseOrNull(import.meta.env.VITE_MAUDESIGNAL_API_BASE),
    refCode,
    fetcher: (u, i) => fetch(u, i),
  }
}

/** A small filled check and the word, for an answer whose FDA facts passed the claim gate. */
function Verified() {
  return (
    <span className="ms-verified" data-testid="mark-verified">
      <svg width="15" height="15" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <circle cx="12" cy="12" r="10" fill="currentColor" />
        <path d="m7.5 12.5 3 3 6-6.5" fill="none" stroke="var(--surface)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      Verified
    </span>
  )
}

interface Props {
  resp: AskResponse
  onAsk: (q: string) => void
  onOpen?: (o: OpenView) => void
  saveResearch: (item: ResearchItem) => Promise<SaveOutcome>
  /** Where a thumbs up / down is sent (tests pass a fake). */
  rating?: RatingSink
  /** When the answer arrived; defaults to when this turn was first drawn. */
  at?: Date
}

/**
 * One answer in the v2 layout: the checked sentences in a reading style with their FDA source chips, a Verified /
 * Withheld mark, one quiet chip naming the route and model, and a small action bar. Steps, timings, cost, tokens and
 * the tier sit in Details, closed by default.
 */
export function AnswerTurn({ resp, onAsk, onOpen, saveResearch, rating, at }: Props) {
  const [answerId] = useState(() => newAnswerId())
  const [arrived] = useState(() => at ?? new Date())
  const [sink] = useState<RatingSink>(() => rating ?? defaultRatingSink())
  const [detailsOpen, setDetailsOpen] = useState(false)
  const panelId = useId()
  const sentences = resp.answer.speakable
  const held = heldBackLine(resp.answer.withheld)
  const recorded = resp.mode === 'recorded'
  const linked = sentences.some((s) => s.links.length > 0)
  const open = openLabel(resp.open)
  const left = resp.limits?.remaining_today
  const showLeft = !recorded && typeof left === 'number' && left <= FEW_LEFT
  const free = resp.tier === 'canned' || resp.tier === 'direct' || resp.tier === 'cache'
  return (
    <div className="ans-turn" data-testid="live-answer" data-layout="v2" data-mode={resp.mode} data-tier={resp.tier ?? 'live'}>
      {sentences.length > 0 && (
        <div className="ans-text t-answer" data-testid="answer-sentences">
          {sentences.map((s, i) => (
            <div key={i} className="ans-sentence" data-testid="answer-sentence">
              <p className="ws-wrap">{s.text}</p>
              {s.links.length > 0 && (
                <span className="ans-sources" data-testid="sentence-links">
                  {s.links.map((l) => (
                    <a key={l.url} href={l.url} target="_blank" rel="noreferrer" className="ans-source">
                      {l.label}
                    </a>
                  ))}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
      {sentences.length === 0 && !held && !recorded && !free && <p className="ans-note">No sentence passed the claim gate for this question.</p>}
      {(linked || held) && (
        <p className="ans-marks m-0" data-testid="answer-marks">
          {linked && <Verified />}
          {held && (
            <span className="ans-withheld" data-testid="held-back">
              <b>Withheld</b>
              <span className="ws-wrap">{held}</span>
            </span>
          )}
        </p>
      )}
      {recorded && resp.recorded_note && (
        <p className="ans-note ws-wrap" data-testid="recorded-note">
          {resp.recorded_note}
        </p>
      )}
      {resp.research && <ResearchSection block={resp.research} onSave={saveResearch} />}
      {open && onOpen && resp.open && (
        <p className="m-0 mt-3">
          <button type="button" className="ms-btn ms-btn--secondary ms-btn--sm" onClick={() => onOpen(resp.open as OpenView)} data-testid="open-view">
            {open}
          </button>
        </p>
      )}
      {resp.suggestions.length > 0 && (
        <ul className="m-0 mt-3 flex list-none flex-wrap gap-2 p-0" aria-label="Suggested questions" data-testid="suggestions">
          {resp.suggestions.map((q) => (
            <li key={q}>
              <button type="button" className="ms-btn ms-btn--secondary ms-btn--sm" onClick={() => onAsk(q)} data-testid="suggestion-chip">
                <span className="ws-wrap">{q}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="ans-meta">
        <ModelChip chip={chipFor(resp)} />
        {showLeft && (
          <span className="ans-left ms-num" data-testid="limits">
            {left} live {left === 1 ? 'question' : 'questions'} left today
          </span>
        )}
        <AnswerActions
          answerId={answerId}
          copy={copyText(resp)}
          readable={readableText(resp)}
          at={arrived}
          rating={sink}
          details={{ open: detailsOpen, onToggle: () => setDetailsOpen((o) => !o), panelId }}
        />
      </div>
      {detailsOpen && <AnswerDetails resp={resp} id={panelId} />}
      <p className="ans-advice" data-testid="not-advice">
        {NOT_MEDICAL_ADVICE}
      </p>
    </div>
  )
}
