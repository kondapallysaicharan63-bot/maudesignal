// Browser side of the voice question: getUserMedia -> MediaRecorder -> AudioContext.decodeAudioData -> 16 kHz mono WAV.
// The pure parts (downmix, resample, WAV header) are in audio.ts and are unit-tested; the browser calls here are covered by
// the Playwright run with a fake microphone. Audio never leaves the page except in the one request that sends it.
// Cancel discards the recording: no WAV is made and nothing is sent. Pause and resume use MediaRecorder's own pause.
import { useCallback, useEffect, useRef, useState } from 'react'
import { byteLevel, MAX_SECONDS, toWav16k } from './audio'

export type RecState = 'idle' | 'recording' | 'paused' | 'processing'

export interface RecResult {
  wav: Blob
  seconds: number
  truncated: boolean
}

/** How many recent levels the waveform shows. */
export const WAVE_BARS = 24
/** From here the bar says when the recording will stop. */
export const WARN_SECONDS = 45
/** The waveform takes a new level this often (ms), so the page is not re-drawn on every animation frame. */
const WAVE_STEP_MS = 90

export interface Recorder {
  state: RecState
  /** Recorded time (paused time is not counted). */
  seconds: number
  level: number
  /** The last WAVE_BARS levels, oldest first (0..1). */
  levels: number[]
  /** False when this browser's MediaRecorder cannot pause. */
  canPause: boolean
  /** True once MAX_SECONDS were recorded: the recording is paused (not sent); Stop uses it, Cancel discards it. */
  atLimit: boolean
  start: () => Promise<void>
  /** Stops and hands the WAV to onResult. */
  stop: () => void
  toggle: () => void
  pause: () => void
  resume: () => void
  /** Stops and throws the recording away: onResult is never called. */
  cancel: () => void
}

type AC = typeof AudioContext
const audioContextCtor = (): AC | null =>
  typeof window === 'undefined' ? null : ((window as unknown as { AudioContext?: AC; webkitAudioContext?: AC }).AudioContext ??
    (window as unknown as { webkitAudioContext?: AC }).webkitAudioContext ?? null)

/** Why the microphone could not be used, in plain words. */
export function micErrorText(e: unknown): string {
  const name = (e as { name?: string } | null)?.name ?? ''
  if (name === 'NotAllowedError' || name === 'SecurityError' || name === 'PermissionDeniedError')
    return 'Microphone permission was denied. Allow the microphone in the browser to talk to it; the recorded voice run is shown below instead.'
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError' || name === 'OverconstrainedError')
    return 'No microphone was found. The recorded voice run is shown below instead.'
  if (name === 'NotReadableError') return 'The microphone is in use by another program. The recorded voice run is shown below instead.'
  return 'The microphone could not be used. The recorded voice run is shown below instead.'
}

/** Decodes a recorded or uploaded audio blob and re-encodes it as 16 kHz mono PCM16 WAV (at most 60 s). */
export async function blobToWav(blob: Blob): Promise<RecResult> {
  const Ctor = audioContextCtor()
  if (!Ctor) throw new Error('no-audio-context')
  const ctx = new Ctor()
  try {
    const decoded = await ctx.decodeAudioData(await blob.arrayBuffer())
    const channels = Array.from({ length: decoded.numberOfChannels }, (_, i) => decoded.getChannelData(i))
    const w = toWav16k(channels, decoded.sampleRate)
    if (w.seconds < 0.3) throw new Error('empty-audio')
    return { wav: new Blob([w.bytes as BlobPart], { type: 'audio/wav' }), seconds: w.seconds, truncated: w.truncated }
  } finally {
    void ctx.close().catch(() => undefined)
  }
}

/** Pushes `v` onto a fixed-length history (oldest dropped). */
export function pushLevel(levels: number[], v: number, max = WAVE_BARS): number[] {
  const next = levels.length >= max ? levels.slice(levels.length - max + 1) : levels.slice()
  next.push(Math.max(0, Math.min(1, v)))
  return next
}

/** Recorded time: finished segments plus the running one (none while paused). */
export function elapsedSeconds(doneMs: number, runningSince: number | null, now: number): number {
  return (doneMs + (runningSince === null ? 0 : now - runningSince)) / 1000
}

interface Handlers {
  onResult: (r: RecResult) => void
  /** Called with a plain-words message when the mic cannot be used or nothing was recorded. */
  onError: (message: string, kind: 'denied' | 'empty' | 'unsupported') => void
  /** At MAX_SECONDS: pause and wait for Stop or Cancel (the message box) instead of stopping and sending (earlier composer). */
  pauseAtLimit?: boolean
}

