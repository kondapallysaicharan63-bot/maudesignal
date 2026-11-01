// The conversation state: typed and spoken turns, history for the next question, and the fall back to stored runs.
// Nothing here stores a question, an answer, audio or a photo outside this page's memory; a reload starts clean.
import { useCallback, useRef, useState } from 'react'
import type { Evidence, Thread } from '../types'
import {
  answerText,
  checkQuestion,
  LIMIT_TEXT,
  LiveError,
  postAsk,
  postLabel,
  postResearchSave,
  postTranscribe,
  postVoice,
  type AskResponse,
  type LabelResponse,
  type ResearchItem,
  type SaveOutcome,
  type TranscribeResult,
  type Turn,
} from './api'
import { recordedFor } from './recorded'
import { speak, stopSpeaking } from './speech'

type Fetcher = (url: string, init?: RequestInit) => Promise<Response>

export interface LiveTurn {
  id: number
  via: 'text' | 'voice' | 'photo'
  /** The question as typed, or as heard for a voice turn (null until the transcript arrives). */
  question: string | null
  status: 'pending' | 'done' | 'error'
  resp?: AskResponse
  /** Shown instead of an answer: a server message (patient data, bad input) or why nothing could be asked. */
  error?: string
  /** A voice turn that fell back: offer the stored voice run. */
  offerRecordedVoice?: boolean
  /** A photo turn: the picture as sent (an object URL in this page only) and the label reading. */
  image?: string
  label?: LabelResponse
  /** A photo turn that failed: offer the stored label runs. */
  offerRecordedLabel?: boolean
  /** A photo turn: the words typed with the photo, asked after the reading (shown in the bubble). */
  followUp?: string
}

export interface LiveChat {
  enabled: boolean
  turns: LiveTurn[]
  busy: boolean
  limitReached: boolean
  speaker: boolean
  setSpeaker: (on: boolean) => void
  speakingId: number | null
  /** Reads one answer aloud now. */
  readAloud: (id: number) => void
  stopSpeech: () => void
  /** Plain-words reason the microphone or a recording could not be used (shown on the voice screen). */
  micNotice: string | null
  setMicNotice: (m: string | null) => void
  /** Returns a message when the question was refused before sending (too short or too long), otherwise null. */
  ask: (q: string, o?: { productCode?: string | null; research?: boolean }) => string | null
  askVoice: (wav: Blob) => Promise<void>
  /**
   * A label photo sent from the message box: one turn with the picture and the reading. Words typed with it are asked
   * after the reading returns, with the top match's product code when it has one (otherwise as typed).
   */
  askPhoto: (image: Blob, followUp?: { question: string; research?: boolean } | null) => void
  /** The words of a recording only (nothing is asked): they go into the message box for editing. */
  transcribe: (wav: Blob) => Promise<TranscribeResult>
  /** Saves one web-research item to the audit trail ('unsupported' when the server has no such route). */
  saveResearch: (item: ResearchItem) => Promise<SaveOutcome>
  clear: () => void
  /**
   * Shows a saved conversation (v2 layout: a chat reopened from Recents, or [] for a new chat). Nothing is sent; the
   * daily-limit state is kept. Answers still on their way for the turns that were on screen go to `onBackground`.
   */
  restore: (turns: LiveTurn[], reserveUpTo?: number) => void
}

interface Options {
  apiBase: string | null
  ref: string | null
  threads: Thread[]
  evidence: Evidence
  fetcher?: Fetcher
  /** A turn that is no longer on screen (another chat was opened) changed: its answer arrived. v2 saves it to its chat. */
  onBackground?: (id: number, p: Partial<LiveTurn>) => void
}

let nextId = 1

/** The product code a question about a label photo is asked with: the top match's, when it is a proper code. */
export function productCodeOf(label: LabelResponse): string | null {
  const c = label.matches.candidates[0]?.product_code?.trim().toUpperCase() ?? ''
  return /^[A-Z]{3}$/.test(c) ? c : null
}

