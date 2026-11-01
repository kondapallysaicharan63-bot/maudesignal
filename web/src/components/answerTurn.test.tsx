// @vitest-environment jsdom
// The v2 answer turn (?layout=v2) mounted in jsdom with a fake fetch: the quiet chip per route, Details closed by
// default, Copy, Read aloud (voice choice, one utterance per sentence, Stop, hidden when unsupported), thumbs up / down
// with a reason (one rating per answer), and the classic layout left exactly as it was.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import evidence from '../../public/data/evidence.json'
import threads from '../../public/data/threads.json'
import type { FetchLike } from '../feedback'
import type { LayoutMode } from '../layoutFlag'
import { stopReading } from '../live/readAloud'
import { useLiveChat } from '../live/useLiveChat'
import type { Evidence, Thread } from '../types'
import { LiveChatView } from './LiveChat'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const T = threads.threads as unknown as Thread[]
const EV = evidence as unknown as Evidence
const QUESTION = 'What changed this week for LLZ?'

const liveBody = (extra: Record<string, unknown> = {}) => ({
  mode: 'live',
  tier: 'live',
  not_medical_advice: true,
  trace: [
    { step: 'Muse Spark answers from stored records', model: 'muse-spark-1.3', ms: 812, status: 'ok' },
    { step: 'Read-only tools and claim gate', model: null, ms: 6, status: 'ok', note: '1 tool call(s)' },
  ],
  cost_usd: 0.0123,
  usage: { input_tokens: 1200, output_tokens: 140 },
  limits: { remaining_today: 9, resets_utc: '2026-11-01T00:00:00Z' },
  answer: {
    speakable: [
      { text: '33 reports were stored for the week (report 50426770).', links: [{ label: 'Report 50426770', url: 'https://www.accessdata.fda.gov/r?id=50426770' }] },
      { text: 'Two device types had more serious reports than usual.', links: [] },
    ],
    withheld: [{ reason: 'a number did not match the stored data' }],
    spoken_text: '33 reports were stored for the week (report 50426770). Two device types had more serious reports than usual. https://x.example',
  },
  ...extra,
})
const greeting = {
  mode: 'canned',
  tier: 'canned',
  badge: 'No FDA facts in this message',
  not_medical_advice: true,
  trace: [{ step: 'Fixed reply, no model call', model: null, ms: 0, status: 'ok' }],
  cost_usd: 0,
  limits: { remaining_today: 30, resets_utc: '2026-11-01T00:00:00Z' },
  suggestions: ['What changed this week?'],
  answer: { speakable: [{ text: 'Hello. Ask about FDA device reports.', links: [] }], withheld: [], spoken_text: 'Hello. Ask about FDA device reports.' },
}
const res = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

let host: HTMLDivElement
let root: Root
let fetcher: ReturnType<typeof vi.fn<(u: string, i?: RequestInit) => Promise<Response>>>
let rateFetch: ReturnType<typeof vi.fn<(u: string, i: RequestInit) => Promise<FetchLike>>>
let chat: ReturnType<typeof useLiveChat> | null = null

interface Utter {
  text: string
  rate: number
  voice: { name: string } | null
  onend: (() => void) | null
  onerror: (() => void) | null
}
interface Synth {
  spoken: Utter[]
  cancelled: number
  voices: { name: string; lang: string; default?: boolean; localService?: boolean }[]
  listeners: (() => void)[]
}
let synth: Synth

const VOICES: Synth['voices'] = [
  { name: 'Microsoft David - English (United States)', lang: 'en-US', default: true, localService: true },
  { name: 'Microsoft Jenny Online (Natural) - English (United States)', lang: 'en-US', localService: false },
  { name: 'Microsoft Aria (Natural) - English (United States)', lang: 'en-US', localService: true },
]

