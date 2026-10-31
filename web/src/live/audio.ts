// Pure audio helpers for the voice question: downmix to mono, resample to 16 kHz, encode WAV PCM16.
// No browser API is used here, so every function is unit-tested. The recording itself (getUserMedia, MediaRecorder and
// AudioContext.decodeAudioData) lives in useRecorder.ts; its decoded channels come through `toWav16k`.

/** The sample rate the API expects. */
export const TARGET_RATE = 16000
/** Longest question: the recorder stops by itself here, and the encoder cuts anything longer. */
export const MAX_SECONDS = 60
/** The API refuses a larger body. 60 s of 16 kHz PCM16 mono is 1.92 MB, so this is never reached by a real clip. */
export const MAX_WAV_BYTES = 4 * 1024 * 1024

/** Averages all channels into one. Channels of different length are read up to the shortest. */
export function downmixToMono(channels: Float32Array[]): Float32Array {
  if (channels.length === 0) return new Float32Array(0)
  if (channels.length === 1) return channels[0]
  const n = Math.min(...channels.map((c) => c.length))
  const out = new Float32Array(n)
  for (let i = 0; i < n; i++) {
    let s = 0
    for (const c of channels) s += c[i]
    out[i] = s / channels.length
  }
  return out
}

/**
 * Resamples mono audio from `from` Hz to `to` Hz. Going down, each output sample is the mean of the input samples it covers
 * (a box filter, which avoids most aliasing); going up, it is linear interpolation. Same rate returns the input unchanged.
 */
export function resample(input: Float32Array, from: number, to: number): Float32Array {
  if (!(from > 0) || !(to > 0)) throw new RangeError('sample rates must be positive')
  if (from === to || input.length === 0) return input
  const outLen = Math.max(1, Math.round((input.length * to) / from))
  const out = new Float32Array(outLen)
  const ratio = from / to
  for (let i = 0; i < outLen; i++) {
    if (ratio > 1) {
      const start = i * ratio
      const end = Math.min(input.length, (i + 1) * ratio)
      const a = Math.floor(start)
      const b = Math.max(a + 1, Math.ceil(end))
      let sum = 0
      let n = 0
      for (let j = a; j < b && j < input.length; j++) {
        sum += input[j]
        n++
      }
      out[i] = n ? sum / n : 0
    } else {
      const pos = i * ratio
      const a = Math.floor(pos)
      const b = Math.min(input.length - 1, a + 1)
      const f = pos - a
      out[i] = input[Math.min(a, input.length - 1)] * (1 - f) + input[b] * f
    }
  }
  return out
}

const clamp16 = (x: number): number => {
  const v = Math.max(-1, Math.min(1, Number.isFinite(x) ? x : 0))
  return v < 0 ? Math.round(v * 0x8000) : Math.round(v * 0x7fff)
}

/** A canonical 44-byte RIFF/WAVE header followed by little-endian signed 16-bit mono samples. */
export function encodeWavPcm16(samples: Float32Array, sampleRate: number = TARGET_RATE): Uint8Array {
  const bytes = samples.length * 2
  const buf = new ArrayBuffer(44 + bytes)
  const v = new DataView(buf)
  const tag = (o: number, s: string) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)))
  tag(0, 'RIFF')
  v.setUint32(4, 36 + bytes, true)
  tag(8, 'WAVE')
  tag(12, 'fmt ')
  v.setUint32(16, 16, true) // fmt chunk size
  v.setUint16(20, 1, true) // PCM
  v.setUint16(22, 1, true) // mono
  v.setUint32(24, sampleRate, true)
  v.setUint32(28, sampleRate * 2, true) // byte rate
  v.setUint16(32, 2, true) // block align
  v.setUint16(34, 16, true) // bits per sample
  tag(36, 'data')
  v.setUint32(40, bytes, true)
  for (let i = 0; i < samples.length; i++) v.setInt16(44 + i * 2, clamp16(samples[i]), true)
  return new Uint8Array(buf)
}

export interface Wav {
  bytes: Uint8Array
  seconds: number
  /** True when the clip was longer than MAX_SECONDS and was cut. */
  truncated: boolean
}

/** Decoded channels at any rate -> a 16 kHz mono PCM16 WAV of at most MAX_SECONDS. */
export function toWav16k(channels: Float32Array[], rate: number): Wav {
  const mono = downmixToMono(channels)
  let pcm = resample(mono, rate, TARGET_RATE)
  const max = MAX_SECONDS * TARGET_RATE
  const truncated = pcm.length > max
  if (truncated) pcm = pcm.subarray(0, max)
  return { bytes: encodeWavPcm16(pcm, TARGET_RATE), seconds: pcm.length / TARGET_RATE, truncated }
}

/** Root-mean-square level, 0..1, of a block of float samples. */
export function rmsLevel(block: ArrayLike<number>): number {
  if (block.length === 0) return 0
  let s = 0
  for (let i = 0; i < block.length; i++) s += block[i] * block[i]
  return Math.min(1, Math.sqrt(s / block.length))
}

/** Level of byte time-domain data (AnalyserNode.getByteTimeDomainData: 128 is silence), 0..1, for the level meter. */
export function byteLevel(block: ArrayLike<number>): number {
  if (block.length === 0) return 0
  let s = 0
  for (let i = 0; i < block.length; i++) {
    const x = (block[i] - 128) / 128
    s += x * x
  }
  return Math.min(1, Math.sqrt(s / block.length) * 2) // x2: speech sits well below full scale
}

/** "0:07" */
export const fmtClock = (seconds: number): string => {
  const s = Math.max(0, Math.floor(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