export function useLiveChat(o: Options): LiveChat {
  const [turns, setTurns] = useState<LiveTurn[]>([])
  const [limitReached, setLimit] = useState(false)
  const [speaker, setSpeaker] = useState(true)
  const [speakingId, setSpeakingId] = useState<number | null>(null)
  const [micNotice, setMicNotice] = useState<string | null>(null)
  const turnsRef = useRef<LiveTurn[]>([])
  const limitRef = useRef(false)
  const speakerRef = useRef(true)
  const opts = useRef(o)
  opts.current = o
  speakerRef.current = speaker

  const put = useCallback((next: LiveTurn[]) => {
    turnsRef.current = next
    setTurns(next)
  }, [])
  const patch = useCallback(
    (id: number, p: Partial<LiveTurn>) => {
      if (!turnsRef.current.some((t) => t.id === id)) {
        opts.current.onBackground?.(id, p)
        return
      }
      put(turnsRef.current.map((t) => (t.id === id ? { ...t, ...p } : t)))
    },
    [put],
  )

  const history = (): Turn[] =>
    turnsRef.current
      .filter((t) => t.status === 'done' && t.question && t.resp)
      .map((t) => ({ question: t.question as string, answer: answerText(t.resp!.answer) }))

  const fetcher: Fetcher = useCallback((u, i) => (opts.current.fetcher ?? ((a, b) => fetch(a, b)))(u, i), [])

  const say = useCallback((id: number, text: string) => {
    const ok = speak(text, { onStart: () => setSpeakingId(id), onEnd: () => setSpeakingId((c) => (c === id ? null : c)) })
    if (!ok) setSpeakingId(null)
  }, [])

  const ask = useCallback(
    (raw: string, ask?: { productCode?: string | null; research?: boolean }): string | null => {
      let q: string
      try {
        q = checkQuestion(raw)
      } catch (e) {
        return (e as Error).message
      }
      const id = nextId++
      const past = history()
      put([...turnsRef.current, { id, via: 'text', question: q, status: 'pending' }])
      const { apiBase, ref, threads, evidence } = opts.current
      const recorded = (why: string) => patch(id, { status: 'done', resp: recordedFor(q, threads, evidence, why) })
      if (limitRef.current) {
        recorded(LIMIT_TEXT + '.')
        return null
      }
      postAsk(q, { history: past, ref, productCode: ask?.productCode ?? null, research: ask?.research === true }, { apiBase, fetcher })
        .then((resp) => patch(id, { status: 'done', resp }))
        .catch((e: unknown) => {
          const err = e instanceof LiveError ? e : new LiveError('network', 'The live service could not be reached.')
          if (err.kind === 'rate_limited') {
            limitRef.current = true
            setLimit(true)
            recorded(LIMIT_TEXT + '.')
          } else if (err.kind === 'patient_data' || err.kind === 'invalid_input') patch(id, { status: 'error', error: err.message })
          else recorded(`${err.message}`)
        })
      return null
    },
    [fetcher, patch, put], // eslint-disable-line react-hooks/exhaustive-deps
  )

  const askVoice = useCallback(
    async (wav: Blob): Promise<void> => {
      const id = nextId++
      const past = history()
      put([...turnsRef.current, { id, via: 'voice', question: null, status: 'pending' }])
      const { apiBase } = opts.current
      if (limitRef.current) {
        patch(id, { status: 'error', error: `${LIMIT_TEXT}. A spoken question needs the live service; the stored voice run is available.`, offerRecordedVoice: true })
        return
      }
      try {
        const resp = await postVoice(wav, { history: past }, { apiBase, fetcher })
        patch(id, { status: 'done', question: resp.heard ?? null, resp })
        if (speakerRef.current && resp.answer.spoken_text) say(id, resp.answer.spoken_text)
      } catch (e) {
        const err = e instanceof LiveError ? e : new LiveError('network', 'The live service could not be reached.')
        if (err.kind === 'rate_limited') {
          limitRef.current = true
          setLimit(true)
          patch(id, { status: 'error', error: `${LIMIT_TEXT}. A spoken question needs the live service; the stored voice run is available.`, offerRecordedVoice: true })
        } else if (err.kind === 'patient_data' || err.kind === 'invalid_input') patch(id, { status: 'error', error: err.message })
        else patch(id, { status: 'error', error: `${err.message} The stored voice run is available.`, offerRecordedVoice: true })
      }
    },
    [fetcher, patch, put, say], // eslint-disable-line react-hooks/exhaustive-deps
  )

  const askPhoto = useCallback(
    (image: Blob, followUp?: { question: string; research?: boolean } | null): void => {
      const id = nextId++
      const url = typeof URL.createObjectURL === 'function' ? URL.createObjectURL(image) : undefined
      put([...turnsRef.current, { id, via: 'photo', question: null, status: 'pending', image: url, ...(followUp ? { followUp: followUp.question } : {}) }])
      const { apiBase } = opts.current
      const thenAsk = (code: string | null) => {
        if (followUp) ask(followUp.question, { productCode: code, research: followUp.research === true })
      }
      postLabel(image, { apiBase, fetcher })
        .then((label) => {
          patch(id, { status: 'done', label })
          thenAsk(productCodeOf(label))
        })
        .catch((e: unknown) => {
          thenAsk(null)
          const err = e instanceof LiveError ? e : new LiveError('network', 'The live service could not be reached.')
          if (err.kind === 'rate_limited') patch(id, { status: 'error', error: `${LIMIT_TEXT}. The recorded label runs are available.`, offerRecordedLabel: true })
          else if (err.kind === 'patient_data' || err.kind === 'invalid_input' || err.kind === 'too_large') patch(id, { status: 'error', error: err.message })
          else patch(id, { status: 'error', error: `${err.message} The recorded label runs are available.`, offerRecordedLabel: true })
        })
    },
    [ask, fetcher, patch, put],
  )

  const transcribe = useCallback(
    (wav: Blob): Promise<TranscribeResult> => postTranscribe(wav, {}, { apiBase: opts.current.apiBase, fetcher }),
    [fetcher],
  )

  const saveResearch = useCallback(
    (item: ResearchItem): Promise<SaveOutcome> => postResearchSave(item, { apiBase: opts.current.apiBase, fetcher }),
    [fetcher],
  )

  const readAloud = useCallback(
    (id: number) => {
      const t = turnsRef.current.find((x) => x.id === id)
      if (t?.resp?.answer.spoken_text) say(id, t.resp.answer.spoken_text)
    },
    [say],
  )
  const stopSpeech = useCallback(() => {
    stopSpeaking()
    setSpeakingId(null)
  }, [])
  const clear = useCallback(() => {
    stopSpeaking()
    setSpeakingId(null)
    limitRef.current = false
    setLimit(false)
    turnsRef.current.forEach((t) => t.image && typeof URL.revokeObjectURL === 'function' && URL.revokeObjectURL(t.image))
    put([])
  }, [put])
  const restore = useCallback(
    (next: LiveTurn[], reserveUpTo = 0) => {
      stopSpeaking()
      setSpeakingId(null)
      // Turn ids stay unique in this page: new turns are numbered after every restored one (and after reserveUpTo).
      if (reserveUpTo >= nextId) nextId = reserveUpTo + 1
      for (const t of next) if (t.id >= nextId) nextId = t.id + 1
      put(next)
    },
    [put],
  )

  return {
    enabled: !!o.apiBase,
    turns,
    busy: turns.some((t) => t.status === 'pending'),
    limitReached,
    speaker,
    setSpeaker: (on) => {
      setSpeaker(on)
      if (!on) {
        stopSpeaking()
        setSpeakingId(null)
      }
    },
    speakingId,
    readAloud,
    stopSpeech,
    micNotice,
    setMicNotice,
    ask,
    askVoice,
    askPhoto,
    transcribe,
    saveResearch,
    clear,
    restore,
  }
}

/** The switched-off conversation (no API address): nothing is sent, nothing is kept. */
export const NO_LIVE: LiveChat = {
  enabled: false,
  turns: [],
  busy: false,
  limitReached: false,
  speaker: false,
  setSpeaker: () => undefined,
  speakingId: null,
  readAloud: () => undefined,
  stopSpeech: () => undefined,
  micNotice: null,
  setMicNotice: () => undefined,
  ask: () => 'The live service is not connected in this build.',
  askVoice: async () => undefined,
  askPhoto: () => undefined,
  transcribe: () => Promise.reject(new LiveError('not_configured', 'The live service is not connected in this build.')),
  saveResearch: async () => 'unsupported',
  clear: () => undefined,
  restore: () => undefined,
}