function installSpeech(voices: Synth['voices']) {
  synth = { spoken: [], cancelled: 0, voices, listeners: [] }
  const Utter = function (this: Record<string, unknown>, t: string) {
    this.text = t
    this.rate = 1
    this.voice = null
    this.onend = null
    this.onerror = null
  } as unknown
  ;(window as unknown as { SpeechSynthesisUtterance: unknown }).SpeechSynthesisUtterance = Utter
  ;(globalThis as unknown as { SpeechSynthesisUtterance: unknown }).SpeechSynthesisUtterance = Utter
  ;(window as unknown as { speechSynthesis: unknown }).speechSynthesis = {
    speaking: false,
    cancel: () => {
      synth.cancelled++
    },
    speak: (u: Utter) => synth.spoken.push(u),
    getVoices: () => synth.voices,
    addEventListener: (_: string, f: () => void) => synth.listeners.push(f),
    removeEventListener: () => undefined,
  }
}
function removeSpeech() {
  delete (window as unknown as { speechSynthesis?: unknown }).speechSynthesis
  delete (window as unknown as { SpeechSynthesisUtterance?: unknown }).SpeechSynthesisUtterance
  delete (globalThis as unknown as { SpeechSynthesisUtterance?: unknown }).SpeechSynthesisUtterance
}

function Harness({ layout }: { layout?: LayoutMode }) {
  const live = useLiveChat({ apiBase: 'https://api.example', ref: null, threads: T, evidence: EV, fetcher: (u, i) => fetcher(u, i) })
  chat = live
  return (
    <LiveChatView
      chat={live}
      threads={T}
      onStarter={(q) => void live.ask(q)}
      onRecordedVoice={() => undefined}
      layout={layout}
      rating={{ apiBase: 'https://api.example', refCode: 'TEST-0', fetcher: (u, i) => rateFetch(u, i) }}
    />
  )
}

const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 30)) })
const q = (id: string) => host.querySelector(`[data-testid="${id}"]`) as HTMLElement | null
const text = () => host.textContent ?? ''

