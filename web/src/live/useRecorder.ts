// Browser side of the voice question: getUserMedia -> MediaRecorder -> AudioContext.decodeAudioData -> 16 kHz mono WAV.
// The pure parts (downmix, resample, WAV header) are in audio.ts and are unit-tested; the browser calls here are covered by
// the Playwright run with a fake microphone. Audio never leaves the page except in the one request that asks the question.
import { useCallback, useEffect, useRef, useState } from 'react'
import { byteLevel, MAX_SECONDS, toWav16k } from './audio'

export type RecState = 'idle' | 'recording' | 'processing'

export interface RecResult {
  wav: Blob
  seconds: number
  truncated: boolean
}

export interface Recorder {
  state: RecState
  seconds: number
  level: number
  start: () => Promise<void>
  stop: () => void
  toggle: () => void
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

interface Handlers {
  onResult: (r: RecResult) => void
  /** Called with a plain-words message when the mic cannot be used or nothing was recorded. */
  onError: (message: string, kind: 'denied' | 'empty' | 'unsupported') => void
}

export function useRecorder(h: Handlers): Recorder {
  const [state, setState] = useState<RecState>('idle')
  const [seconds, setSeconds] = useState(0)
  const [level, setLevel] = useState(0)
  const rec = useRef<MediaRecorder | null>(null)
  const stream = useRef<MediaStream | null>(null)
  const meter = useRef<{ ctx: AudioContext; raf: number } | null>(null)
  const tick = useRef<number | null>(null)
  const auto = useRef<number | null>(null)
  const handlers = useRef(h)
  handlers.current = h

  const cleanup = useCallback(() => {
    if (tick.current) window.clearInterval(tick.current)
    if (auto.current) window.clearTimeout(auto.current)
    tick.current = auto.current = null
    if (meter.current) {
      cancelAnimationFrame(meter.current.raf)
      void meter.current.ctx.close().catch(() => undefined)
      meter.current = null
    }
    stream.current?.getTracks().forEach((t) => t.stop())
    stream.current = null
    setLevel(0)
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
    const chunks: Blob[] = []
    const mr = new MediaRecorder(s)
    rec.current = mr
    mr.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data)
    }
    mr.onstop = () => {
      const type = mr.mimeType || 'audio/webm'
      cleanup()
      rec.current = null
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
        const loop = () => {
          an.getByteTimeDomainData(buf)
          setLevel(byteLevel(buf))
          m.raf = requestAnimationFrame(loop)
        }
        m.raf = requestAnimationFrame(loop)
        meter.current = m
      } catch {
        meter.current = null
      }
    }
    const t0 = Date.now()
    setSeconds(0)
    tick.current = window.setInterval(() => setSeconds((Date.now() - t0) / 1000), 200)
    auto.current = window.setTimeout(stop, MAX_SECONDS * 1000)
    mr.start()
    setState('recording')
  }, [state, cleanup, stop])

  const toggle = useCallback(() => {
    if (state === 'recording') stop()
    else if (state === 'idle') void start()
  }, [state, start, stop])

  return { state, seconds, level, start, stop, toggle }
}
