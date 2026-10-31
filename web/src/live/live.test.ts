// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'
import evidence from '../../public/data/evidence.json'
import threads from '../../public/data/threads.json'
import type { Evidence, Thread } from '../types'
import {
  answerText,
  badgeText,
  buildAskBody,
  buildLabelForm,
  buildVoiceForm,
  checkQuestion,
  heldBackLine,
  isFreeTier,
  LiveError,
  mapError,
  openLabel,
  parseAsk,
  parseLabelResponse,
  postAsk,
  postLabel,
  postVoice,
  trimHistory,
} from './api'
import { byteLevel, downmixToMono, encodeWavPcm16, fmtClock, MAX_SECONDS, resample, rmsLevel, TARGET_RATE, toWav16k } from './audio'
import { fitSize, isAcceptedImage, readingRows } from './label'
import { drawToJpeg, encodeWithin, PHOTO_QUALITIES, type PhotoCanvas } from './photo'
import { recordedFor, threadToResponse } from './recorded'
import { speechText } from './speech'

const T = threads.threads as unknown as Thread[]
const EV = evidence as unknown as Evidence

const ascii = (b: Uint8Array, from: number, to: number) => String.fromCharCode(...b.slice(from, to))
const u32 = (b: Uint8Array, o: number) => new DataView(b.buffer, b.byteOffset).getUint32(o, true)
const u16 = (b: Uint8Array, o: number) => new DataView(b.buffer, b.byteOffset).getUint16(o, true)
const i16 = (b: Uint8Array, o: number) => new DataView(b.buffer, b.byteOffset).getInt16(o, true)

describe('WAV PCM16 encoder', () => {
  const samples = new Float32Array([0, 0.5, -0.5, 1, -1, 2, -2])
  const wav = encodeWavPcm16(samples, 16000)

  it('writes a canonical 44-byte header', () => {
    expect(ascii(wav, 0, 4)).toBe('RIFF')
    expect(ascii(wav, 8, 12)).toBe('WAVE')
    expect(ascii(wav, 12, 16)).toBe('fmt ')
    expect(u32(wav, 16)).toBe(16)
    expect(u16(wav, 20)).toBe(1) // PCM
    expect(u16(wav, 22)).toBe(1) // mono
    expect(u32(wav, 24)).toBe(16000)
    expect(u32(wav, 28)).toBe(32000) // byte rate
    expect(u16(wav, 32)).toBe(2) // block align
    expect(u16(wav, 34)).toBe(16) // bits
    expect(ascii(wav, 36, 40)).toBe('data')
  })

  it('has the right length and size fields', () => {
    expect(wav.length).toBe(44 + samples.length * 2)
    expect(u32(wav, 40)).toBe(samples.length * 2)
    expect(u32(wav, 4)).toBe(wav.length - 8)
  })

  it('stores the sample rate it was given', () => {
    expect(u32(encodeWavPcm16(samples, 8000), 24)).toBe(8000)
    expect(u32(encodeWavPcm16(samples), 24)).toBe(TARGET_RATE)
  })

  it('writes little-endian signed samples and clips out-of-range values', () => {
    expect(i16(wav, 44)).toBe(0)
    expect(i16(wav, 46)).toBe(16384)
    expect(i16(wav, 48)).toBe(-16384)
    expect(i16(wav, 50)).toBe(32767)
    expect(i16(wav, 52)).toBe(-32768)
    expect(i16(wav, 54)).toBe(32767) // 2 clipped
    expect(i16(wav, 56)).toBe(-32768) // -2 clipped
  })

  it('turns NaN into silence and an empty clip into a header only', () => {
    expect(i16(encodeWavPcm16(new Float32Array([NaN])), 44)).toBe(0)
    expect(encodeWavPcm16(new Float32Array(0)).length).toBe(44)
  })
})

