import { useMemo, useState } from 'react'
import { apiBaseFrom, PHOTO_WARNING, UNCONFIGURED_TEXT, VOICE_WARNING, type CaptureMode } from '../capture'
import { Icon } from '../icons'
import { MAX_SECONDS } from '../live/audio'
import { blobToWav, type Recorder } from '../live/useRecorder'
import { buildLabelTrace, buildThreadTrace } from '../trace'
import type { LabelReading, Thread, WorkspaceData } from '../types'
import { CameraPanel } from './CameraPanel'
import { RecordingBar } from './RecordingBar'
import { TraceView } from './TraceView'
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

function LabelCard({ l, image }: { l: LabelReading; image?: string }) {
  const trace = useMemo(() => buildLabelTrace(l), [l])
  const fields = Object.entries(l.fields).filter(([, f]) => f.value)
  return (
    <article className="mt-3 rounded-md border border-rule bg-surface p-4" data-testid="label-recorded">
      <p className="m-0 flex flex-wrap items-center gap-2">
        <Tag live={false} />
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

/** What the voice screen needs from the live chat and the recorder. Absent when the build has no API. */
export interface VoiceLive {
  recorder: Recorder
  /** Sends a 16 kHz mono WAV (recorded or converted from an uploaded file). */
  onWav: (wav: Blob) => void
  /** Plain-words reason the mic could not be used. */
  notice: string | null
}

interface Props {
  mode: CaptureMode
  data: WorkspaceData
  onThread: (id: string) => void
  onLabel: (index: number) => void
  /** Test hook: replaces the network call. */
  fetcher?: (url: string, init?: RequestInit) => Promise<Response>
  apiBase?: string | null
  voice?: VoiceLive | null
}

/**
 * Camera (a photo of a device label) or mic (a spoken question). Live reading needs the API; without it, or when it
 * cannot be used (no permission, daily limit), the recorded examples from the stored data are shown, labelled "Recorded run".
 */
export function CaptureView({ mode, data, onThread, onLabel, fetcher, apiBase, voice }: Props) {
  const base_ = apiBase === undefined ? API_BASE : apiBase
  const [labelIdx, setLabelIdx] = useState(0)
  const [fileProblem, setFileProblem] = useState<string | null>(null)

  const voiceThreads = data.threads.threads.filter(
    (t) => t.voice && (t.tool_steps.length > 0 || t.sentences.some((s) => s.claims.length > 0)),
  )
  const [voiceIdx, setVoiceIdx] = useState(0)
  const voiceThread: Thread | undefined = voiceThreads[Math.min(voiceIdx, Math.max(0, voiceThreads.length - 1))]
  const labels = data.vision.labels
  const label = labels[Math.min(labelIdx, Math.max(0, labels.length - 1))]

  const isLabel = mode === 'label'
  const noApi = !base_
  const btn = 'w-full sm:w-auto'

  const onAudioFile = async (f: File | undefined) => {
    if (!f || !voice) return
    setFileProblem(null)
    if (f.size === 0) return setFileProblem('That file is empty.')
    if (!f.type.startsWith('audio/') && !f.type.startsWith('video/webm')) return setFileProblem('That file is not audio.')
    try {
      voice.onWav((await blobToWav(f)).wav)
    } catch {
      setFileProblem('That audio file could not be read by this browser. Try a WAV or MP3 file.')
    }
  }

  return (
    <div>
      <p className="ms-kicker">{isLabel ? 'Camera' : 'Mic'}</p>
      <h1 className="t-title-lg m-0">{isLabel ? 'Read a device label' : 'Ask by voice'}</h1>
      <p className="mt-1 max-w-xl text-ink-2">
        {isLabel
          ? 'Photograph or upload a device label. SAM 3.1 finds it, Muse Spark reads it, and the K-number and GTIN are checked against openFDA. You confirm any match.'
          : 'Talk to it: the question is transcribed, then Muse Spark answers from stored records and every sentence passes the claim gate. The answer is read aloud.'}
      </p>

      {isLabel ? (
        noApi ? (
          <>
            <Warning text={PHOTO_WARNING} />
            <p className="m-0 mt-3 text-[16px] leading-snug text-ink-2" role="status" data-testid="no-api">
              {UNCONFIGURED_TEXT}
            </p>
          </>
        ) : (
          <CameraPanel apiBase={base_} fetcher={fetcher} />
        )
      ) : (
        <>
          <Warning text={VOICE_WARNING} />
          {noApi || !voice ? (
            <p className="m-0 mt-3 text-[16px] leading-snug text-ink-2" role="status" data-testid="no-api">
              {UNCONFIGURED_TEXT}
            </p>
          ) : (
            <>
              <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
                <button
                  type="button"
                  className={`ms-btn ws-btn-primary ${btn}`}
                  style={{ height: 48 }}
                  aria-pressed={voice.recorder.state === 'recording'}
                  disabled={voice.recorder.state === 'processing'}
                  onClick={voice.recorder.toggle}
                  data-testid="record"
                >
                  <Icon name="mic" size={18} /> {voice.recorder.state === 'recording' ? 'Stop and send' : 'Record a question'}
                </button>
                <label className={`ms-btn ms-btn--secondary cursor-pointer ${btn}`} style={{ height: 48 }}>
                  <Icon name="upload" size={18} /> Upload an audio file
                  <input
                    type="file"
                    accept="audio/*"
                    className="sr-only"
                    data-testid="audio-input"
                    aria-label="Upload an audio file with a question"
                    onChange={(e) => {
                      void onAudioFile(e.target.files?.[0])
                      e.target.value = ''
                    }}
                  />
                </label>
              </div>
              <p className="m-0 mt-2 text-[15px] text-ink-2">Click once to start and again to stop; it stops by itself after {MAX_SECONDS} seconds.</p>
              <div className="mt-2">
                <RecordingBar rec={voice.recorder} />
              </div>
              {fileProblem && (
                <p role="alert" className="ms-banner ms-banner--err mt-2">
                  <span className="ws-wrap">{fileProblem}</span>
                </p>
              )}
              {voice.notice && (
                <p role="alert" className="ms-banner ms-banner--warn mt-2" data-testid="mic-notice">
                  <span className="ws-wrap">{voice.notice}</span>
                </p>
              )}
            </>
          )}
        </>
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
            <LabelCard l={label} image={dataUrl(label.image)} />
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
