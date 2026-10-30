import { useCallback, useEffect, useRef, useState } from 'react'
import { Icon } from '../icons'
import { legibilityBanner } from '../labelMatch'
import { LIMIT_TEXT, LiveError, MAX_SOURCE_BYTES, NOT_MEDICAL_ADVICE, PHOTO_NOTE, postLabel, type Candidate, type LabelResponse } from '../live/api'
import { readingRows } from '../live/label'
import { PHOTO_TOO_BIG_TEXT, PhotoError, cameraErrorText, fileToJpeg, frameToJpeg } from '../live/photo'
import { LiveTrace } from './LiveTrace'

type Fetcher = (url: string, init?: RequestInit) => Promise<Response>

function CandidateCard({ c, rank, total, confirmed, onConfirm, onUndo }: {
  c: Candidate
  rank: number
  total: number
  confirmed: boolean
  onConfirm: () => void
  onUndo: () => void
}) {
  return (
    <li
      data-testid="match-card"
      data-confirmed={confirmed ? 'true' : undefined}
      aria-current={confirmed ? 'true' : undefined}
      className={['mt-3 rounded-md bg-surface p-3', confirmed ? 'border-2 border-success bg-success-soft' : 'border border-rule'].join(' ')}
    >
      <p className="ms-num m-0 text-[17px] font-semibold">
        Possible match {rank} of {total}
        {confirmed && <span className="ws-pill ml-2 bg-success-soft text-success ws-pill--ring">Confirmed</span>}
      </p>
      <p className="ws-wrap m-0 mt-1 text-[19px] font-semibold leading-snug">{c.device_name}</p>
      {confirmed ? (
        <p className="m-0 mt-2 text-[16px]" data-testid="confirmed-block">
          <span className="font-semibold text-success">You confirmed this match.</span>{' '}
          <span className="text-ink-2">Confirmed by you in this browser; not saved.</span>{' '}
          <button type="button" onClick={onUndo} className="min-h-11 text-accent underline" data-testid="undo-confirm">
            Undo
          </button>
        </p>
      ) : (
        <div className="mt-2" data-testid="confirm-row">
          <button type="button" onClick={onConfirm} className="min-h-11 rounded-xs border border-ink bg-sunk px-4 text-[17px] font-semibold text-ink hover:bg-surface">
            Confirm this match
          </button>
        </div>
      )}
      <dl className="m-0 mt-2 grid grid-cols-[7.5rem_1fr] gap-x-3 gap-y-1 text-[17px]">
        <dt className="text-ink-2">Applicant</dt>
        <dd className="ws-wrap m-0">{c.applicant}</dd>
        <dt className="text-ink-2">K-number</dt>
        <dd className="m-0">
          <span className="ms-code">{c.k_number}</span>
        </dd>
        <dt className="text-ink-2">Product code</dt>
        <dd className="m-0">
          <span className="ms-code">{c.product_code}</span>
        </dd>
      </dl>
      {c.why_matched.length > 0 && (
        <div className="mt-3">
          <span className="ws-pill bg-success-soft text-success ws-pill--ring">Why it matched</span>
          <ul className="m-0 mt-1 list-disc pl-5 text-[17px]" data-testid="why-matched">
            {c.why_matched.map((w) => (
              <li key={w} className="ws-wrap">
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}
      {c.why_not_matched.length > 0 && (
        <div className="mt-3 rounded-md border-2 border-warning bg-warning-soft p-2" data-testid="mismatch-block">
          <span className="ws-pill bg-warning-soft text-warning ws-pill--ring">What did not match</span>
          <ul className="m-0 mt-1 list-disc pl-5 text-[17px]" data-testid="why-not-matched">
            {c.why_not_matched.map((w) => (
              <li key={w} className="ws-wrap">
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}
      {c.links.length > 0 && (
        <p className="m-0 mt-3 text-[17px]">
          {c.links.map((l, i) => (
            <span key={l.url}>
              {i > 0 && ' · '}
              <a href={l.url} target="_blank" rel="noreferrer" className="text-accent underline">
                {l.label}
              </a>
            </span>
          ))}
        </p>
      )}
    </li>
  )
}

/** The possible matches of a live reading. Nothing is chosen for the person; a click confirms one, in this page only. */
export function LiveMatches({ res }: { res: LabelResponse }) {
  const [picked, setPicked] = useState<number | null>(null)
  const [none, setNone] = useState(false)
  const cands = res.matches.candidates
  return (
    <section className="mt-4" data-testid="label-matches">
      <h3 className="ms-kicker m-0 !text-[16px]">Possible matches (a person confirms one)</h3>
      {cands.length === 0 ? (
        res.matches.search_failed || res.matches.note ? (
          <div data-testid="search-failed" className="mt-2 rounded-md border-2 border-warning bg-warning-soft p-3">
            <p className="ws-wrap m-0 text-[19px] font-semibold leading-snug" data-testid="search-failed-note">
              {res.matches.note ?? 'openFDA could not be searched, so there is no match result for this photo.'}
            </p>
            <p className="m-0 mt-1 text-[17px] font-semibold" data-testid="search-failed-retry">
              Next step: try again in a minute. A retry uses another of today's live readings.
            </p>
          </div>
        ) : (
          <div data-testid="no-match" className="mt-2 rounded-md border border-rule bg-sunk p-3">
            <p className="m-0 text-[22px] font-semibold leading-snug">No match found</p>
            <p className="m-0 mt-1 text-[17px] font-semibold">Next step: take a clearer photo of the label.</p>
          </div>
        )
      ) : (
        <>
          <p className="m-0 mt-1 text-[17px] text-ink-2">
            Up to three records from openFDA. None is chosen for you; check them against the photo, then confirm one or none.
          </p>
          {!none ? (
            <div className="mt-2" data-testid="none-row">
              <button
                type="button"
                onClick={() => {
                  setNone(true)
                  setPicked(null)
                }}
                className="min-h-11 rounded-xs border border-rule px-3 text-[17px] text-ink-2 hover:bg-sunk"
              >
                None of these
              </button>
            </div>
          ) : (
            <p className="m-0 mt-2 text-[17px]" data-testid="none-note">
              <span className="font-semibold">You chose none of these.</span> <span className="text-[16px] text-ink-2">Only in this browser; not saved.</span>{' '}
              <button type="button" onClick={() => setNone(false)} className="min-h-11 text-accent underline">
                Undo
              </button>
            </p>
          )}
          <ul className="m-0 list-none p-0">
            {cands.map((c, i) => (
              <CandidateCard
                key={`${c.k_number}-${i}`}
                c={c}
                rank={i + 1}
                total={cands.length}
                confirmed={picked === i}
                onConfirm={() => {
                  setPicked(i)
                  setNone(false)
                }}
                onUndo={() => setPicked(null)}
              />
            ))}
          </ul>
        </>
      )}
    </section>
  )
}

/** The reading, the possible matches and the steps of one live label run. */
export function LiveLabelResult({ res }: { res: LabelResponse }) {
  const rows = readingRows(res.reading)
  const banner = legibilityBanner(res.reading.legibility)
  const recorded = res.mode === 'recorded'
  return (
    <article className="mt-3 rounded-md border border-rule bg-surface p-4" data-testid="label-live" data-mode={res.mode}>
      <p className="m-0 flex flex-wrap items-center gap-2">
        <span className={`ws-pill ${recorded ? 'bg-warning-soft text-warning' : 'bg-success-soft text-success'}`} data-testid="mode-badge">
          {recorded ? 'Recorded run' : 'Live result'}
        </span>
        {res.limits && !recorded && (
          <span className="text-[15px] text-ink-2">
            {res.limits.remaining_today} live {res.limits.remaining_today === 1 ? 'reading' : 'readings'} left today
          </span>
        )}
      </p>
      {recorded && res.recorded_note && (
        <p className="ws-wrap m-0 mt-2 text-[16px] text-ink-2" data-testid="recorded-note">
          {res.recorded_note}
        </p>
      )}
      {banner && (
        <p role="status" className="ms-banner ms-banner--warn mt-3" data-testid="legibility-banner">
          <span className="ws-wrap">{banner}</span>
        </p>
      )}
      <p className="m-0 mt-3 text-[16px] text-ink-2">
        Legibility: <strong className="text-ink" data-testid="legibility">{res.reading.legibility.replace(/_/g, " ")}</strong>
      </p>
      <dl className="m-0 mt-2 text-[16px]" data-testid="reading-fields">
        {rows.map((r) => (
          <div key={r.key} className="flex flex-wrap justify-between gap-x-3 border-t border-rule py-1.5">
            <dt className="text-ink-2">{r.label}</dt>
            <dd className="ws-wrap m-0 text-right">{r.value ?? <span className="text-ink-2">{r.hidden ? 'value withheld' : 'not read'}</span>}</dd>
          </div>
        ))}
      </dl>
      {Array.isArray(res.reading.values_withheld) && res.reading.values_withheld.some((k) => k === 'lot' || k === 'serial') && (
        <p className="m-0 mt-2 text-[15px] text-ink-2" data-testid="lot-serial-note">
          Lot and serial numbers on the label are never shown or kept.
        </p>
      )}
      <LiveMatches res={res} />
      <div className="mt-4">
        <h3 className="ms-kicker m-0 !text-[16px]">Steps of this run</h3>
        <div className="mt-1">
          <LiveTrace steps={res.trace} label="Steps of this label reading" />
        </div>
      </div>
      <p className="m-0 mt-3 text-[15px] text-ink-2">{NOT_MEDICAL_ADVICE}</p>
    </article>
  )
}

/** Live camera preview + capture, or an uploaded photo. Both end in one JPEG sent to POST /v1/live/label. */
export function CameraPanel({ apiBase, fetcher }: { apiBase: string | null; fetcher?: Fetcher }) {
  const [cam, setCam] = useState(false)
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<LabelResponse | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [fellBack, setFellBack] = useState<string | null>(null)
  const video = useRef<HTMLVideoElement>(null)
  const stream = useRef<MediaStream | null>(null)

  const stopCamera = useCallback(() => {
    stream.current?.getTracks().forEach((t) => t.stop())
    stream.current = null
    if (video.current) video.current.srcObject = null
    setCam(false)
  }, [])
  // Leaving the panel switches the camera off.
  useEffect(() => stopCamera, [stopCamera])

  const start = async () => {
    setProblem(null)
    setFellBack(null)
    if (!navigator.mediaDevices?.getUserMedia) {
      setProblem('This browser cannot use the camera. Upload a photo instead. The recorded label runs are shown below.')
      return
    }
    let s: MediaStream
    try {
      s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false })
    } catch (e) {
      const name = (e as { name?: string })?.name
      if (name === 'OverconstrainedError' || name === 'NotFoundError') {
        try {
          s = await navigator.mediaDevices.getUserMedia({ video: true, audio: false })
        } catch (e2) {
          setProblem(cameraErrorText(e2))
          return
        }
      } else {
        setProblem(cameraErrorText(e))
        return
      }
    }
    stream.current = s
    setCam(true)
  }
  // Attach the stream once the <video> exists.
  useEffect(() => {
    if (cam && video.current && stream.current) {
      video.current.srcObject = stream.current
      void video.current.play().catch(() => undefined)
    }
  }, [cam])

  const send = async (blob: Blob) => {
    setBusy(true)
    setRes(null)
    setProblem(null)
    setFellBack(null)
    try {
      setRes(await postLabel(blob, { apiBase, fetcher: fetcher ?? ((u, i) => fetch(u, i)) }))
    } catch (e) {
      const err = e instanceof LiveError ? e : new LiveError('network', 'The live service could not be reached.')
      if (err.kind === 'rate_limited') setFellBack(`${LIMIT_TEXT}.`)
      else if (err.kind === 'patient_data' || err.kind === 'invalid_input' || err.kind === 'too_large') setProblem(err.message)
      else setFellBack(`${err.message} Showing the recorded label runs below.`)
    } finally {
      setBusy(false)
    }
  }

  const capture = async () => {
    if (!video.current) return
    try {
      const blob = await frameToJpeg(video.current)
      stopCamera()
      await send(blob)
    } catch (e) {
      if (e instanceof PhotoError && e.kind === 'too_big') setProblem(PHOTO_TOO_BIG_TEXT)
      else setProblem('No picture could be taken yet. Wait a second for the camera to start, then try again.')
    }
  }

  const upload = async (f: File | undefined) => {
    if (!f) return
    setProblem(null)
    if (f.size === 0) return setProblem('That file is empty.')
    if (f.size > MAX_SOURCE_BYTES) return setProblem(`That file is too large to read here. Choose a photo under ${MAX_SOURCE_BYTES / (1024 * 1024)} MB.`)
    if (!f.type.startsWith('image/')) return setProblem('That file is not an image. Choose a JPEG or PNG photo.')
    let blob: Blob
    try {
      blob = await fileToJpeg(f)
    } catch (e) {
      // The original file is never sent: if this browser cannot decode and shrink it, nothing is uploaded.
      if (e instanceof PhotoError && e.kind === 'too_big') return setProblem(PHOTO_TOO_BIG_TEXT)
      return setProblem('That image could not be read in this browser. Choose a JPEG or PNG photo.')
    }
    await send(blob)
  }

  const btn = 'w-full sm:w-auto'
  return (
    <section aria-label="Camera" data-testid="camera-panel">
      <p className="m-0 mt-3 flex gap-2 rounded-md border border-rule-strong bg-surface px-3 py-2 text-[16px] leading-snug text-ink" data-testid="patient-warning">
        <Icon name="info" size={20} />
        <span className="ws-wrap font-semibold">{PHOTO_NOTE}</span>
      </p>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
        {!cam ? (
          <button type="button" className={`ms-btn ws-btn-primary ${btn}`} style={{ height: 48 }} onClick={() => void start()} disabled={busy} data-testid="use-camera">
            <Icon name="camera" size={18} /> Use camera
          </button>
        ) : (
          <>
            <button type="button" className={`ms-btn ws-btn-primary ${btn}`} style={{ height: 48 }} onClick={() => void capture()} data-testid="capture">
              <Icon name="camera" size={18} /> Capture
            </button>
            <button type="button" className={`ms-btn ms-btn--secondary ${btn}`} style={{ height: 48 }} onClick={stopCamera}>
              Turn camera off
            </button>
          </>
        )}
        <label className={`ms-btn ms-btn--secondary cursor-pointer ${btn} focus-within:outline focus-within:outline-2`} style={{ height: 48 }}>
          <Icon name="upload" size={18} /> Upload photo
          <input
            type="file"
            accept="image/jpeg,image/png,image/*"
            className="sr-only"
            data-testid="image-input"
            aria-label="Upload photo of a device label"
            disabled={busy}
            onChange={(e) => {
              void upload(e.target.files?.[0])
              e.target.value = ''
            }}
          />
        </label>
      </div>
      {cam && (
        <div className="mt-3" data-testid="camera-preview">
          <video ref={video} playsInline muted autoPlay aria-label="Camera preview" className="max-h-80 w-full max-w-full rounded-md border border-rule bg-sunk object-contain" />
        </div>
      )}
      {busy && (
        <div role="status" aria-live="polite" className="mt-3 text-[16px] text-ink-2" data-testid="label-busy">
          <p className="m-0">Reading the label: SAM 3.1 finds it, Muse Spark reads it, openFDA is searched, then the claim gate checks the result…</p>
        </div>
      )}
      {problem && (
        <p role="alert" className="ms-banner ms-banner--err mt-3" data-testid="camera-problem">
          <span className="ws-wrap">{problem}</span>
        </p>
      )}
      {fellBack && (
        <p role="alert" className="ms-banner ms-banner--warn mt-3" data-testid="fallback-reason">
          <span className="ws-wrap">
            <strong>{fellBack}</strong>
          </span>
        </p>
      )}
      {res && <LiveLabelResult res={res} />}
    </section>
  )
}
