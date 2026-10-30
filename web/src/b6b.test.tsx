import { renderToStaticMarkup } from 'react-dom/server'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import audit from '../public/data/audit.json'
import briefs from '../public/data/briefs.json'
import dossier from '../public/data/dossier.json'
import evidence from '../public/data/evidence.json'
import investigations from '../public/data/investigations.json'
import manifest from '../public/data/manifest.json'
import protocol from '../public/data/protocol.json'
import schedules from '../public/data/schedules.json'
import sources from '../public/data/sources.json'
import sweep from '../public/data/sweep.json'
import threads from '../public/data/threads.json'
import vision from '../public/data/vision.json'
import { CaptureView } from './components/CaptureView'
import { Composer } from './components/Composer'
import { TraceView } from './components/TraceView'
import {
  checkFile,
  FAILURE_TEXT,
  parseLabel,
  parseVoice,
  PHOTO_WARNING,
  sendCapture,
  VOICE_WARNING,
} from './capture'
import { buildLabelTrace, buildReviewTrace, buildThreadTrace, NOT_RECORDED, argsSummary, modelBadge } from './trace'
import { exactKnownCode, knownCodes, moveActive, suggest } from './typeahead'
import type { Brief, Thread, WorkspaceData } from './types'

beforeAll(() => {
  ;(globalThis as unknown as { window: unknown }).window = { matchMedia: () => ({ matches: true }) }
})

const T = threads.threads as unknown as Thread[]
const B = briefs.briefs as unknown as Brief[]
const data = {
  manifest,
  threads,
  briefs: briefs.briefs,
  sources: sources.sources,
  schedules: schedules.schedules,
  investigations,
  evidence,
  audit,
  dossier,
  vision,
  sweep,
  protocol,
} as unknown as WorkspaceData

const text = (html: string) =>
  html
    .replace(/<[^>]+>/g, ' ')
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')

const FORBIDDEN = [
  /FDA-approved/i,
  /Part 11 compliant/i,
  /\bvalidated\b/i,
  /overnight/i,
  /worsening signals/i,
  /citation-checked/i,
  /complaint data/i,
  /\bsafe\b/i,
  /\bunsafe\b/i,
  /\bcompliant\b/i,
  /coming soon/i,
]

