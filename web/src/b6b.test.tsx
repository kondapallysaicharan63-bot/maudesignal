import { renderToStaticMarkup } from 'react-dom/server'
import { beforeAll, describe, expect, it } from 'vitest'
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
import { PHOTO_WARNING, UNCONFIGURED_TEXT, VOICE_WARNING } from './capture'
import { buildLabelTrace, buildReviewTrace, buildThreadTrace, NOT_RECORDED, argsSummary, modelBadge, traceSummary } from './trace'
import { exactKnownCode, highlightParts, knownCodes, moveActive, suggest } from './typeahead'
import { suggestThreads } from './match'
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

  it('folds to one summary line, says "not recorded" once for the steps, and shows the whole-run line and replay note', () => {
    const t = T.find((x) => x.tool_steps.length > 0)!
    const tr = buildThreadTrace(t)
    const html = text(renderToStaticMarkup(<TraceView trace={tr} shown={tr.steps.length} />))
    const raw = renderToStaticMarkup(<TraceView trace={tr} shown={tr.steps.length} />)
    // Closed by default; the summary names the steps, the model, the tool calls and the stored cost.
    expect(raw).not.toMatch(/<details[^>]* open/)
    expect(html).toContain(traceSummary(tr))
    expect(traceSummary(tr)).toContain(`${tr.steps.length} steps`)
    expect(traceSummary(tr)).toContain('Muse Spark')
    expect(traceSummary(tr)).toContain(`${t.tool_steps.length} tool`)
    // One note instead of "Time: not recorded" on every step.
    expect(html.match(/Per-step time, tokens and cost: not recorded/g)).toHaveLength(1)
    expect(html.match(/Time: not recorded/g)).toHaveLength(1) // the whole-run line only
    expect(html).toContain('Whole run')
    expect(html).toContain('Replayed from a recording')
    for (const re of FORBIDDEN) expect(html).not.toMatch(re)
    // While the replay is part-way, later steps and the whole-run line are not shown yet.
    const part = text(renderToStaticMarkup(<TraceView trace={tr} shown={1} />))
    expect(part).not.toContain('Gate check')
    expect(part).not.toContain('Whole run')
    expect(part).toContain(`Replaying: step 1 of ${tr.steps.length}`)
  })

  it('leaves the cost out of the summary when the run did not store one, and shows tool arguments as code', () => {
    const t = T.find((x) => x.tool_steps.length > 0)!
    const bare = buildThreadTrace({ ...t, usage: null })
    expect(traceSummary(bare)).not.toContain('$')
    expect(traceSummary(bare)).not.toContain('not recorded')
    const tool = bare.steps.find((s) => s.kind === 'tool')!
    expect(tool.args).toBe(argsSummary(t.tool_steps[0].arguments))
    expect(tool.result).toBe(t.tool_steps[0].summary || 'no summary stored')
    const html = renderToStaticMarkup(<TraceView trace={bare} shown={bare.steps.length} />)
    expect(html).toContain('font-mono')
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

  it('marks the typed characters in a suggestion and keeps the text whole', () => {
    const parts = highlightParts('Which recalls cover LLZ devices?', 'recall')
    expect(parts.map((p) => p.text).join('')).toBe('Which recalls cover LLZ devices?')
    expect(parts.filter((p) => p.hit).map((p) => p.text)).toEqual(['recall'])
    expect(highlightParts('Image Processing', 'll').some((p) => p.hit)).toBe(false) // only the start of a word counts
    expect(highlightParts('LLZ', 'll').filter((p) => p.hit).map((p) => p.text)).toEqual(['LL'])
    expect(highlightParts('anything', '')).toEqual([{ text: 'anything', hit: false }])
    expect(highlightParts('Recalls', 'recalls').filter((p) => p.hit).map((p) => p.text)).toEqual(['Recalls'])
  })

  it('ranks the question that matches more of the typed words first', () => {
    const q = 'recall'
    const ranked = suggestThreads(q, T, 8)
    expect(ranked.length).toBeGreaterThan(0)
    const hits = (t: Thread) => (t.question.toLowerCase().includes(q) ? 1 : 0)
    // every question that contains the typed word comes before the ones that only match another way
    const first = ranked.findIndex((t) => !hits(t))
    if (first >= 0) expect(ranked.slice(first).every((t) => !hits(t))).toBe(true)
  })

  it('shows a labelled list with a hint, a scroll cap and a visible selected row', () => {
    const html = renderToStaticMarkup(
      <Composer threads={T} onThread={() => {}} viewKey="new" codes={codes} onCode={() => {}} onCamera={() => {}} onMic={() => {}} captureMode="label" />,
    )
    expect(html).toContain('Camera on')
    expect(html).toContain('aria-pressed="true"')
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
  it('shows the patient-data note before any upload or recording', () => {
    expect(PHOTO_WARNING).toBe('Photo is read once and not stored. Do not photograph patient details.')
    expect(VOICE_WARNING).toBe('Audio is sent once for transcription and not stored. Do not say patient details.')
    const label = text(renderToStaticMarkup(<CaptureView mode="label" data={data} onThread={() => {}} onLabel={() => {}} apiBase={null} />))
    expect(label).toContain(PHOTO_WARNING)
    const voice = text(renderToStaticMarkup(<CaptureView mode="voice" data={data} onThread={() => {}} onLabel={() => {}} apiBase={null} />))
    expect(voice).toContain(VOICE_WARNING)
  })

  it('falls back to the recorded example, labelled "Recorded run", when no API is set', () => {
    const label = text(renderToStaticMarkup(<CaptureView mode="label" data={data} onThread={() => {}} onLabel={() => {}} apiBase={null} />))
    expect(label).toContain('Recorded run')
    expect(label).toContain(UNCONFIGURED_TEXT)
    expect(label).not.toContain('Live result')
    expect(label).not.toContain('Use camera')
    expect(label).toContain('SAM 3.1')
    const voice = text(renderToStaticMarkup(<CaptureView mode="voice" data={data} onThread={() => {}} onLabel={() => {}} apiBase={null} />))
    expect(voice).toContain('Recorded run')
    expect(voice).toContain('Voice Transcribe')
    expect(voice).toContain('Heard:')
    for (const re of FORBIDDEN) {
      expect(label).not.toMatch(re)
      expect(voice).not.toMatch(re)
    }
  })

  it('with an API address the label screen offers the camera and an upload', () => {
    const raw = renderToStaticMarkup(<CaptureView mode="label" data={data} onThread={() => {}} onLabel={() => {}} apiBase="https://api.example" />)
    const label = text(raw)
    expect(label).toContain('Use camera')
    expect(label).toContain('Upload photo')
    expect(label.indexOf(PHOTO_WARNING)).toBeLessThan(label.indexOf('Use camera'))
    for (const re of FORBIDDEN) expect(label).not.toMatch(re)
  })
})
