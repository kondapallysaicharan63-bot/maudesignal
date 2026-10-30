import { useEffect, useMemo, useRef, useState } from 'react'
import {
  apiBaseFrom,
  checkFile,
  FAILURE_TEXT,
  MAX_RECORD_SECONDS,
  PHOTO_WARNING,
  sendCapture,
  VOICE_WARNING,
  type CaptureMode,
  type CaptureOutcome,
  type LiveStep,
  type PickedFile,
} from '../capture'
import { Icon } from '../icons'
import { buildLabelTrace, buildThreadTrace } from '../trace'
import type { LabelReading, Thread, WorkspaceData } from '../types'
import { TraceView } from './TraceView'
import { ThreadView } from './ThreadView'
import { labelName } from './VisionWorkflow'

/** The API base is fixed when the site is built (VITE_MAUDESIGNAL_API_BASE); empty means no live reading here. */
const API_BASE = apiBaseFrom(import.meta.env.VITE_MAUDESIGNAL_API_BASE)

const base = import.meta.env.BASE_URL
const dataUrl = (p: string) => `${base}data/${p}`

const K_STATUS: Record<string, string> = {
  not_printed: 'no K-number printed',
  verified: 'K-number found in openFDA',
  illegible: 'K-number illegible',
  bad_format: 'printed text is not a K-number',
  not_in_openfda: 'K-number not found in openFDA',
}

function Tag({ live }: { live: boolean }) {
  return (
    <span className={`ws-pill ${live ? 'bg-success-soft text-success' : 'bg-warning-soft text-warning'}`}>
      {live ? 'Live result' : 'Recorded run'}
    </span>
  )
}

function Warning({ text }: { text: string }) {
  return (
    <p
      className="mt-3 flex gap-2 rounded-md border border-rule-strong bg-surface px-3 py-2 text-[16px] leading-snug text-ink"
      data-testid="patient-warning"
    >
      <Icon name="info" size={20} />
      <span className="ws-wrap font-semibold">{text}</span>
    </p>
  )
}