describe('agent trace', () => {
  it('lists planning, each tool call, the gate check and done, with model badges', () => {
    const t = T.find((x) => x.tool_steps.length >= 2 && !x.voice)!
    const tr = buildThreadTrace(t)
    expect(tr.steps.map((s) => s.kind)).toEqual(['plan', ...t.tool_steps.map(() => 'tool'), 'gate', 'done'])
    expect(tr.steps[0].model).toBe('Muse Spark')
    expect(tr.steps[1].detail).toContain(t.tool_steps[0].summary)
    expect(tr.steps[1].detail).toContain('Arguments:')
    expect(tr.beforeGate).toBe(1 + t.tool_steps.length)
  })

  it('shows "not recorded" for per-step time, tokens and cost and never a number', () => {
    for (const t of T) {
      const tr = buildThreadTrace(t)
      for (const s of tr.steps) {
        expect(s.time).toEqual({ text: NOT_RECORDED, recorded: false })
        expect(s.tokens).toEqual({ text: NOT_RECORDED, recorded: false })
        expect(s.cost).toEqual({ text: NOT_RECORDED, recorded: false })
      }
      // No recording stores a duration, so the run-level time is also not recorded.
      expect(tr.usage.time.recorded).toBe(false)
    }
  })

  it('takes run-level tokens and cost from the stored usage only', () => {
    const t = T.find((x) => x.usage)!
    const tr = buildThreadTrace(t)
    expect(tr.usage.tokens.text).toContain(t.usage!.input_tokens.toLocaleString('en-US'))
    expect(tr.usage.cost.text).toBe(`$${t.usage!.cost_usd.toFixed(4)}`)
    const bare = buildThreadTrace({ ...t, usage: null })
    expect(bare.usage.tokens.text).toBe(NOT_RECORDED)
    expect(bare.usage.cost.text).toBe(NOT_RECORDED)
    // A duration appears only if the recording stored one.
    expect(buildThreadTrace({ ...t, usage: { ...t.usage!, duration_s: 4.25 } }).usage.time.text).toBe('4.3 s')
  })

  it('adds a Voice Transcribe "Heard" step first for voice threads', () => {
    const t = T.find((x) => x.voice)!
    const tr = buildThreadTrace(t)
    expect(tr.steps[0].kind).toBe('heard')
    expect(tr.steps[0].title).toBe('Heard')
    expect(tr.steps[0].model).toBe('Voice Transcribe')
    expect(tr.steps[0].detail).toContain(t.voice!.audio_seconds.toFixed(1))
  })

  it('reports the first pass and the withheld reasons of the gate', () => {
    const t = T.find((x) => x.sentences.some((s) => s.status === 'block'))!
    const gate = buildThreadTrace(t).steps.find((s) => s.kind === 'gate')!
    const reasons = t.sentences.filter((s) => s.status !== 'pass').flatMap((s) => s.reasons)
    expect(gate.lines).toEqual(reasons)
    expect(gate.lines.length).toBeGreaterThan(0)
    expect(gate.detail).toContain(`${t.first_pass!.passed} passed, ${t.first_pass!.blocked} blocked`)
    const none = buildThreadTrace({ ...t, first_pass: null }).steps.find((s) => s.kind === 'gate')!
    expect(none.detail).toContain('First pass: not recorded')
  })

  it('labels the vision run SAM 3.1 + Muse Spark and the dossier review Muse Wonder', () => {
    const l = vision.labels[0] as never
    const tr = buildLabelTrace(l)
    expect(tr.steps[0].model).toBe('SAM 3.1')
    expect(tr.steps[1].model).toBe('Muse Spark')
    expect(tr.steps[0].time.recorded).toBe(false)
    const review = buildReviewTrace(dossier.review as never)
    expect(review.steps[0].model).toBe('Muse Wonder')
    expect(review.steps[0].time.text).toBe(NOT_RECORDED)
  })

  it('summarizes arguments and model names', () => {
    expect(argsSummary({})).toBe('no arguments')
    expect(argsSummary({ report_id: '1', n: 3 })).toBe('report_id: 1, n: 3')
    expect(modelBadge('muse-spark-1.3')).toBe('Muse Spark')
    expect(modelBadge('muse-wonder-1.0')).toBe('Muse Wonder')
  })

  it('renders "not recorded" per step, the whole-run line and the replay note, with no forbidden wording', () => {
    const t = T.find((x) => x.tool_steps.length > 0)!
    const tr = buildThreadTrace(t)
    const html = text(renderToStaticMarkup(<TraceView trace={tr} shown={tr.steps.length} />))
    expect(html).toContain('Time: not recorded')
    expect(html).toContain('Whole run')
    expect(html).toContain('Replayed from a recording')
    for (const re of FORBIDDEN) expect(html).not.toMatch(re)
    // While the replay is part-way, later steps and the whole-run line are not shown yet.
    const part = text(renderToStaticMarkup(<TraceView trace={tr} shown={1} />))
    expect(part).not.toContain('Gate check')
    expect(part).not.toContain('Whole run')
  })
})