describe('mono and resampling', () => {
  it('averages channels', () => {
    const m = downmixToMono([new Float32Array([1, 0, -1]), new Float32Array([0, 1, -1])])
    expect(Array.from(m)).toEqual([0.5, 0.5, -1])
    expect(downmixToMono([]).length).toBe(0)
    const one = new Float32Array([0.1, 0.2])
    expect(downmixToMono([one])).toBe(one)
  })

  it('48 kHz to 16 kHz gives a third of the samples and keeps a constant level', () => {
    const out = resample(new Float32Array(48000).fill(0.25), 48000, 16000)
    expect(out.length).toBe(16000)
    expect(out.every((x) => Math.abs(x - 0.25) < 1e-6)).toBe(true)
  })

  it('44.1 kHz to 16 kHz keeps the duration', () => {
    const out = resample(new Float32Array(44100), 44100, 16000)
    expect(out.length).toBe(16000)
  })

  it('upsampling interpolates linearly', () => {
    const out = resample(new Float32Array([0, 1]), 8000, 16000)
    expect(out.length).toBe(4)
    expect(out[0]).toBe(0)
    expect(out[1]).toBeCloseTo(0.5, 5)
    expect(out[2]).toBe(1)
  })

  it('returns the input at the same rate and rejects a bad rate', () => {
    const a = new Float32Array([0.3])
    expect(resample(a, 16000, 16000)).toBe(a)
    expect(() => resample(a, 0, 16000)).toThrow(RangeError)
  })

  it('a 1 kHz tone at 48 kHz is still a 1 kHz tone at 16 kHz (zero crossings)', () => {
    const n = 48000
    const tone = Float32Array.from({ length: n }, (_, i) => Math.sin((2 * Math.PI * 1000 * i) / 48000))
    const out = resample(tone, 48000, 16000)
    let crossings = 0
    for (let i = 1; i < out.length; i++) if (out[i - 1] < 0 !== out[i] < 0) crossings++
    expect(Math.abs(crossings - 2000)).toBeLessThanOrEqual(2) // 1000 cycles per second, two crossings each
  })
})

describe('whole pipeline', () => {
  it('stereo 48 kHz becomes a 16 kHz mono WAV of the same duration', () => {
    const left = new Float32Array(48000).fill(0.2)
    const right = new Float32Array(48000).fill(0.4)
    const w = toWav16k([left, right], 48000)
    expect(w.seconds).toBeCloseTo(1, 5)
    expect(w.truncated).toBe(false)
    expect(w.bytes.length).toBe(44 + 16000 * 2)
    expect(u32(w.bytes, 24)).toBe(16000)
    expect(u16(w.bytes, 22)).toBe(1)
    expect(i16(w.bytes, 44)).toBe(Math.round(0.3 * 0x7fff))
  })

  it('cuts a clip longer than 60 s and says so; the file stays under the 4 MB limit', () => {
    const w = toWav16k([new Float32Array(16000 * 75)], 16000)
    expect(w.truncated).toBe(true)
    expect(w.seconds).toBe(MAX_SECONDS)
    expect(w.bytes.length).toBe(44 + MAX_SECONDS * 16000 * 2)
    expect(w.bytes.length).toBeLessThan(4 * 1024 * 1024)
  })

  it('levels and clock', () => {
    expect(rmsLevel(new Float32Array([0, 0]))).toBe(0)
    expect(rmsLevel(new Float32Array([1, -1]))).toBe(1)
    expect(rmsLevel([])).toBe(0)
    expect(byteLevel(new Uint8Array([128, 128, 128]))).toBe(0)
    expect(byteLevel(new Uint8Array([255, 0, 255, 0]))).toBe(1)
    expect(fmtClock(0)).toBe('0:00')
    expect(fmtClock(7.9)).toBe('0:07')
    expect(fmtClock(60)).toBe('1:00')
    expect(fmtClock(-3)).toBe('0:00')
  })
})

describe('history trimming and question checks', () => {
  const turn = (i: number, ans = `answer ${i}`) => ({ question: `question ${i}`, answer: ans })

  it('keeps the last four turns, oldest first', () => {
    const h = trimHistory([1, 2, 3, 4, 5, 6].map((i) => turn(i)))
    expect(h.map((t) => t.question)).toEqual(['question 3', 'question 4', 'question 5', 'question 6'])
  })

  it('cuts each answer to 600 characters and drops blank turns', () => {
    const h = trimHistory([turn(1, 'x'.repeat(900)), { question: '  ', answer: 'a' }, { question: 'q', answer: '' }])
    expect(h).toHaveLength(1)
    expect(h[0].answer).toHaveLength(600)
  })

  it('checks the question length the way the server does', () => {
    expect(checkQuestion('  hi?  ')).toBe('hi?')
    expect(checkQuestion('hi')).toBe('hi') // a greeting is answered by the server's fixed reply
    expect(() => checkQuestion(' x ')).toThrow(/at least 2/)
    expect(() => checkQuestion('   ')).toThrow(LiveError)
    expect(() => checkQuestion('x'.repeat(501))).toThrow(/500/)
    expect(checkQuestion('x'.repeat(500))).toHaveLength(500)
  })

  it('answerText joins the sentences that passed', () => {
    expect(answerText({ speakable: [{ text: 'One.', links: [] }, { text: 'Two.', links: [] }], withheld: [], spoken_text: '' })).toBe('One. Two.')
  })
})

