import { useEffect, useRef, useState } from 'react'
import { Icon } from '../icons'
import { badgeText, heldBackLine, isFreeTier, LIMIT_TEXT, NOT_MEDICAL_ADVICE, openLabel, VOICE_NOTE, type AskResponse, type OpenView } from '../live/api'
import { speechSupported } from '../live/speech'
import type { LiveChat as Chat, LiveTurn } from '../live/useLiveChat'
import type { Thread } from '../types'
import { layoutMode, type LayoutMode } from '../layoutFlag'
import { labelChip } from '../live/answerMeta'
import { readKey } from '../live/readAloud'
import type { RatingSink } from './AnswerActions'
import { AnswerTurn } from './AnswerTurn'
import { ModelChip } from './ModelChip'
import { LiveLabelResult } from './CameraPanel'
import { LiveTrace } from './LiveTrace'
import { ResearchSection } from './ResearchSection'

const reduced = (): boolean => !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** Words shown so far: one more every 28 ms, all at once with prefers-reduced-motion. */
function useReveal(total: number, active: boolean): number {
  const [n, setN] = useState(active && !reduced() ? 0 : total)
  useEffect(() => {
    if (!active || reduced()) {
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
  }, [total, active])
  return n
}

function Sentence({ text, links, onDone }: { text: string; links: { label: string; url: string }[]; onDone: () => void }) {
  const words = text.split(' ')
  const n = useReveal(words.length, true)
  const done = n >= words.length
  const fired = useRef(false)
  useEffect(() => {
    if (done && !fired.current) {
      fired.current = true
      onDone()
    }
  }, [done, onDone])
  return (
    <li className="py-1.5" data-testid="answer-sentence">
      <span className="ws-wrap">{words.slice(0, n).join(' ')}</span>
      {done && links.length > 0 && (
        <span className="mt-1 block text-[15px]" data-testid="sentence-links">
          {links.map((l, i) => (
            <span key={l.url}>
              {i > 0 && ' · '}
              <a href={l.url} target="_blank" rel="noreferrer" className="text-accent underline">
                {l.label}
              </a>
            </span>
          ))}
        </span>
      )}
    </li>
  )
}

/** Badge colours: green for a live answer, amber for a recorded run, the quiet surface for tiers 1 to 3. */
function badgeClass(resp: AskResponse): string {
  if (isFreeTier(resp)) return 'bg-sunk text-ink ws-pill--ring'
  return resp.mode === 'recorded' ? 'bg-warning-soft text-warning' : 'bg-success-soft text-success'
}

/** The trace steps appear one by one as the run is shown, then the answer is written out word by word. */
function Answer({ turn, chat, onAsk, onOpen }: { turn: LiveTurn; chat: Chat; onAsk: (q: string) => void; onOpen?: (o: OpenView) => void }) {
  const resp = turn.resp as AskResponse
  const steps = resp.trace
  const [shownSteps, setSteps] = useState(reduced() ? steps.length : 0)
  useEffect(() => {
    if (shownSteps >= steps.length) return
    const id = window.setTimeout(() => setSteps((s) => s + 1), 220)
    return () => window.clearTimeout(id)
  }, [shownSteps, steps.length])
  const stepsDone = shownSteps >= steps.length
  const [upTo, setUpTo] = useState(1)
  const sentences = resp.answer.speakable
  const held = heldBackLine(resp.answer.withheld)
  const allShown = stepsDone && upTo > sentences.length
  const recorded = resp.mode === 'recorded'
  const free = isFreeTier(resp)
  const speaking = chat.speakingId === turn.id
  const open = openLabel(resp.open)
  return (
    <div data-testid="live-answer" data-mode={resp.mode} data-tier={resp.tier ?? 'live'}>
      <p className="m-0 flex flex-wrap items-center gap-2">
        <span className={`ws-pill ${badgeClass(resp)}`} data-testid="mode-badge">
          {badgeText(resp)}
        </span>
        {resp.limits && !recorded && (
          <span className="text-[15px] text-ink-2" data-testid="limits">
            {resp.limits.remaining_today} live {resp.limits.remaining_today === 1 ? 'question' : 'questions'} left today
          </span>
        )}
      </p>
      {recorded && resp.recorded_note && (
        <p className="ws-wrap m-0 mt-2 text-[16px] text-ink-2" data-testid="recorded-note">
          {resp.recorded_note}
        </p>
      )}
      {steps.length > 0 && (
        <div className="mt-2">
          <LiveTrace steps={steps} shown={shownSteps} />
        </div>
      )}
      {stepsDone && (
        <>
          {sentences.length > 0 && (
            <ul className="m-0 mt-2 list-none p-0" data-testid="answer-sentences">
              {sentences.slice(0, upTo).map((s, i) => (
                <Sentence key={i} text={s.text} links={s.links} onDone={() => setUpTo((u) => Math.max(u, i + 2))} />
              ))}
            </ul>
          )}
          {sentences.length === 0 && !held && !recorded && !free && <p className="m-0 mt-2 text-ink-2">No sentence passed the claim gate for this question.</p>}
          {allShown && held && (
            <p className="ws-wrap m-0 mt-2 text-[16px] text-ink-2" data-testid="held-back">
              {held}
            </p>
          )}
        </>
      )}
      {allShown && (
        <p className="m-0 mt-2 flex flex-wrap items-center gap-2 text-[15px] text-ink-2">
          {resp.answer.spoken_text && speechSupported() && (
            <button
              type="button"
              className="ms-btn ms-btn--secondary"
              style={{ height: 36 }}
              onClick={() => (speaking ? chat.stopSpeech() : chat.readAloud(turn.id))}
              aria-label={speaking ? 'Stop reading aloud' : 'Read this answer aloud'}
            >
              {speaking ? 'Stop' : 'Read aloud'}
            </button>
          )}
          {typeof resp.cost_usd === 'number' && (
            <span className="ms-num" data-testid="answer-cost">
              Cost of this answer: ${resp.cost_usd.toFixed(4)}
              {free ? ' (no model call)' : ''}
            </span>
          )}
          {resp.tier === 'cache' && resp.answered_at && <span data-testid="answered-at">First answered {resp.answered_at.slice(11, 16)} UTC</span>}
        </p>
      )}
      {allShown && resp.research && <ResearchSection block={resp.research} onSave={chat.saveResearch} />}
      {allShown && open && onOpen && resp.open && (
        <p className="m-0 mt-2">
          <button type="button" className="ms-btn ms-btn--secondary" style={{ height: 40 }} onClick={() => onOpen(resp.open as OpenView)} data-testid="open-view">
            {open}
          </button>
        </p>
      )}
      {allShown && resp.suggestions.length > 0 && (
        <ul className="m-0 mt-2 flex list-none flex-wrap gap-2 p-0" aria-label="Suggested questions" data-testid="suggestions">
          {resp.suggestions.map((q) => (
            <li key={q}>
              <button type="button" className="ms-btn ms-btn--secondary" style={{ height: 36 }} onClick={() => onAsk(q)} data-testid="suggestion-chip">
                <span className="ws-wrap">{q}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="m-0 mt-2 text-[15px] text-ink-2" data-testid="not-advice">
        {NOT_MEDICAL_ADVICE}
      </p>
    </div>
  )
}

/** While the model works: the steps that will run, the one in progress marked. Real timings arrive with the answer. */
function Typing({ voice }: { voice: boolean }) {
  return (
    <div role="status" aria-live="polite" data-testid="typing" className="text-[16px] text-ink-2">
      <p className="m-0 flex items-center gap-2">
        <span className="ms-num inline-flex gap-1" aria-hidden="true">
          <i className="ws-dot" />
          <i className="ws-dot" />
          <i className="ws-dot" />
        </span>
        <span>{voice ? 'Transcribing your question, then Muse Spark reads the stored records…' : 'Muse Spark is reading the stored records…'}</span>
      </p>
      <ol className="m-0 mt-1 list-none space-y-0.5 p-0 text-[15px]">
        {voice && <li>1 · Voice Transcribe: working</li>}
        <li>
          {voice ? 2 : 1} · Muse Spark: working
        </li>
        <li>
          {voice ? 3 : 2} · Claim gate: waits for the sentences
        </li>
      </ol>
    </div>
  )
}

/** v2: a calm line while the model works; the steps and their timings are in Details once the answer arrives. */
function TypingV2({ voice }: { voice: boolean }) {
  return (
    <div role="status" aria-live="polite" data-testid="typing" className="text-[15px] text-ink-2">
      <p className="m-0 flex items-center gap-2">
        <span className="inline-flex gap-1" aria-hidden="true">
          <i className="ws-dot" />
          <i className="ws-dot" />
          <i className="ws-dot" />
        </span>
        <span>{voice ? 'Transcribing your question, then Muse Spark reads the stored records…' : 'Muse Spark is reading the stored records…'}</span>
      </p>
    </div>
  )
}

/** A label photo sent from the message box: the picture, then the reading and the possible matches. */
function PhotoTurn({ turn, onRecordedLabel, v2 = false }: { turn: LiveTurn; onRecordedLabel?: () => void; v2?: boolean }) {
  return (
    <article className="space-y-3" data-testid="live-turn" data-status={turn.status} data-via="photo">
      <div className="ml-auto w-fit max-w-[85%] rounded-md bg-sunk p-2" data-testid="user-bubble">
        {turn.image ? (
          <img src={turn.image} alt="Your photo of a device label" className="block max-h-40 w-auto max-w-full rounded-sm" />
        ) : (
          <p className="m-0 px-2 py-1">Photo of a device label</p>
        )}
        {turn.followUp && (
          <>
            <p className="ws-wrap m-0 mt-2 whitespace-pre-wrap px-1">{turn.followUp}</p>
            <p className="m-0 mt-1 px-1 text-[15px] text-ink-2" data-testid="photo-followup-note">
              {turn.status === 'pending' ? 'Your question is sent after the photo reading.' : 'Your question was sent after the photo reading.'}
            </p>
          </>
        )}
      </div>
      {turn.status === 'pending' && (
        <p role="status" aria-live="polite" className="m-0 text-[16px] text-ink-2" data-testid="label-busy">
          Reading the label: SAM 3.1 finds it, Muse Spark reads it, openFDA is searched, then the claim gate checks the result…
        </p>
      )}
      {turn.status === 'error' && (
        <div role="alert" className="ms-banner ms-banner--warn" data-testid="turn-error">
          <span className="ws-wrap">{turn.error}</span>
          {turn.offerRecordedLabel && onRecordedLabel && (
            <button type="button" className="ms-btn ms-btn--secondary mt-2" style={{ height: 40 }} onClick={onRecordedLabel}>
              Open the recorded label runs
            </button>
          )}
        </div>
      )}
      {turn.status === 'done' && turn.label && <LiveLabelResult res={turn.label} />}
      {v2 && turn.status === 'done' && turn.label && (
        <p className="m-0">
          <ModelChip chip={labelChip(turn.label)} />
        </p>
      )}
    </article>
  )
}

export function TurnView({ turn, chat, onRecordedVoice, onRecordedLabel, onAsk, onOpen, v2 = false, rating }: {
  turn: LiveTurn
  chat: Chat
  onRecordedVoice: () => void
  onRecordedLabel?: () => void
  onAsk: (q: string) => void
  onOpen?: (o: OpenView) => void
  /** The ?layout=v2 answer turn; classic (false) draws exactly what it drew before. */
  v2?: boolean
  rating?: RatingSink
}) {
  if (turn.via === 'photo') return v2 ? <PhotoTurn turn={turn} onRecordedLabel={onRecordedLabel} v2 /> : <PhotoTurn turn={turn} onRecordedLabel={onRecordedLabel} />
  return (
    <article className="space-y-3" data-testid="live-turn" data-status={turn.status}>
      <div className="ml-auto max-w-[85%] rounded-md bg-sunk px-4 py-3" data-testid="user-bubble">
        {turn.via === 'voice' ? (
          <p className="ws-wrap m-0">
            <span className="font-semibold">Heard:</span>{' '}
            {turn.question ? <>&ldquo;{turn.question}&rdquo;</> : <span className="text-ink-2">{turn.status === 'pending' ? 'transcribing…' : 'nothing was heard'}</span>}
          </p>
        ) : (
          <p className="ws-wrap m-0 whitespace-pre-wrap">{turn.question}</p>
        )}
      </div>
      {turn.status === 'pending' && (v2 ? <TypingV2 voice={turn.via === 'voice'} /> : <Typing voice={turn.via === 'voice'} />)}
      {turn.status === 'error' && (
        <div role="alert" className="ms-banner ms-banner--warn" data-testid="turn-error">
          <span className="ws-wrap">{turn.error}</span>
          {turn.offerRecordedVoice && (
            <button type="button" className="ms-btn ms-btn--secondary mt-2" style={{ height: 40 }} onClick={onRecordedVoice}>
              Open the recorded voice run
            </button>
          )}
        </div>
      )}
      {turn.status === 'done' && turn.resp && (
        <>
          {turn.via === 'voice' && turn.resp.heard && <span className="sr-only">Heard: {turn.resp.heard}</span>}
          {v2 ? (
            <AnswerTurn resp={turn.resp} onAsk={onAsk} onOpen={onOpen} saveResearch={chat.saveResearch} rating={rating} readKey={readKey(turn.id)} />
          ) : (
            <Answer turn={turn} chat={chat} onAsk={onAsk} onOpen={onOpen} />
          )}
        </>
      )}
    </article>
  )
}

/** The conversation: your questions as bubbles, a typing indicator with the live steps, then the checked answer. */
export function LiveChatView({ chat, threads, onStarter, onRecordedVoice, onRecordedLabel, onOpen, layout, rating }: {
  chat: Chat
  threads: Thread[]
  onStarter: (q: string) => void
  onRecordedVoice: () => void
  /** A photo turn that failed offers the stored label runs. */
  onRecordedLabel?: () => void
  /** Opens a page an answer points to (Check any device type, Our devices, the AI sweep). */
  onOpen?: (o: OpenView) => void
  /** Test hook: forces the layout (default: ?layout= then VITE_LAYOUT_DEFAULT, see layoutFlag.ts). */
  layout?: LayoutMode
  /** Test hook (v2): where thumbs up / down are sent. */
  rating?: RatingSink
}) {
  const [v2] = useState(() => (layout ?? layoutMode()) === 'v2')
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: 'end' })
  }, [chat.turns.length, chat.turns.map((t) => t.status).join()])
  const starters = ['01-what-changed', '05-capa-need-evidence', '10-recalls']
    .map((id) => threads.find((t) => t.id === id))
    .filter((t): t is Thread => !!t)
  return (
    <div className="space-y-6" data-testid="live-chat">
      <div>
        <p className="ms-kicker">Live</p>
        <h1 className="t-title-lg m-0">Ask Muse Spark</h1>
        <p className="mt-1 max-w-xl text-ink-2">
          Type a question or press the mic. Greetings and simple lookups are answered directly at no cost; open questions go to Muse Spark. Every FDA
          fact passes the claim gate before you see it.
        </p>
        <p className="m-0 mt-2 flex flex-wrap items-center gap-2">
          {speechSupported() && (
            <button
              type="button"
              className="ms-btn ms-btn--secondary"
              style={{ height: 40 }}
              aria-pressed={chat.speaker}
              onClick={() => chat.setSpeaker(!chat.speaker)}
              data-testid="speaker-toggle"
            >
              <Icon name="mic" size={16} /> Speaker {chat.speaker ? 'on' : 'off'}
            </button>
          )}
          {chat.speakingId !== null && (
            <button type="button" className="ms-btn ms-btn--secondary" style={{ height: 40 }} onClick={chat.stopSpeech} data-testid="stop-speech">
              Stop reading
            </button>
          )}
          {chat.turns.length > 0 && (
            <button type="button" className="ms-btn ms-btn--secondary" style={{ height: 40 }} onClick={chat.clear}>
              Clear conversation
            </button>
          )}
        </p>
        <p className="m-0 mt-2 text-[15px] text-ink-2" data-testid="voice-note">
          {VOICE_NOTE}
        </p>
      </div>
      {chat.limitReached && (
        <p role="status" className="ms-banner ms-banner--warn m-0" data-testid="limit-banner">
          <span className="ws-wrap">{LIMIT_TEXT}</span>
        </p>
      )}
      {chat.micNotice && (
        <p role="alert" className="ms-banner ms-banner--warn m-0">
          <span className="ws-wrap">{chat.micNotice}</span>
        </p>
      )}
      {chat.turns.length === 0 && starters.length > 0 && (
        <div>
          <h2 className="ms-kicker">Try one of these</h2>
          <ul className="m-0 mt-1 list-none p-0">
            {starters.map((t) => (
              <li key={t.id}>
                <button type="button" className="ws-side-item items-start border-b border-rule" onClick={() => onStarter(t.question)}>
                  <span className="ws-wrap">{t.question}</span>
                  <Icon name="chevron" size={18} />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div role="log" aria-live="polite" aria-label="Conversation" className="space-y-8">
        {chat.turns.map((t) => (
          v2 ? (
            <TurnView key={t.id} turn={t} chat={chat} onRecordedVoice={onRecordedVoice} onRecordedLabel={onRecordedLabel} onAsk={onStarter} onOpen={onOpen} v2 rating={rating} />
          ) : (
            <TurnView key={t.id} turn={t} chat={chat} onRecordedVoice={onRecordedVoice} onRecordedLabel={onRecordedLabel} onAsk={onStarter} onOpen={onOpen} />
          )
        ))}
      </div>
      <div ref={end} />
    </div>
  )
}