describe('composer type-ahead', () => {
  const codes = knownCodes(sweep as never, B)

  it('collects codes from the sweep and the briefs only', () => {
    expect(codes.length).toBeGreaterThan(10)
    expect(codes.some((c) => c.code === 'LLZ')).toBe(true)
    const stored = new Set([...(sweep.rows as { product_code: string }[]).map((r) => r.product_code)])
    for (const b of B) for (const c of Object.keys(b.device_types ?? {})) stored.add(c)
    for (const b of B) for (const s of b.signals) stored.add(s.product_code)
    for (const c of codes) expect(stored.has(c.code)).toBe(true)
    expect(codes.find((c) => c.code === 'LLZ')?.name).toContain('Image Processing')
  })

  it('suggests recorded questions and device codes for typed text', () => {
    const q = suggest('recall', T, codes)
    expect(q.length).toBeGreaterThan(0)
    for (const s of q) if (s.kind === 'question') expect(T.some((t) => t.id === s.thread.id)).toBe(true)
    const c = suggest('ll', T, codes)
    expect(c.some((s) => s.kind === 'code' && s.code === 'LLZ')).toBe(true)
    expect(suggest('', T, codes)).toEqual([])
  })

  it('puts an exactly typed code first, even if it is not in the stored data', () => {
    const known = suggest('llz', T, codes)
    expect(known[0]).toMatchObject({ kind: 'code', code: 'LLZ', known: true })
    const unknown = suggest('zzq', T, codes)
    expect(unknown[0]).toMatchObject({ kind: 'code', code: 'ZZQ', known: false })
    expect(exactKnownCode('llz', codes)).toBe('LLZ')
    expect(exactKnownCode('zzq', codes)).toBeNull()
  })

  it('moves the highlight with ArrowDown and ArrowUp and wraps', () => {
    expect(moveActive(-1, 'ArrowDown', 3)).toBe(0)
    expect(moveActive(0, 'ArrowDown', 3)).toBe(1)
    expect(moveActive(2, 'ArrowDown', 3)).toBe(0)
    expect(moveActive(-1, 'ArrowUp', 3)).toBe(2)
    expect(moveActive(0, 'ArrowUp', 3)).toBe(2)
    expect(moveActive(2, 'ArrowUp', 3)).toBe(1)
    expect(moveActive(1, 'Enter', 3)).toBe(1)
    expect(moveActive(1, 'ArrowDown', 0)).toBe(-1)
  })

  it('renders a combobox with listbox semantics and camera and mic buttons', () => {
    const html = renderToStaticMarkup(
      <Composer threads={T} onThread={() => {}} viewKey="new" codes={codes} onCode={() => {}} onCamera={() => {}} onMic={() => {}} />,
    )
    expect(html).toContain('role="combobox"')
    expect(html).toContain('aria-autocomplete="list"')
    expect(html).toContain('data-testid="composer-camera"')
    expect(html).toContain('data-testid="composer-mic"')
  })
})