describe('payload builders', () => {
  it('ask body: question, trimmed history, product code, ref; empty keys left out', () => {
    expect(buildAskBody('  What changed?  ')).toEqual({ question: 'What changed?' })
    const body = buildAskBody('And QIH?', { history: [1, 2, 3, 4, 5].map((i) => ({ question: `q${i}`, answer: 'a'.repeat(700) })), productCode: 'QIH', ref: 'dr-x' })
    expect((body.history as unknown[]).length).toBe(4)
    expect((body.history as { answer: string }[])[0].answer).toHaveLength(600)
    expect(body.product_code).toBe('QIH')
    expect(body.ref).toBe('dr-x')
    expect(() => buildAskBody('n')).toThrow(LiveError)
  })

  it('voice form: part "audio" is the WAV; part "meta" only when there is something to say', async () => {
    const wav = new Blob([new Uint8Array(44)], { type: 'audio/wav' })
    const bare = buildVoiceForm(wav)
    expect(bare.get('audio')).toBeInstanceOf(Blob)
    expect((bare.get('audio') as File).type).toBe('audio/wav')
    expect(bare.has('meta')).toBe(false)
    const withMeta = buildVoiceForm(wav, { history: [{ question: 'q', answer: 'a' }], productCode: 'LLZ' })
    const meta = JSON.parse(
      await new Promise<string>((res) => {
        const fr = new FileReader()
        fr.onload = () => res(String(fr.result))
        fr.readAsText(withMeta.get('meta') as Blob)
      }),
    )
    expect(meta).toEqual({ history: [{ question: 'q', answer: 'a' }], product_code: 'LLZ' })
  })

  it('label form: part "image" only', () => {
    const f = buildLabelForm(new Blob([new Uint8Array([0xff, 0xd8, 0xff])], { type: 'image/jpeg' }))
    expect([...f.keys()]).toEqual(['image'])
    expect((f.get('image') as File).name).toBe('label.jpg')
    expect((buildLabelForm(new Blob([], { type: 'image/png' })).get('image') as File).name).toBe('label.png')
  })
})

describe('error mapping', () => {
  it('422 patient_data keeps the server message', () => {
    const e = mapError(422, { code: 'patient_data', message: 'Remove the patient name.' })
    expect(e).toMatchObject({ kind: 'patient_data', message: 'Remove the patient name.' })
  })
  it('422 other codes are invalid input', () => {
    expect(mapError(422, { code: 'invalid_input', message: 'too short' })).toMatchObject({ kind: 'invalid_input', message: 'too short' })
    expect(mapError(422, null).kind).toBe('invalid_input')
  })
  it('429 is rate limited with retry_after_s', () => {
    expect(mapError(429, { code: 'rate_limited', message: 'm', retry_after_s: 120 })).toMatchObject({ kind: 'rate_limited', retryAfterS: 120 })
    expect(mapError(429, {}).message).toMatch(/limit/i)
  })
  it('413 is too large; other statuses are a server error that never echoes the body', () => {
    expect(mapError(413, {}).kind).toBe('too_large')
    const e = mapError(500, { message: '<script>alert(1)</script> secret' })
    expect(e.kind).toBe('server')
    expect(e.message).not.toContain('secret')
  })
  it('a long server message is cut', () => {
    expect(mapError(422, { code: 'patient_data', message: 'x'.repeat(2000) }).message.length).toBeLessThanOrEqual(400)
  })
})

