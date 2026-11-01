// The chat screen chrome (v2): an empty chat is one greeting line and a few suggestion chips above the message box;
// a chat with turns is the conversation column. The turns themselves come from ChatTurnSlot.
import { Component, useEffect, useRef, type ErrorInfo, type ReactNode } from 'react'
import { LIMIT_TEXT, VOICE_NOTE, type OpenView } from '../live/api'
import type { LiveChat } from '../live/useLiveChat'
import type { Thread } from '../types'
import { ChatTurn } from './ChatTurnSlot'

/** Suggestion chips of an empty chat: stored questions, in this order, when they exist. */
export const CHIP_THREADS = ['01-what-changed', '10-recalls', '05-capa-need-evidence']
export const GREETING = 'What would you like to check today?'
/** "Questions left" is shown only from this many down. */
export const LEFT_FROM = 5

export function chipQuestions(threads: Thread[]): string[] {
  return CHIP_THREADS.map((id) => threads.find((t) => t.id === id)?.question)
    .filter((q): q is string => !!q)
    .slice(0, 3)
}

/** Live questions left today, from the newest answer that arrived in this page; null when unknown or more than LEFT_FROM. */
export function questionsLeft(chat: Pick<LiveChat, 'remaining'>): number | null {
  const n = chat.remaining
  return typeof n === 'number' && n <= LEFT_FROM ? n : null
}

/**
 * A saved chat that cannot be drawn (an answer the view cannot read) shows this instead of a blank page, with a way
 * out: delete that chat, or start a new one.
 */
export class ChatBoundary extends Component<
  { resetKey: string; onDelete: (() => void) | null; onNewChat: () => void; children: ReactNode },
  { failed: boolean; key: string }
> {
  state = { failed: false, key: this.props.resetKey }
  static getDerivedStateFromError(): Partial<{ failed: boolean }> {
    return { failed: true }
  }
  static getDerivedStateFromProps(p: { resetKey: string }, s: { failed: boolean; key: string }) {
    return p.resetKey !== s.key ? { failed: false, key: p.resetKey } : null
  }
  componentDidCatch(e: Error, info: ErrorInfo): void {
    console.error('chat could not be shown', e, info.componentStack)
  }
  render(): ReactNode {
    if (!this.state.failed) return this.props.children
    return (
      <div className="ms2-empty" role="alert" data-testid="chat-broken">
        <h1 className="ms2-h1">This chat could not be shown</h1>
        <p className="ms2-muted m-0">Part of it was saved in a form this page cannot read.</p>
        <p className="m-0 flex flex-wrap gap-2">
          {this.props.onDelete && (
            <button type="button" className="ms-btn ms-btn--secondary" style={{ height: 44 }} onClick={this.props.onDelete} data-testid="broken-delete">
              Delete this chat
            </button>
          )}
          <button type="button" className="ms-btn ws-btn-primary" style={{ height: 44 }} onClick={this.props.onNewChat} data-testid="broken-new">
            New chat
          </button>
        </p>
      </div>
    )
  }
}

export function ChatScreen({
  chat,
  threads,
  missing,
  onAsk,
  onNewChat,
  onRecordedVoice,
  onRecordedLabel,
  onOpen,
}: {
  chat: LiveChat
  threads: Thread[]
  /** The address names a chat that is not saved on this device. */
  missing: boolean
  onAsk: (q: string) => void
  onNewChat: () => void
  onRecordedVoice: () => void
  onRecordedLabel: () => void
  onOpen: (o: OpenView) => void
}) {
  const end = useRef<HTMLDivElement>(null)
  const statuses = chat.turns.map((t) => t.status).join()
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: 'end' })
  }, [chat.turns.length, statuses])

  if (missing && chat.turns.length === 0)
    return (
      <div className="ms2-empty" data-testid="chat-missing">
        <h1 className="ms2-h1">This chat is not on this device</h1>
        <p className="ms2-muted">Chats are saved in this browser only. It may have been deleted, or saved in another browser.</p>
        <button type="button" className="ms-btn ws-btn-primary" style={{ height: 44 }} onClick={onNewChat}>
          New chat
        </button>
      </div>
    )

  const chips = chipQuestions(threads)
  return (
    <div className="ms2-chat" data-testid="chat-screen">
      {chat.turns.length === 0 ? (
        <div className="ms2-empty" data-testid="chat-empty">
          <h1 className="ms2-greeting">{GREETING}</h1>
          {chips.length > 0 && (
            <ul className="ms2-chips" aria-label="Suggested questions">
              {chips.map((q) => (
                <li key={q}>
                  <button type="button" className="ms2-chip" onClick={() => onAsk(q)} data-testid="empty-chip">
                    {q}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <h1 className="sr-only">Chat</h1>
      )}
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
      {chat.turns.length > 0 && (
        <div role="log" aria-live="polite" aria-label="Conversation" className="space-y-8" data-testid="live-chat">
          {chat.turns.map((t) => (
            <ChatTurn key={t.id} turn={t} chat={chat} onRecordedVoice={onRecordedVoice} onRecordedLabel={onRecordedLabel} onAsk={onAsk} onOpen={onOpen} />
          ))}
        </div>
      )}
      {chat.speakingId !== null && (
        <p className="m-0">
          <button type="button" className="ms-btn ms-btn--secondary" style={{ height: 40 }} onClick={chat.stopSpeech} data-testid="stop-speech">
            Stop reading
          </button>
        </p>
      )}
      <div ref={end} />
    </div>
  )
}

/** The line above the message box: questions left (only from 5 down) and, while recording, the audio note. */
export function ComposerNote({ left, recording }: { left: number | null; recording: boolean }) {
  if (left === null && !recording) return null
  return (
    <div className="ms2-composer-note" role="status" aria-live="polite">
      {recording && (
        <p className="m-0" data-testid="voice-note">
          {VOICE_NOTE}
        </p>
      )}
      {left !== null && (
        <p className="m-0" data-testid="questions-left">
          {left} live {left === 1 ? 'question' : 'questions'} left today
        </p>
      )}
    </div>
  )
}