describe('camera and mic', () => {
  const png = () => new Blob([new Uint8Array([1, 2, 3])], { type: 'image/png' })
  const wav = () => new Blob([new Uint8Array([1, 2, 3])], { type: 'audio/wav' })
  const never = vi.fn(async () => new Response('{}'))

  it('shows the patient-data warning before any upload', () => {
    expect(PHOTO_WARNING).toBe("Don't photograph patients or patient data. Photos are not stored unless you choose to.")
    const html = text(
      renderToStaticMarkup(<CaptureView mode="label" data={data} onThread={() => {}} onLabel={() => {}} apiBase={null} />),
    )
    expect(html).toContain(PHOTO_WARNING)
    expect(html.indexOf(PHOTO_WARNING)).toBeLessThan(html.indexOf('Take a photo'))
    const raw = renderToStaticMarkup(<CaptureView mode="label" data={data} onThread={() => {}} onLabel={() => {}} apiBase={null} />)
    expect(raw).toContain('accept="image/*"')
    expect(raw).toContain('capture="environment"')
    const voice = text(
      renderToStaticMarkup(<CaptureView mode="voice" data={data} onThread={() => {}} onLabel={() => {}} apiBase={null} />),
    )
    expect(voice).toContain(VOICE_WARNING)
  })

  it('falls back to the recorded example, labelled "Recorded run", when no API is set', () => {
    const label = text(
      renderToStaticMarkup(<CaptureView mode="label" data={data} onThread={() => {}} onLabel={() => {}} apiBase={null} />),
    )
    expect(label).toContain('Recorded run')
    expect(label).toContain(FAILURE_TEXT.unconfigured)
    expect(label).not.toContain('Live result')
    expect(label).toContain('SAM 3.1')
    const voice = text(
      renderToStaticMarkup(<CaptureView mode="voice" data={data} onThread={() => {}} onLabel={() => {}} apiBase={null} />),
    )
    expect(voice).toContain('Recorded run')
    expect(voice).toContain('Voice Transcribe')
    expect(voice).toContain('Heard:')
    for (const re of FORBIDDEN) {
      expect(label).not.toMatch(re)
      expect(voice).not.toMatch(re)
    }
  })

  it('sends nothing when the API base is not set', async () => {
    const out = await sendCapture('label', { blob: png(), name: 'a.png' }, { apiBase: null, fetcher: never })
    expect(out).toMatchObject({ ok: false, reason: 'unconfigured' })
    expect(never).not.toHaveBeenCalled()
  })

  it('rejects a wrong, empty or oversized file before sending', async () => {
    expect(checkFile('label', { size: 10, type: 'audio/wav' })).toBe('wrong-type')
    expect(checkFile('voice', { size: 10, type: 'image/png' })).toBe('wrong-type')
    expect(checkFile('label', { size: 0, type: 'image/png' })).toBe('empty')
    expect(checkFile('label', { size: 13 * 1024 * 1024, type: 'image/png' })).toBe('too-large')
    expect(checkFile('voice', { size: 100, type: 'audio/webm' })).toBeNull()
    const out = await sendCapture('voice', { blob: png(), name: 'x.png' }, { apiBase: 'https://api.example', fetcher: never })
    expect(out).toMatchObject({ ok: false, reason: 'wrong-type' })
    expect(never).not.toHaveBeenCalled()
  })

  it('falls back with the reason on 404, 429, errors and unreadable answers', async () => {
    const run = (res: () => Promise<Response>, mode: 'label' | 'voice' = 'label') =>
      sendCapture(mode, { blob: mode === 'label' ? png() : wav(), name: 'f' }, { apiBase: 'https://api.example', fetcher: res })
    expect(await run(async () => new Response('', { status: 404 }))).toMatchObject({ ok: false, reason: 'not-found' })
    expect(await run(async () => new Response('', { status: 429 }))).toMatchObject({ ok: false, reason: 'rate' })
    expect(await run(async () => new Response('', { status: 500 }))).toMatchObject({ ok: false, reason: 'server' })
    expect(
      await run(async () => {
        throw new TypeError('network down')
      }),
    ).toMatchObject({ ok: false, reason: 'network' })
    expect(await run(async () => new Response('not json'))).toMatchObject({ ok: false, reason: 'bad-response' })
    expect(await run(async () => new Response(JSON.stringify({ hello: 1 })))).toMatchObject({ ok: false, reason: 'bad-response' })
    expect(await run(async () => new Response(JSON.stringify({ hello: 1 })), 'voice')).toMatchObject({ ok: false, reason: 'bad-response' })
  })

  it('posts the photo to /v1/label and the recording to /v1/voice', async () => {
    const urls: string[] = []
    const f = async (u: string, init?: RequestInit) => {
      urls.push(`${init?.method} ${u}`)
      return new Response('{}', { status: 404 })
    }
    await sendCapture('label', { blob: png(), name: 'a.png' }, { apiBase: 'https://api.example', fetcher: f })
    await sendCapture('voice', { blob: wav(), name: 'a.wav' }, { apiBase: 'https://api.example', fetcher: f })
    expect(urls).toEqual(['POST https://api.example/v1/label', 'POST https://api.example/v1/voice'])
  })

  it('accepts a real answer only if it has the stored shape, and streams steps as they arrive', async () => {
    const label = vision.labels[0]
    expect(parseLabel(label)).not.toBeNull()
    expect(parseLabel({ reading: label })).not.toBeNull()
    expect(parseLabel({ fields: {} })).toBeNull()
    expect(parseVoice({ transcript_text: 'what changed', language: 'English' })).toMatchObject({ transcript: 'what changed', thread: null })
    expect(parseVoice({ transcript_text: '  ' })).toBeNull()
    const lines = [
      JSON.stringify({ type: 'step', name: 'sam', summary: 'found 1 box' }),
      JSON.stringify({ type: 'step', name: 'read', summary: 'read 3 fields' }),
      JSON.stringify({ type: 'result', result: label }),
    ].join('\n')
    const seen: string[] = []
    const out = await sendCapture(
      'label',
      { blob: png(), name: 'a.png' },
      {
        apiBase: 'https://api.example',
        fetcher: async () => new Response(lines, { headers: { 'content-type': 'application/x-ndjson' } }),
        onStep: (s) => seen.push(s.name),
      },
    )
    expect(out).toMatchObject({ ok: true, mode: 'label' })
    expect(seen).toEqual(['sam', 'read'])
  })
})