describe('response parsing', () => {
  const ok = {
    mode: 'live',
    not_medical_advice: true,
    trace: [{ step: 'Muse Spark', model: 'muse-spark-1.3', ms: 812, status: 'ok' }],
    cost_usd: null,
    limits: { remaining_today: 7, resets_utc: '2026-11-01T00:00:00Z' },
    heard: ' What changed? ',
    answer: {
      speakable: [{ text: 'A.', links: [{ label: 'x', url: 'https://example.org/a' }, { label: 'bad', url: 'javascript:alert(1)' }] }, { text: '' }],
      withheld: [{ reason: 'r' }],
      spoken_text: 'A.',
    },
  }
  it('keeps only http(s) links and non-empty sentences', () => {
    const r = parseAsk(ok)!
    expect(r.answer.speakable).toHaveLength(1)
    expect(r.answer.speakable[0].links).toEqual([{ label: 'x', url: 'https://example.org/a' }])
    expect(r.heard).toBe('What changed?')
    expect(r.limits?.remaining_today).toBe(7)
    expect(r.cost_usd).toBeNull()
  })
  it('reads the chat tier, badge, chips, did-you-mean and the page to open; drops anything else', () => {
    const r = parseAsk({
      ...ok,
      mode: 'direct',
      tier: 'direct',
      badge: 'Direct FDA lookup — no AI',
      suggestions: ['Recalls for LLZ', 3, '', 'a'.repeat(300)],
      did_you_mean: ['LLZ', 'not a code'],
      open: { view: 'check-device', code: 'QAS' },
    })!
    expect(r.mode).toBe('direct')
    expect(r.tier).toBe('direct')
    expect(r.badge).toBe('Direct FDA lookup — no AI')
    expect(r.suggestions).toEqual(['Recalls for LLZ', 'a'.repeat(120)])
    expect(r.did_you_mean).toEqual(['LLZ'])
    expect(r.open).toEqual({ view: 'check-device', code: 'QAS' })
    expect(badgeText(r)).toBe('Direct FDA lookup — no AI')
    expect(isFreeTier(r)).toBe(true)
    expect(openLabel(r.open)).toBe('Open Check any device type for QAS')
    const bad = parseAsk({ ...ok, tier: 'premium', open: { view: 'javascript:alert(1)' } })!
    expect(bad.tier).toBeUndefined()
    expect(bad.open).toBeUndefined()
    expect(bad.suggestions).toEqual([])
    expect(badgeText(bad)).toBe('Live answer')
    expect(badgeText({ ...bad, mode: 'recorded' })).toBe('Recorded run')
    expect(openLabel({ view: 'alerts' })).toBeNull()
  })
  it('rejects an answer without the answer block', () => {
    expect(parseAsk({ mode: 'live' })).toBeNull()
    expect(parseAsk(null)).toBeNull()
    expect(parseAsk({ answer: { speakable: 'no' } })).toBeNull()
  })
  it('label responses are cut to three candidates and need the reading and matches', () => {
    const cand = (i: number) => ({ k_number: `K${i}`, device_name: 'd', applicant: 'a', product_code: 'QIH', why_matched: ['w'], why_not_matched: [], links: [] })
    const body = { mode: 'live', trace: [], reading: { legibility: 'clear', fields: {} }, matches: { status: 'needs_person_to_confirm', candidates: [1, 2, 3, 4].map(cand) }, confirmed: null }
    expect(parseLabelResponse(body)!.matches.candidates).toHaveLength(3)
    expect(parseLabelResponse({ ...body, matches: { status: 'no_match_found', candidates: [] } })!.matches.status).toBe('no_match_found')
    expect(parseLabelResponse({ mode: 'live' })).toBeNull()
  })
  it('held-back line shows the count and the reasons only', () => {
    expect(heldBackLine([])).toBeNull()
    expect(heldBackLine([{ reason: 'a number did not match' }])).toBe('1 sentence held back: a number did not match')
    expect(heldBackLine([{ reason: 'r1' }, { reason: 'r1' }, { reason: 'r2' }])).toBe('3 sentences held back: r1; r2')
  })
})