async function mount(layout?: LayoutMode) {
  await act(async () => root.render(<Harness layout={layout} />))
}
async function ask(body: unknown, question = QUESTION) {
  fetcher.mockResolvedValueOnce(res(200, body))
  await act(async () => {
    chat!.ask(question)
  })
  await flush()
}
async function typeReason(box: HTMLTextAreaElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(box, value)
    box.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

beforeEach(() => {
  window.matchMedia = ((query: string) => ({ matches: query.includes('reduce'), addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
  installSpeech(VOICES)
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  fetcher = vi.fn()
  rateFetch = vi.fn(async () => ({ ok: true, status: 201 }))
})
afterEach(async () => {
  stopReading()
  await act(async () => root.unmount())
  host.remove()
  chat = null
  window.history.replaceState(null, '', '/')
})

describe('v2 answer turn', () => {
  it('a live answer: the reading text, source chips, Verified / Withheld, one chip "Muse Spark 1.3 · Live", nothing noisy', async () => {
    await mount('v2')
    await ask(liveBody())
    const ans = q('live-answer')!
    expect(ans.getAttribute('data-layout')).toBe('v2')
    expect(q('model-chip')?.textContent).toBe('Muse Spark 1.3 · Live')
    expect(host.querySelectorAll('[data-testid="model-chip"]')).toHaveLength(1)
    expect(q('answer-sentences')?.className).toContain('t-answer')
    expect(q('sentence-links')?.querySelector('a')?.getAttribute('href')).toBe('https://www.accessdata.fda.gov/r?id=50426770')
    expect(q('mark-verified')?.textContent).toContain('Verified')
    expect(q('held-back')?.textContent).toContain('1 sentence held back: a number did not match the stored data')
    expect(text()).not.toContain('Cost of this answer')
    expect(text()).not.toContain('812 ms')
    expect(q('live-trace')).toBeNull()
    expect(q('mode-badge')).toBeNull()
    expect(q('limits')).toBeNull()
    expect(q('answer-time')?.textContent).toMatch(/^\d{1,2}:\d{2} (AM|PM)$/)
  })

  it('sources sit below the answer under "Sources"; no per-answer advice line (Copy keeps it)', async () => {
    const written: string[] = []
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (s: string) => void written.push(s) } })
    await mount('v2')
    await ask(liveBody())
    const ans = q('live-answer')!
    const src = q('answer-sources')!
    expect(src.querySelector('.ans-sources-label')?.textContent).toBe('Sources')
    expect(q('answer-sentences')!.querySelector('a')).toBeNull()
    expect(q('answer-sentences')!.compareDocumentPosition(src) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(src.querySelectorAll('a')).toHaveLength(1)
    expect(ans.querySelector('[data-testid="not-advice"]')).toBeNull()
    expect(ans.textContent).not.toContain('Not medical advice')
    await act(async () => q('action-copy')!.click())
    await flush()
    expect(written[0]).toContain('Not medical advice')
  })

  it('only the chosen thumb looks selected; an open reason box does not', async () => {
    await mount('v2')
    await ask(liveBody())
    await act(async () => q('action-down')!.click())
    expect(q('action-down')!.className).not.toContain('ans-ib--chosen')
    expect(q('action-up')!.className).not.toContain('ans-ib--chosen')
    await act(async () => q('rating-send')!.click())
    await flush()
    expect(q('action-down')!.className).toContain('ans-ib--chosen')
    expect(q('action-up')!.className).not.toContain('ans-ib--chosen')
    expect(q('action-up')!.getAttribute('aria-pressed')).toBe('false')
  })

  it('a greeting is an "Instant answer" with no FDA-facts line and no cost line', async () => {
    await mount('v2')
    await ask(greeting, 'namaste')
    expect(q('model-chip')?.textContent).toBe('Instant answer')
    expect(text()).not.toContain('No FDA facts in this message')
    expect(text()).not.toContain('Fixed reply, no model call')
    expect(text()).not.toMatch(/\$0\.0000/)
    expect(q('mark-verified')).toBeNull()
    expect(host.querySelectorAll('[data-testid="suggestion-chip"]')).toHaveLength(1)
  })

  it('direct, cached and recorded answers get their own chip; a cached answer shows when it was first answered', async () => {
    await mount('v2')
    await ask({ ...greeting, mode: 'direct', tier: 'direct', badge: 'Direct FDA lookup — no AI' }, 'Recalls for QIH')
    await ask({ ...liveBody(), tier: 'cache', answered_at: '2026-11-01T10:15:00Z' }, 'Again?')
    fetcher.mockRejectedValueOnce(new TypeError('offline'))
    await act(async () => {
      chat!.ask('What changed this week?')
    })
    await flush()
    const chips = Array.from(host.querySelectorAll('[data-testid="model-chip"]')).map((c) => c.textContent)
    expect(chips[0]).toBe('Instant answer')
    expect(chips[1]).toBe('Cached')
    expect(chips[2]).toMatch(/^Recorded · [A-Z][a-z]{2} \d{1,2}, \d{4}$/)
    expect(q('recorded-note')).not.toBeNull()
    const times = Array.from(host.querySelectorAll('[data-testid="answer-time"]'))
    expect(times[1].getAttribute('datetime')).toBe('2026-11-01T10:15:00.000Z')
  })

  it('a voice turn names Muse Voice Transcribe, and in v2 its auto-read goes through the answer\'s own button', async () => {
    window.history.replaceState(null, '', '/?layout=v2')
    await mount('v2')
    const body = liveBody({ heard: 'what changed', trace: [{ step: 'Muse Voice Transcribe', model: 'muse-voice-transcribe-1.0', ms: 540, status: 'ok' }, ...liveBody().trace] })
    fetcher.mockResolvedValueOnce(res(200, body))
    await act(async () => {
      await chat!.askVoice(new Blob([new Uint8Array(44)], { type: 'audio/wav' }))
    })
    await flush()
    expect(q('model-chip')?.textContent).toBe('Muse Voice Transcribe + Muse Spark 1.3 · Live')
    expect(synth.spoken.map((u) => u.text)).toEqual(['33 reports were stored for the week.', 'Two device types had more serious reports than usual.'])
    expect(synth.spoken[0].voice?.name).toContain('Aria (Natural)')
    expect(q('action-read')?.getAttribute('aria-label')).toBe('Stop reading aloud')
    await act(async () => q('action-read')!.click())
    expect(q('action-read')?.getAttribute('aria-label')).toBe('Read aloud')
  })

  it('classic voice auto-read keeps the old path (spoken_text as is)', async () => {
    await mount('classic')
    fetcher.mockResolvedValueOnce(res(200, liveBody({ heard: 'what changed' })))
    await act(async () => {
      await chat!.askVoice(new Blob([new Uint8Array(44)], { type: 'audio/wav' }))
    })
    await flush()
    expect(synth.spoken).toHaveLength(1)
    expect(synth.spoken[0].text).toContain('(report 50426770)')
  })

  it('"questions left" shows only when 5 or fewer remain', async () => {
    await mount('v2')
    await ask(liveBody({ limits: { remaining_today: 5, resets_utc: '' } }))
    expect(q('limits')?.textContent).toBe('5 live questions left today')
  })

  it('Details is closed by default, opens the trace, cost, tokens, timings and tier; Escape closes it and returns focus', async () => {
    await mount('v2')
    await ask(liveBody())
    const t = q('details-toggle')!
    expect(t.getAttribute('aria-expanded')).toBe('false')
    expect(t.getAttribute('aria-label')).toBe('Details')
    expect(q('answer-details')).toBeNull()
    await act(async () => t.click())
    expect(t.getAttribute('aria-expanded')).toBe('true')
    const panel = q('answer-details')!
    expect(t.getAttribute('aria-controls')).toBe(panel.id)
    expect(q('details-tier')?.textContent).toBe('Live model answer')
    expect(q('details-cost')?.textContent).toBe('$0.0123')
    expect(q('details-tokens')?.textContent).toBe('1200 in · 140 out')
    expect(q('details-time')?.textContent).toBe('818 ms across 2 steps')
    const steps = panel.querySelectorAll('[data-testid="trace-step"]')
    expect(steps).toHaveLength(2)
    expect(steps[0].textContent).toContain('Muse Spark 1.3 · 812 ms')
    expect(steps[0].querySelector('.sr-only')?.textContent).toBe('done')
    expect(steps[0].querySelector('svg')).not.toBeNull()
    expect(panel.querySelector('.ans-sub')?.textContent).toBe('Steps')
    await act(async () => panel.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
    expect(q('answer-details')).toBeNull()
    expect(t.getAttribute('aria-expanded')).toBe('false')
    expect(document.activeElement).toBe(t)
  })

  it('Copy puts the answer and its FDA links on the clipboard, not the question', async () => {
    const written: string[] = []
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (s: string) => void written.push(s) } })
    await mount('v2')
    await ask(liveBody())
    await act(async () => q('action-copy')!.click())
    await flush()
    expect(written).toHaveLength(1)
    expect(written[0]).toContain('33 reports were stored for the week')
    expect(written[0]).toContain('Report 50426770: https://www.accessdata.fda.gov/r?id=50426770')
    expect(written[0]).not.toContain(QUESTION)
    expect(q('action-copy')?.getAttribute('aria-label')).toBe('Copied')
    expect(q('copy-failed')).toBeNull()
  })

  it('a recorded answer copies with its label and note first', async () => {
    const written: string[] = []
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (s: string) => void written.push(s) } })
    await mount('v2')
    const note = 'No live model call was made. Shown instead: a recorded run that answered "What changed this week?" (recorded 2026-10-28).'
    await ask({ ...liveBody(), mode: 'recorded', tier: undefined, recorded_note: note })
    await act(async () => q('action-copy')!.click())
    await flush()
    expect(written[0].startsWith(`Recorded answer · Oct 28, 2026\n${note}\n\n`)).toBe(true)
  })

  it('a copy that fails says so in visible text', async () => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async () => { throw new Error('denied') } } })
    const exec = document.execCommand
    ;(document as unknown as { execCommand: () => boolean }).execCommand = () => false
    await mount('v2')
    await ask(liveBody())
    await act(async () => q('action-copy')!.click())
    await flush()
    expect(q('copy-failed')?.textContent).toContain("Couldn't copy")
    ;(document as unknown as { execCommand: typeof exec }).execCommand = exec
  })

  it('Read aloud picks an on-device Natural voice at 0.95, one utterance per sentence, only the answer; Stop cancels', async () => {
    await mount('v2')
    await ask(liveBody())
    const b = q('action-read')!
    expect(b.getAttribute('aria-label')).toBe('Read aloud')
    expect(b.hasAttribute('aria-pressed')).toBe(false)
    await act(async () => b.click())
    expect(synth.spoken).toHaveLength(2)
    for (const u of synth.spoken) {
      expect(u.voice?.name).toContain('Aria (Natural)')
      expect(u.rate).toBe(0.95)
      expect(u.text).not.toMatch(/https?:|50426770/)
    }
    expect(q('action-read')?.getAttribute('aria-label')).toBe('Stop reading aloud')
    const before = synth.cancelled
    await act(async () => q('action-read')!.click())
    expect(synth.cancelled).toBeGreaterThan(before)
    expect(q('action-read')?.getAttribute('aria-label')).toBe('Read aloud')
  })

  it('a late error from a cancelled reading does not clear the new one', async () => {
    await mount('v2')
    await ask(liveBody())
    await ask(liveBody(), 'Second question?')
    const reads = Array.from(host.querySelectorAll('[data-testid="action-read"]')) as HTMLButtonElement[]
    await act(async () => reads[0].click())
    const old = synth.spoken[0]
    await act(async () => reads[1].click())
    await act(async () => old.onerror?.())
    expect(reads[1].getAttribute('aria-label')).toBe('Stop reading aloud')
    expect(reads[0].getAttribute('aria-label')).toBe('Read aloud')
    // the new reading ends normally on its last sentence
    await act(async () => synth.spoken[synth.spoken.length - 1].onend?.())
    expect(reads[1].getAttribute('aria-label')).toBe('Read aloud')
  })

  it('voices that load late show the button on voiceschanged', async () => {
    installSpeech([])
    await mount('v2')
    await ask(liveBody())
    expect(q('action-read')).toBeNull()
    synth.voices = [{ name: 'Google US English', lang: 'en-US' }]
    await act(async () => synth.listeners.forEach((f) => f()))
    expect(q('action-read')).not.toBeNull()
  })

  it('Read aloud is hidden when the browser has no speechSynthesis', async () => {
    removeSpeech()
    await mount('v2')
    await ask(liveBody())
    expect(q('action-read')).toBeNull()
    expect(q('action-copy')).not.toBeNull()
  })

  it('thumbs up posts a rating with the answer id and no question text; further thumbs are ignored', async () => {
    await mount('v2')
    await ask(liveBody())
    await act(async () => q('action-up')!.click())
    await flush()
    expect(rateFetch).toHaveBeenCalledTimes(1)
    const [url, init] = rateFetch.mock.calls[0]
    expect(url).toBe('https://api.example/v1/feedback')
    expect(init.credentials).toBe('omit')
    const body = JSON.parse(init.body as string)
    expect(body).toMatchObject({ kind: 'answer_rating', rating: 5, comment: '', consent: 'no_quote', ref: 'TEST-0', page: 'live-answer' })
    expect(body.answer_id).toMatch(/^[A-Za-z0-9_-]{8,64}$/)
    expect(init.body as string).not.toContain('What changed')
    expect(init.body as string).not.toContain('33 reports')
    expect(q('action-up')?.getAttribute('aria-pressed')).toBe('true')
    expect(q('rating-status')?.textContent).toContain('Thanks')
    await act(async () => q('action-down')!.click())
    await act(async () => q('action-up')!.click())
    await flush()
    expect(q('rating-reason')).toBeNull()
    expect(rateFetch).toHaveBeenCalledTimes(1)
    expect(q('action-down')?.getAttribute('aria-disabled')).toBe('true')
  })

  it('thumbs down opens an optional reason box (300 characters at most), sends the reason, then focus returns to it', async () => {
    await mount('v2')
    await ask(liveBody())
    const down = q('action-down')!
    expect(down.hasAttribute('aria-pressed')).toBe(false)
    await act(async () => down.click())
    expect(down.getAttribute('aria-expanded')).toBe('true')
    const box = q('rating-reason')!.querySelector('textarea')!
    expect(box.maxLength).toBe(300)
    expect(document.activeElement).toBe(box)
    expect(host.querySelector(`label[for="${box.id}"]`)?.textContent).toContain('What was wrong?')
    await typeReason(box, 'The count looked off.' + 'x'.repeat(400))
    await act(async () => q('rating-send')!.click())
    await flush()
    const body = JSON.parse(rateFetch.mock.calls[0][1].body as string)
    expect(body.rating).toBe(1)
    expect(body.comment.startsWith('The count looked off.')).toBe(true)
    expect(body.comment.length).toBeLessThanOrEqual(300)
    expect(JSON.stringify(body)).not.toContain(QUESTION)
    expect(q('rating-reason')).toBeNull()
    expect(down.getAttribute('aria-expanded')).toBe('false')
    expect(down.getAttribute('data-chosen')).toBe('true')
    expect(document.activeElement).toBe(down)
  })

  it('an older API (422 on kind / answer_id) shows only "Rating not saved."', async () => {
    rateFetch = vi.fn(async () => ({ ok: false, status: 422, json: async () => ({ error: { code: 'invalid_input', message: 'Invalid input: answer_id, kind.' } }) }))
    await mount('v2')
    await ask(liveBody())
    await act(async () => q('action-up')!.click())
    await flush()
    expect(q('rating-status')?.textContent).toBe('Rating not saved.')
    expect(text()).not.toContain('Invalid input')
    expect(q('action-up')?.getAttribute('aria-pressed')).toBe('false') // not saved: can try again
  })

  it('a second rating refused by the server (409) locks the thumbs', async () => {
    rateFetch = vi.fn(async () => ({ ok: false, status: 409 }))
    await mount('v2')
    await ask(liveBody())
    await act(async () => q('action-up')!.click())
    await flush()
    expect(q('rating-status')?.textContent).toBe('This answer was already rated.')
    expect(q('action-up')?.getAttribute('aria-disabled')).toBe('true')
  })

  it('every action button has a label and a tooltip', async () => {
    await mount('v2')
    await ask(liveBody())
    for (const id of ['action-copy', 'action-read', 'action-up', 'action-down', 'details-toggle']) {
      const b = q(id)!
      expect(b.tagName).toBe('BUTTON')
      expect(b.getAttribute('aria-label')).toBeTruthy()
      expect(b.getAttribute('title')).toBeTruthy()
    }
  })
})

describe('classic layout', () => {
  it('is drawn exactly as before (snapshot taken from the classic code before v2 existed)', async () => {
    await mount()
    await ask(liveBody())
    expect(q('live-answer')?.getAttribute('data-layout')).toBeNull()
    expect(q('mode-badge')?.textContent).toBe('Live answer')
    expect(q('model-chip')).toBeNull()
    expect(host.innerHTML).toMatchSnapshot()
  })

  it('layout="classic" draws the same as no layout', async () => {
    await mount('classic')
    await ask(liveBody())
    const classic = host.innerHTML
    expect(classic).toContain('Cost of this answer')
    expect(q('details-toggle')).toBeNull()
  })
})