function LabelCard({ l, live, image, note }: { l: LabelReading; live: boolean; image?: string; note?: string }) {
  const trace = useMemo(() => buildLabelTrace(l), [l])
  const fields = Object.entries(l.fields).filter(([, f]) => f.value)
  return (
    <article className="mt-3 rounded-md border border-rule bg-surface p-4" data-testid={live ? 'label-live' : 'label-recorded'}>
      <p className="m-0 flex flex-wrap items-center gap-2">
        <Tag live={live} />
        {note && <span className="text-[15px] text-ink-2">{note}</span>}
      </p>
      <h3 className="t-title-lg ws-wrap m-0 mt-2" style={{ fontSize: 20 }}>
        {labelName(l)}
      </h3>
      {image && (
        <img
          src={image}
          alt="Recorded example device-label photo"
          className="mt-3 max-h-64 w-auto max-w-full rounded-xs border border-rule"
        />
      )}
      <p className="ws-wrap m-0 mt-2 text-ink-2">
        {K_STATUS[l.k_status] ?? l.k_status}
        {l.k_number ? ` (${l.k_number})` : ''} · {l.sam.boxes.length} label {l.sam.boxes.length === 1 ? 'box' : 'boxes'} found
      </p>
      {fields.length > 0 && (
        <dl className="m-0 mt-2 text-[15px]">
          {fields.map(([k, f]) => (
            <div key={k} className="flex flex-wrap justify-between gap-x-3 border-t border-rule py-1.5">
              <dt className="text-ink-2">{k.replace(/_/g, ' ')}</dt>
              <dd className="ws-wrap m-0 text-right">{f.value}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className="mt-3">
        <TraceView trace={trace} shown={99} replayed={false} label="Label reading steps" />
      </div>
    </article>
  )
}

/** One recorded sample in a vertical list: "Sample 1" and the sample's own text, at least 44px high. */
function SampleButton({ on, n, text, onClick }: { on: boolean; n: number; text: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={[
        'flex min-h-11 w-full items-start gap-2 rounded-xs border px-3 py-2 text-left text-[16px] leading-snug text-ink',
        on ? 'border-accent bg-accent-soft shadow-[inset_4px_0_0_var(--accent)]' : 'border-rule hover:bg-sunk',
      ].join(' ')}
    >
      <span className="shrink-0 font-semibold">Sample {n}</span>
      <span className="ws-wrap line-clamp-2 min-w-0 flex-1 text-ink-2">{text}</span>
    </button>
  )
}

function Steps({ steps }: { steps: LiveStep[] }) {
  if (steps.length === 0) return null
  return (
    <ol className="m-0 mt-2 list-none space-y-1 p-0 text-[15px] text-ink-2" aria-label="Steps as they arrive" aria-live="polite">
      {steps.map((s, i) => (
        <li key={i}>
          <span className="ms-code">{s.name}</span> <span className="ws-wrap">{s.summary}</span>
        </li>
      ))}
    </ol>
  )
}

interface Props {
  mode: CaptureMode
  data: WorkspaceData
  onThread: (id: string) => void
  onLabel: (index: number) => void
  /** Test hook: replaces the network call. */
  fetcher?: (url: string, init?: RequestInit) => Promise<Response>
  apiBase?: string | null
}

/**
 * Camera (a photo of a device label) or mic (a spoken question). Live reading needs the API; until it answers, the
 * recorded examples from the stored data are shown and labelled "Recorded run", with the reason.
 */
export function CaptureView({ mode, data, onThread, onLabel, fetcher, apiBase }: Props) {
  const base_ = apiBase === undefined ? API_BASE : apiBase
  const [picked, setPicked] = useState<PickedFile | null>(null)
  const [busy, setBusy] = useState(false)
  const [outcome, setOutcome] = useState<CaptureOutcome | null>(null)
  const [steps, setSteps] = useState<LiveStep[]>([])
  const [problem, setProblem] = useState<string | null>(null)
  const [rec, setRec] = useState<'idle' | 'recording'>('idle')
  const [labelIdx, setLabelIdx] = useState(0)
  const recorder = useRef<MediaRecorder | null>(null)
  const stopTimer = useRef<number | null>(null)

  // A different mode is a different screen: start clean.
  useEffect(() => {
    setPicked(null)
    setOutcome(null)
    setSteps([])
    setProblem(null)
  }, [mode])
  useEffect(
    () => () => {
      if (stopTimer.current) window.clearTimeout(stopTimer.current)
      if (recorder.current && recorder.current.state !== 'inactive') recorder.current.stop()
    },
    [],
  )

  const voiceThreads = data.threads.threads.filter(
    (t) => t.voice && (t.tool_steps.length > 0 || t.sentences.some((s) => s.claims.length > 0)),
  )
  const [voiceIdx, setVoiceIdx] = useState(0)
  const voiceThread: Thread | undefined = voiceThreads[Math.min(voiceIdx, Math.max(0, voiceThreads.length - 1))]
  const labels = data.vision.labels
  const label = labels[Math.min(labelIdx, Math.max(0, labels.length - 1))]

  const choose = (f: File | undefined) => {
    setOutcome(null)
    setSteps([])
    if (!f) return
    const bad = checkFile(mode, f)
    if (bad) {
      setPicked(null)
      setProblem(FAILURE_TEXT[bad])
      return
    }
    setProblem(null)
    setPicked({ blob: f, name: f.name || (mode === 'label' ? 'label.jpg' : 'question.webm') })
  }

  const send = async () => {
    if (!picked || busy) return
    setBusy(true)
    setSteps([])
    const out = await sendCapture(mode, picked, {
      apiBase: base_,
      fetcher: fetcher ?? ((u, i) => fetch(u, i)),
      onStep: (s) => setSteps((c) => [...c, s]),
    })
    setOutcome(out)
    setBusy(false)
  }

  const startRecording = async () => {
    setProblem(null)
    setOutcome(null)
    if (typeof MediaRecorder === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      setProblem('This browser cannot record audio. Choose an audio file instead.')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mr = new MediaRecorder(stream)
      const chunks: Blob[] = []
      mr.ondataavailable = (e) => e.data.size > 0 && chunks.push(e.data)
      mr.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        const type = mr.mimeType || 'audio/webm'
        const blob = new Blob(chunks, { type })
        setRec('idle')
        const bad = checkFile('voice', blob)
        if (bad) setProblem(FAILURE_TEXT[bad])
        else setPicked({ blob, name: `question.${type.includes('mp4') ? 'm4a' : type.includes('ogg') ? 'ogg' : 'webm'}` })
      }
      recorder.current = mr
      mr.start()
      setRec('recording')
      stopTimer.current = window.setTimeout(() => mr.state !== 'inactive' && mr.stop(), MAX_RECORD_SECONDS * 1000)
    } catch {
      setProblem('The microphone could not be used (permission denied or no microphone). Choose an audio file instead.')
    }
  }
  const stopRecording = () => {
    if (stopTimer.current) window.clearTimeout(stopTimer.current)
    if (recorder.current && recorder.current.state !== 'inactive') recorder.current.stop()
  }

  const isLabel = mode === 'label'
  const failed = outcome && !outcome.ok ? outcome : null
  const noApi = !base_

  const btn = 'w-full sm:w-auto'
  return (
    <div>
      <p className="ms-kicker">{isLabel ? 'Camera' : 'Mic'}</p>
      <h1 className="t-title-lg m-0">{isLabel ? 'Read a device label' : 'Ask by voice'}</h1>
      <p className="mt-1 max-w-xl text-ink-2">
        {isLabel
          ? 'Photograph or upload a device label. SAM 3.1 finds it, Muse Spark reads it, and the K-number and GTIN are checked.'
          : 'Record or upload a question. It is transcribed, and the copilot answers from stored records; every sentence is checked first.'}
      </p>
      <Warning text={isLabel ? PHOTO_WARNING : VOICE_WARNING} />

      <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
        {isLabel ? (
          <>
            <label className={`ms-btn ws-btn-primary cursor-pointer ${btn}`} style={{ height: 48 }}>
              <Icon name="camera" size={18} /> Take a photo
              <input
                type="file"
                accept="image/*"
                capture="environment"
                className="sr-only"
                data-testid="camera-input"
                onChange={(e) => choose(e.target.files?.[0])}
              />
            </label>
            <label className={`ms-btn ms-btn--secondary cursor-pointer ${btn}`} style={{ height: 48 }}>
              <Icon name="upload" size={18} /> Upload an image
              <input
                type="file"
                accept="image/*"
                className="sr-only"
                data-testid="image-input"
                onChange={(e) => choose(e.target.files?.[0])}
              />
            </label>
          </>
        ) : (
          <>
            {rec === 'idle' ? (
              <button type="button" className={`ms-btn ws-btn-primary ${btn}`} style={{ height: 48 }} onClick={() => void startRecording()}>
                <Icon name="mic" size={18} /> Record a question
              </button>
            ) : (
              <button type="button" className={`ms-btn ws-btn-primary ${btn}`} style={{ height: 48 }} onClick={stopRecording}>
                Stop recording
              </button>
            )}
            <label className={`ms-btn ms-btn--secondary cursor-pointer ${btn}`} style={{ height: 48 }}>
              <Icon name="upload" size={18} /> Upload an audio file
              <input
                type="file"
                accept="audio/*"
                className="sr-only"
                data-testid="audio-input"
                onChange={(e) => choose(e.target.files?.[0])}
              />
            </label>
          </>
        )}
      </div>
      {noApi && !picked && !outcome && !problem && (
        <p className="m-0 mt-2 text-[16px] leading-snug text-ink-2" role="status" data-testid="no-api">
          {FAILURE_TEXT.unconfigured} The recorded run below shows what a reading looks like.
        </p>
      )}
      <p className="m-0 mt-2 text-[16px] text-ink-2" role="status" aria-live="polite">
        {rec === 'recording' ? `Recording... stops by itself after ${MAX_RECORD_SECONDS} seconds.` : ''}
      </p>
      {problem && (
        <p role="alert" className="ms-banner ms-banner--err mt-2">
          <span className="ws-wrap">{problem}</span>
        </p>
      )}
      {picked && !outcome && (
        <div className="mt-3 rounded-md border border-rule-strong bg-surface p-3" data-testid="picked">
          <p className="ws-wrap m-0">
            Ready: <strong>{picked.name}</strong> ({Math.max(1, Math.round(picked.blob.size / 1024)).toLocaleString('en-US')} KB)
          </p>
          <p className="m-0 mt-1 text-[16px] leading-snug text-ink-2">
            {noApi
              ? 'The live API is not connected, so sending shows the recorded run instead.'
              : 'Sending uploads this file to the MaudeSignal API. The server removes the camera metadata (EXIF).'}
          </p>
          <button type="button" className="ms-btn ws-btn-primary mt-2 w-full sm:w-auto" style={{ height: 48 }} disabled={busy} onClick={() => void send()}>
            {busy ? 'Sending…' : isLabel ? 'Send photo' : 'Send recording'}
          </button>
        </div>
      )}
      {busy && <Steps steps={steps} />}

      {failed && (
        <p role="alert" className="ms-banner ms-banner--warn mt-3" data-testid="fallback-reason">
          <span className="ws-wrap">
            <strong>Showing the recorded run instead.</strong> {failed.message}
          </span>
        </p>
      )}

      {outcome && outcome.ok && outcome.mode === 'label' && (
        <>
          <Steps steps={outcome.steps} />
          <LabelCard l={outcome.reading} live note="Read just now by the API." />
        </>
      )}
      {outcome && outcome.ok && outcome.mode === 'voice' && (
        <section className="mt-3" data-testid="voice-live">
          <p className="m-0 flex flex-wrap items-center gap-2">
            <Tag live />
            <span className="text-[15px] text-ink-2">Transcribed just now by the API.</span>
          </p>
          <p className="ws-wrap m-0 mt-2">
            <span className="font-semibold">Heard:</span> &ldquo;{outcome.transcript}&rdquo;
          </p>
          <Steps steps={outcome.steps} />
          {outcome.thread ? (
            <div className="mt-3">
              <ThreadView
                t={outcome.thread}
                ev={data.evidence}
                siblings={[]}
                onThread={onThread}
              />
            </div>
          ) : (
            <p className="m-0 mt-2 text-ink-2">The API returned the transcript only, with no checked answer.</p>
          )}
        </section>
      )}

      <h2 className="ms-kicker mt-6">Recorded run</h2>
      {isLabel ? (
        label ? (
          <>
            <p className="m-0 mt-1 text-[15px] text-ink-2">
              A stored reading of a sample label photo, replayed from a recording. Nothing here was read live.
            </p>
            {labels.length > 1 && (
              <div className="mt-2 flex flex-col gap-2" role="group" aria-label="Recorded label examples">
                {labels.map((l, i) => (
                  <SampleButton key={l.image} on={i === labelIdx} n={i + 1} text={labelName(l)} onClick={() => setLabelIdx(i)} />
                ))}
              </div>
            )}
            <LabelCard l={label} live={false} image={dataUrl(label.image)} />
            <button type="button" className="ms-btn ms-btn--secondary mt-3" onClick={() => onLabel(labelIdx)}>
              Open the full reading
            </button>
          </>
        ) : (
          <p className="mt-2 text-ink-2">No recorded label reading is stored.</p>
        )
      ) : voiceThread ? (
        <section data-testid="voice-recorded">
          <p className="m-0 mt-1 flex flex-wrap items-center gap-2">
            <Tag live={false} />
            <span className="text-[15px] text-ink-2">A stored voice question, replayed from a recording. Nothing was transcribed live.</span>
          </p>
          {voiceThreads.length > 1 && (
            <div className="mt-2 flex flex-col gap-2" role="group" aria-label="Recorded voice questions">
              {voiceThreads.map((t, i) => (
                <SampleButton key={t.id} on={i === voiceIdx} n={i + 1} text={t.voice?.transcript_text ?? t.question} onClick={() => setVoiceIdx(i)} />
              ))}
            </div>
          )}
          <p className="ws-wrap mt-3">
            <span className="font-semibold">Heard:</span> &ldquo;{voiceThread.voice?.transcript_text}&rdquo;
          </p>
          <div className="mt-2">
            <TraceView trace={buildThreadTrace(voiceThread)} shown={99} replayed={false} label="Voice answer steps" />
          </div>
          <button type="button" className="ms-btn ms-btn--secondary mt-3" onClick={() => onThread(voiceThread.id)}>
            Open the recorded answer
          </button>
        </section>
      ) : (
        <p className="mt-2 text-ink-2">No recorded voice question is stored.</p>
      )}
    </div>
  )
}