describe('network layer with a fake fetch', () => {
  const answer = { mode: 'live', not_medical_advice: true, trace: [], cost_usd: null, limits: null, answer: { speakable: [{ text: 'Hi.', links: [] }], withheld: [], spoken_text: 'Hi.' } }
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

  it('posts JSON to /v1/live/ask without credentials', async () => {
    const f = vi.fn(async () => json(200, answer))
    const r = await postAsk('What changed?', { history: [] }, { apiBase: 'https://api.example', fetcher: f })
    expect(r.answer.speakable[0].text).toBe('Hi.')
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('https://api.example/v1/live/ask')
    expect(init.method).toBe('POST')
    expect(init.credentials).toBe('omit')
    expect(JSON.parse(init.body as string)).toEqual({ question: 'What changed?' })
  })

  it('posts multipart to /v1/live/voice and /v1/live/label', async () => {
    const f = vi.fn(async (u: string) => (u.endsWith('/label') ? json(200, { mode: 'live', trace: [], reading: { legibility: 'clear', fields: {} }, matches: { status: 'no_match_found', candidates: [] } }) : json(200, answer)))
    await postVoice(new Blob([new Uint8Array(44)], { type: 'audio/wav' }), {}, { apiBase: 'https://api.example', fetcher: f })
    await postLabel(new Blob([new Uint8Array([1])], { type: 'image/jpeg' }), { apiBase: 'https://api.example', fetcher: f })
    const calls = f.mock.calls as unknown as [string, RequestInit][]
    expect(calls.map((c) => c[0])).toEqual(['https://api.example/v1/live/voice', 'https://api.example/v1/live/label'])
    expect(calls[0][1].body).toBeInstanceOf(FormData)
    expect(calls[0][1].headers).toBeUndefined() // the browser sets the multipart boundary
  })

  it('maps 429, 422, 500, network errors, timeouts and unreadable answers', async () => {
    const run = (f: () => Promise<Response>, timeoutMs?: number) => postAsk('What changed?', {}, { apiBase: 'https://api.example', fetcher: f, timeoutMs }).catch((e: LiveError) => e)
    expect(await run(async () => json(429, { code: 'rate_limited', message: 'm', retry_after_s: 5 }))).toMatchObject({ kind: 'rate_limited', retryAfterS: 5 })
    expect(await run(async () => json(422, { code: 'patient_data', message: 'no names' }))).toMatchObject({ kind: 'patient_data', message: 'no names' })
    expect(await run(async () => json(500, {}))).toMatchObject({ kind: 'server' })
    expect(
      await run(async () => {
        throw new TypeError('down')
      }),
    ).toMatchObject({ kind: 'network' })
    expect(await run(async () => new Response('not json'))).toMatchObject({ kind: 'bad_response' })
    expect(await run(async () => json(200, { hello: 1 }))).toMatchObject({ kind: 'bad_response' })
    const slow = (_u: string, init?: RequestInit) =>
      new Promise<Response>((_res, rej) => init?.signal?.addEventListener('abort', () => rej(Object.assign(new Error('a'), { name: 'AbortError' }))))
    expect(await run(slow as () => Promise<Response>, 20)).toMatchObject({ kind: 'timeout' })
  })

  it('sends nothing without an API address, and refuses a bad question or image before sending', async () => {
    const f = vi.fn()
    expect(await postAsk('What changed?', {}, { apiBase: null, fetcher: f }).catch((e: LiveError) => e)).toMatchObject({ kind: 'not_configured' })
    expect(await postAsk('n', {}, { apiBase: 'https://x.example', fetcher: f }).catch((e: LiveError) => e)).toMatchObject({ kind: 'invalid_input' })
    expect(await postLabel(new Blob([], { type: 'image/jpeg' }), { apiBase: 'https://x.example', fetcher: f }).catch((e: LiveError) => e)).toMatchObject({ kind: 'invalid_input' })
    expect(await postLabel(new Blob([new Uint8Array(4 * 1024 * 1024 + 1)], { type: 'image/jpeg' }), { apiBase: 'https://x.example', fetcher: f }).catch((e: LiveError) => e)).toMatchObject({ kind: 'too_large' })
    expect(f).not.toHaveBeenCalled()
  })
})