export function useRecorder(h: Handlers): Recorder {
  const [state, setState] = useState<RecState>('idle')
  const [seconds, setSeconds] = useState(0)
  const [level, setLevel] = useState(0)
  const [levels, setLevels] = useState<number[]>([])
  const [canPause, setCanPause] = useState(true)
  const [atLimit, setAtLimit] = useState(false)
  const rec = useRef<MediaRecorder | null>(null)
  const stream = useRef<MediaStream | null>(null)
  const meter = useRef<{ ctx: AudioContext; raf: number } | null>(null)
  const tick = useRef<number | null>(null)
  const discard = useRef(false)
  const paused = useRef(false)
  // Recorded time: milliseconds of finished segments, and when the running segment started (null while paused).
  const timing = useRef<{ doneMs: number; since: number | null }>({ doneMs: 0, since: null })
  const handlers = useRef(h)
  handlers.current = h

  const cleanup = useCallback(() => {
    if (tick.current) window.clearInterval(tick.current)
    tick.current = null
    if (meter.current) {
      cancelAnimationFrame(meter.current.raf)
      void meter.current.ctx.close().catch(() => undefined)
      meter.current = null
    }
    stream.current?.getTracks().forEach((t) => t.stop())
    stream.current = null
    paused.current = false
    setLevel(0)
    setLevels([])
    setAtLimit(false)
  }, [])

  useEffect(
    () => () => {
      const r = rec.current
      if (r && r.state !== 'inactive') {
        r.onstop = null
        r.stop()
      }
      cleanup()
    },
    [cleanup],
  )

  const stop = useCallback(() => {
    const r = rec.current
    if (r && r.state !== 'inactive') r.stop()
  }, [])

  const cancel = useCallback(() => {
    const r = rec.current
    discard.current = true
    if (r && r.state !== 'inactive') r.stop()
    else {
      cleanup()
      setState('idle')
    }
  }, [cleanup])

  const pause = useCallback(() => {
    const r = rec.current
    if (!r || r.state !== 'recording' || typeof r.pause !== 'function') return
    r.pause()
    const t = timing.current
    if (t.since !== null) t.doneMs += Date.now() - t.since
    t.since = null
    paused.current = true
    setLevel(0)
    setState('paused')
  }, [])

  const resume = useCallback(() => {
    const r = rec.current
    if (!r || r.state !== 'paused' || typeof r.resume !== 'function') return
    const t = timing.current
    if (t.doneMs >= MAX_SECONDS * 1000) return // the limit is reached: only Stop or Cancel
    r.resume()
    timing.current.since = Date.now()
    paused.current = false
    setState('recording')
  }, [])

  const start = useCallback(async () => {
    if (state !== 'idle') return
    if (typeof MediaRecorder === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      handlers.current.onError('This browser cannot record audio. The recorded voice run is shown below instead.', 'unsupported')
      return
    }
    let s: MediaStream
    try {
      s = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (e) {
      handlers.current.onError(micErrorText(e), 'denied')
      return
    }
    stream.current = s
    discard.current = false
    paused.current = false
    const chunks: Blob[] = []
    const mr = new MediaRecorder(s)
    rec.current = mr
    setCanPause(typeof mr.pause === 'function' && typeof mr.resume === 'function')
    mr.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data)
    }
    mr.onstop = () => {
      const type = mr.mimeType || 'audio/webm'
      cleanup()
      rec.current = null
      if (discard.current) {
        // Cancelled: the chunks are dropped here and nothing is decoded or sent.
        chunks.length = 0
        discard.current = false
        setState('idle')
        return
      }
      setState('processing')
      blobToWav(new Blob(chunks, { type }))
        .then((r) => handlers.current.onResult(r))
        .catch((e: unknown) =>
          handlers.current.onError(
            (e as Error)?.message === 'empty-audio' || chunks.length === 0
              ? 'Nothing was recorded. Check that the microphone is on, then try again.'
              : 'That recording could not be read by this browser.',
            'empty',
          ),
        )
        .finally(() => setState('idle'))
    }
    // The level meter: an analyser on the same stream. If the browser has no AudioContext the timer still runs.
    const Ctor = audioContextCtor()
    if (Ctor) {
      try {
        const ctx = new Ctor()
        const an = ctx.createAnalyser()
        an.fftSize = 512
        ctx.createMediaStreamSource(s).connect(an)
        const buf = new Uint8Array(an.fftSize)
        const m = { ctx, raf: 0 }
        let last = 0
        const loop = (now: number) => {
          if (!paused.current && now - last >= WAVE_STEP_MS) {
            last = now
            an.getByteTimeDomainData(buf)
            const v = byteLevel(buf)
            setLevel(v)
            setLevels((l) => pushLevel(l, v))
          }
          m.raf = requestAnimationFrame(loop)
        }
        m.raf = requestAnimationFrame(loop)
        meter.current = m
      } catch {
        meter.current = null
      }
    }
    timing.current = { doneMs: 0, since: Date.now() }
    setSeconds(0)
    setAtLimit(false)
    setLevels([])
    tick.current = window.setInterval(() => {
      const t = timing.current
      const sec = elapsedSeconds(t.doneMs, t.since, Date.now())
      setSeconds(sec)
      // The longest question: at the limit the recording is paused, not sent. Nothing is used until the person
      // presses Stop (or Cancel discards it).
      if (sec >= MAX_SECONDS && t.since !== null && !handlers.current.pauseAtLimit) stop()
      else if (sec >= MAX_SECONDS && t.since !== null) {
        const r = rec.current
        t.doneMs = MAX_SECONDS * 1000
        t.since = null
        setSeconds(MAX_SECONDS)
        setAtLimit(true)
        if (r && r.state === 'recording' && typeof r.pause === 'function') {
          r.pause()
          paused.current = true
          setLevel(0)
          setState('paused')
        } else stop() // no pause in this browser: stop here; the person still presses Send
      }
    }, 200)
    mr.start()
    setState('recording')
  }, [state, cleanup, stop])

  const toggle = useCallback(() => {
    if (state === 'recording' || state === 'paused') stop()
    else if (state === 'idle') void start()
  }, [state, start, stop])

  return { state, seconds, level, levels, canPause, atLimit, start, stop, toggle, pause, resume, cancel }
}