describe('label helpers', () => {
  it('hides withheld, illegible and empty values and never fills them in', () => {
    const rows = readingRows({
      legibility: 'partly_legible',
      fields: { device_name: { value: 'Stub', legibility: 'clear' }, model: { value: 'M-1', legibility: 'illegible' }, k_number: { value: 'K123456', legibility: 'clear' }, gtin: null, manufacturer: 'Acme' },
      values_withheld: ['k_number'],
    })
    const by = Object.fromEntries(rows.map((r) => [r.key, r]))
    expect(by.device_name.value).toBe('Stub')
    expect(by.model).toMatchObject({ value: null, hidden: false }) // illegible: "not read", not "value withheld"
    expect(by.k_number).toMatchObject({ value: null, hidden: true }) // listed in values_withheld
    expect(by.gtin).toMatchObject({ value: null, hidden: false })
    expect(by.manufacturer.value).toBe('Acme')
  })
  it('an illegible reading hides every value', () => {
    const rows = readingRows({ legibility: 'illegible', fields: { device_name: { value: 'Looks real', legibility: 'clear' } } })
    expect(rows[0]).toMatchObject({ value: null, hidden: false })
  })
  it('an empty legibility becomes "unknown"', () => {
    const b = { mode: 'live', matches: { candidates: [] }, reading: { legibility: '  ', fields: {} } }
    expect(parseLabelResponse(b)?.reading.legibility).toBe('unknown')
    expect(parseLabelResponse({ ...b, reading: { fields: {} } })?.reading.legibility).toBe('unknown')
  })
  it('fitSize keeps the aspect ratio, never enlarges, and handles bad sizes', () => {
    expect(fitSize(4000, 3000)).toEqual({ width: 1600, height: 1200 })
    expect(fitSize(800, 600)).toEqual({ width: 800, height: 600 })
    expect(fitSize(0, 10)).toEqual({ width: 0, height: 0 })
    expect(fitSize(3000, 4000, 1000)).toEqual({ width: 750, height: 1000 })
  })
  it('accepts JPEG and PNG only', () => {
    expect(isAcceptedImage('image/jpeg')).toBe(true)
    expect(isAcceptedImage('image/png')).toBe(true)
    expect(isAcceptedImage('image/heic')).toBe(false)
    expect(isAcceptedImage('application/pdf')).toBe(false)
  })
})

describe('recorded fallback', () => {
  it('shows a stored run in the live shape, with its note naming the run', () => {
    const t = T.find((x) => x.id === '06-trap') ?? T[0]
    const r = threadToResponse(t, EV, 'note')
    expect(r.mode).toBe('recorded')
    expect(r.answer.speakable.length + r.answer.withheld.length).toBe(t.sentences.length)
    expect(r.answer.withheld.length).toBe(t.sentences.filter((s) => s.status === 'block').length)
    expect(JSON.stringify(r.answer)).not.toContain(t.sentences.find((s) => s.status === 'block')?.text ?? '\u0000')
  })
  it('finds the closest stored question, or says that none is close', () => {
    const q = T.find((x) => x.tool_steps.length > 0)!.question
    const close = recordedFor(q, T, EV, 'Daily live limit reached.')
    expect(close.recorded_note).toContain('Daily live limit reached.')
    expect(close.answer.speakable.length).toBeGreaterThan(0)
    const none = recordedFor('zzzz qqqq xxxx', T, EV, 'Offline.')
    expect(none.answer.speakable).toHaveLength(0)
    expect(none.recorded_note).toMatch(/No stored run is close/)
  })
  it('speech text is whitespace-normalised and cut at a sentence end when long', () => {
    expect(speechText('  a   b \n c ')).toBe('a b c')
    const long = 'Sentence one is here. '.repeat(100)
    const cut = speechText(long)
    expect(cut.length).toBeLessThanOrEqual(1200)
    expect(cut.endsWith('.')).toBe(true)
  })
})

describe('photo downscale and size logic (fake canvas and encoder)', () => {
  const MB = 1024 * 1024
  const blobOf = (n: number) => new Blob([new Uint8Array(n)], { type: 'image/jpeg' })

  /** A fake canvas whose encoded size depends only on the quality asked for. */
  function fakeCanvas(sizeAt: (q: number) => number) {
    const calls: { w: number; h: number; q: number[]; drawn: number[] } = { w: 0, h: 0, q: [], drawn: [] }
    const c: PhotoCanvas = {
      width: 0,
      height: 0,
      getContext: () => ({ drawImage: (_s, _x, _y, w, h) => void calls.drawn.push(w, h) }),
      toBlob: (cb, type, q) => {
        calls.q.push(q)
        expect(type).toBe('image/jpeg')
        cb(blobOf(sizeAt(q)))
      },
    }
    return { c, calls }
  }

  it('tries quality 0.85, then 0.7, then 0.55', () => {
    expect([...PHOTO_QUALITIES]).toEqual([0.85, 0.7, 0.55])
  })
  it('draws at most 1600 px on the long side and encodes at 0.85 first', async () => {
    const { c, calls } = fakeCanvas(() => 900_000)
    const out = await drawToJpeg('src', 4032, 3024, () => c)
    expect(calls.drawn).toEqual([1600, 1200])
    expect(c.width).toBe(1600)
    expect(c.height).toBe(1200)
    expect(calls.q).toEqual([0.85])
    expect(out.size).toBe(900_000)
  })
  it('a small image is not enlarged', async () => {
    const { c, calls } = fakeCanvas(() => 50_000)
    await drawToJpeg('src', 640, 480, () => c)
    expect(calls.drawn).toEqual([640, 480])
  })
  it('retries at 0.7 when 0.85 is over 4 MB, and sends that result', async () => {
    const { c, calls } = fakeCanvas((q) => (q > 0.8 ? 5 * MB : 3 * MB))
    const out = await drawToJpeg('src', 4000, 3000, () => c)
    expect(calls.q).toEqual([0.85, 0.7])
    expect(out.size).toBe(3 * MB)
  })
  it('retries at 0.55 when 0.85 and 0.7 are over 4 MB', async () => {
    const { c, calls } = fakeCanvas((q) => (q > 0.6 ? 4 * MB + 1 : 2 * MB))
    const out = await drawToJpeg('src', 4000, 3000, () => c)
    expect(calls.q).toEqual([0.85, 0.7, 0.55])
    expect(out.size).toBe(2 * MB)
  })
  it('exactly 4 MB is accepted', async () => {
    const out = await encodeWithin(async () => blobOf(4 * MB))
    expect(out.size).toBe(4 * MB)
  })
  it('throws too_big when even 0.55 is over 4 MB, and never returns the original', async () => {
    const { c, calls } = fakeCanvas(() => 6 * MB)
    await expect(drawToJpeg('src', 4000, 3000, () => c)).rejects.toMatchObject({ name: 'PhotoError', kind: 'too_big' })
    expect(calls.q).toEqual([0.85, 0.7, 0.55])
  })
  it('an empty encode result is encode_failed, not a photo and not too big', async () => {
    await expect(encodeWithin(async () => blobOf(0))).rejects.toMatchObject({ name: 'PhotoError', kind: 'encode_failed' })
  })
  it('a source with no pixels throws no_frame before any canvas is made', async () => {
    const make = vi.fn()
    await expect(drawToJpeg('src', 0, 0, make as never)).rejects.toMatchObject({ kind: 'no_frame' })
    expect(make).not.toHaveBeenCalled()
  })
  it('an encoder that returns null fails with encode_failed', async () => {
    const c: PhotoCanvas = { width: 0, height: 0, getContext: () => null, toBlob: (cb) => cb(null) }
    await expect(drawToJpeg('src', 100, 100, () => c)).rejects.toMatchObject({ kind: 'encode_failed' })
  })
})

describe('label matches: search_failed', () => {
  const base = (matches: Record<string, unknown>) => ({
    mode: 'live',
    trace: [],
    reading: { legibility: 'clear', fields: { device_name: { value: 'X', legibility: 'clear' } } },
    matches,
    confirmed: null,
  })
  it('keeps search_failed and the note from the server', () => {
    const r = parseLabelResponse(base({ status: 'no_match_found', candidates: [], search_failed: true, note: 'openFDA could not be searched, so there is no match result for this photo.' }))
    expect(r?.matches.search_failed).toBe(true)
    expect(r?.matches.note).toMatch(/could not be searched/)
    expect(r?.matches.candidates).toEqual([])
  })
  it('a plain no match has neither flag nor note', () => {
    const r = parseLabelResponse(base({ status: 'no_match_found', candidates: [] }))
    expect(r?.matches.search_failed).toBeUndefined()
    expect(r?.matches.note).toBeUndefined()
  })
  it('real-API candidates with null fields do not turn into the text "null"', () => {
    const r = parseLabelResponse(base({ status: 'needs_person_to_confirm', candidates: [{ k_number: null, device_name: null, applicant: null, product_code: null, why_matched: [], why_not_matched: [], links: [] }] }))
    expect(r?.matches.candidates[0]).toMatchObject({ k_number: '', device_name: '', applicant: '', product_code: '' })
  })
})
