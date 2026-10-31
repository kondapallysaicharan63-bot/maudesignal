// @vitest-environment jsdom
// The live conversation mounted in jsdom with a fake fetch: live, recorded, 429, 422, keyboard, history, voice and speech.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import evidence from '../../public/data/evidence.json'
import threads from '../../public/data/threads.json'
import { Composer } from '../components/Composer'
import { LiveChatView } from '../components/LiveChat'
import type { Evidence, Thread } from '../types'
import { useLiveChat } from './useLiveChat'
import type { Recorder } from './useRecorder'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const T = threads.threads as unknown as Thread[]
const EV = evidence as unknown as Evidence

const idle: Recorder = { state: 'idle', seconds: 0, level: 0, start: async () => undefined, stop: () => undefined, toggle: () => undefined }

const liveBody = (n: number, extra: Record<string, unknown> = {}) => ({
  mode: 'live',
  not_medical_advice: true,
  trace: [
    { step: 'Muse Spark reads the stored records', model: 'muse-spark-1.3', ms: 812, status: 'ok' },
    { step: 'Claim gate checks every sentence', model: null, ms: 6, status: 'ok' },
  ],
  cost_usd: null,
  limits: { remaining_today: 9, resets_utc: '2026-11-01T00:00:00Z' },
  answer: {
    speakable: [
      { text: `Answer number ${n} is about stored reports.`, links: [{ label: 'Report 1', url: 'https://example.org/r1' }] },
      { text: 'A second sentence follows.', links: [] },
    ],
    withheld: [{ reason: 'a number did not match' }],
    spoken_text: `Answer number ${n} is about stored reports. A second sentence follows.`,
  },
  ...extra,
})
const res = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

let host: HTMLDivElement
let root: Root
let fetcher: ReturnType<typeof vi.fn<(u: string, i?: RequestInit) => Promise<Response>>>
const spoken: string[] = []

function Harness() {
  const live = useLiveChat({ apiBase: 'https://api.example', ref: null, threads: T, evidence: EV, fetcher: (u, i) => fetcher(u, i) })
  return (
    <>
      <LiveChatView chat={live} threads={T} onStarter={(q) => void live.ask(q)} onRecordedVoice={() => undefined} />
      <Composer
        threads={T}
        onThread={() => undefined}
        viewKey="live"
        codes={[]}
        onCode={() => undefined}
        onCamera={() => undefined}
        onMic={() => undefined}
        live={{ busy: live.busy, recorder: idle, onAsk: live.ask }}
      />
      <button data-testid="send-voice" onClick={() => void live.askVoice(new Blob([new Uint8Array(44)], { type: 'audio/wav' }))} />
    </>
  )
}

const input = () => host.querySelector('textarea') as HTMLTextAreaElement
async function type(text: string) {
  await act(async () => {
    const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!
    set.call(input(), text)
    input().dispatchEvent(new Event('input', { bubbles: true }))
  })
}
async function key(k: string, shiftKey = false) {
  await act(async () => {
    input().dispatchEvent(new KeyboardEvent('keydown', { key: k, shiftKey, bubbles: true, cancelable: true }))
  })
}
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 30)) })
const text = () => host.textContent ?? ''
const q = (id: string) => host.querySelector(`[data-testid="${id}"]`)

beforeEach(async () => {
  spoken.length = 0
  window.matchMedia = ((query: string) => ({ matches: query.includes('reduce'), addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
  ;(window as unknown as { SpeechSynthesisUtterance: unknown }).SpeechSynthesisUtterance = function (this: { text: string }, t: string) { this.text = t } as unknown
  ;(globalThis as unknown as { SpeechSynthesisUtterance: unknown }).SpeechSynthesisUtterance = (window as unknown as { SpeechSynthesisUtterance: unknown }).SpeechSynthesisUtterance
  ;(window as unknown as { speechSynthesis: unknown }).speechSynthesis = {
    speaking: false,
    cancel: () => undefined,
    speak: (u: { text: string }) => spoken.push(u.text),
  }
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  fetcher = vi.fn()
  await act(async () => root.render(<Harness />))
})
afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
})

describe('a live conversation', () => {
  it('shows the question as a bubble, then the checked answer with links, the held-back line and the advice line', async () => {
    fetcher.mockResolvedValueOnce(res(200, liveBody(1)))
    await type('What changed this week?')
    await key('Enter')
    expect(q('user-bubble')?.textContent).toContain('What changed this week?')
    await flush()
    expect(q('mode-badge')?.textContent).toBe('Live answer')
    expect(text()).toContain('Answer number 1 is about stored reports.')
    expect(text()).toContain('A second sentence follows.')
    expect(q('sentence-links')?.querySelector('a')?.getAttribute('href')).toBe('https://example.org/r1')
    expect(q('held-back')?.textContent).toBe('1 sentence held back: a number did not match')
    expect(q('not-advice')?.textContent).toContain('Not medical advice')
    expect(q('limits')?.textContent).toContain('9 live questions left today')
    // the trace shows each step with its model and its time in ms
    const steps = Array.from(host.querySelectorAll('[data-testid="trace-step"]')).map((s) => s.textContent)
    expect(steps[0]).toContain('Muse Spark')
    expect(steps[0]).toContain('812 ms')
    expect(steps[1]).toContain('Claim gate')
    // the held-back sentence text is never shown
    expect(text()).not.toContain('Withheld by the gate')
  })

  it('shows a typing indicator with the steps while the answer is on its way', async () => {
    let release: (r: Response) => void = () => undefined
    fetcher.mockReturnValueOnce(new Promise<Response>((r) => (release = r)))
    await type('What changed this week?')
    await key('Enter')
    expect(q('typing')?.textContent).toContain('Muse Spark')
    expect(q('typing')?.textContent).toContain('Claim gate')
    await act(async () => release(res(200, liveBody(1))))
    await flush()
    expect(q('typing')).toBeNull()
  })

  it('sends the earlier turns as history, last four at most, answers cut to 600 characters', async () => {
    for (let i = 1; i <= 6; i++) {
      fetcher.mockResolvedValueOnce(res(200, liveBody(i)))
      await type(`Question number ${i}`)
      await key('Enter')
      await flush()
    }
    const bodies = fetcher.mock.calls.map((c) => JSON.parse((c[1] as RequestInit).body as string))
    expect(bodies[0].history).toBeUndefined()
    expect(bodies[1].history).toHaveLength(1)
    expect(bodies[1].history[0].question).toBe('Question number 1')
    expect(bodies[5].history).toHaveLength(4)
    expect(bodies[5].history[0].question).toBe('Question number 2')
    expect(bodies[5].history.every((h: { answer: string }) => h.answer.length <= 600)).toBe(true)
  })

  it('Enter sends, Shift+Enter does not, and focus stays in the input', async () => {
    fetcher.mockResolvedValue(res(200, liveBody(1)))
    await type('What changed this week?')
    input().focus()
    await key('Enter', true)
    expect(fetcher).not.toHaveBeenCalled()
    await key('Enter')
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(document.activeElement).toBe(input())
    expect(input().value).toBe('')
    await flush()
  })

  it('refuses a question that is too short or too long, before sending', async () => {
    await type('x')
    await key('Enter')
    expect(q('ask-error')?.textContent).toMatch(/at least 2/)
    await type('x'.repeat(501))
    await key('Enter')
    expect(q('ask-error')?.textContent).toMatch(/500/)
    expect(fetcher).not.toHaveBeenCalled()
  })
})

describe('recorded, limit and refusal', () => {
  it('a recorded answer from the server carries the badge and the note', async () => {
    fetcher.mockResolvedValueOnce(res(200, liveBody(1, { mode: 'recorded', recorded_note: 'The model was busy; this is the stored run 06-trap.' })))
    await type('What changed this week?')
    await key('Enter')
    await flush()
    expect(q('mode-badge')?.textContent).toBe('Recorded run')
    expect(q('recorded-note')?.textContent).toContain('stored run 06-trap')
    expect(q('not-advice')).not.toBeNull()
  })

  it('429 shows the limit message, switches to recorded runs and stops calling the service', async () => {
    fetcher.mockResolvedValueOnce(res(429, { code: 'rate_limited', message: 'limit', retry_after_s: 60 }))
    const stored = T.find((t) => t.tool_steps.length > 0)!.question
    await type(stored)
    await key('Enter')
    await flush()
    expect(q('limit-banner')?.textContent).toBe('Daily live limit reached - showing recorded runs')
    expect(q('mode-badge')?.textContent).toBe('Recorded run')
    expect(q('recorded-note')?.textContent).toContain('Daily live limit reached')
    expect(q('answer-sentences')?.textContent?.length).toBeGreaterThan(20)
    await type(stored)
    await key('Enter')
    await flush()
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(host.querySelectorAll('[data-testid="live-turn"]')).toHaveLength(2)
  })

  it('a service that cannot be reached falls back to the closest stored run, labelled', async () => {
    fetcher.mockRejectedValueOnce(new TypeError('down'))
    await type(T.find((t) => t.tool_steps.length > 0)!.question)
    await key('Enter')
    await flush()
    expect(q('mode-badge')?.textContent).toBe('Recorded run')
    expect(q('recorded-note')?.textContent).toContain('could not be reached')
  })

  it('422 patient_data shows the server message and no answer', async () => {
    fetcher.mockResolvedValueOnce(res(422, { code: 'patient_data', message: 'That looks like a patient name. Remove it and ask again.' }))
    await type('What happened to the patient John?')
    await key('Enter')
    await flush()
    expect(q('turn-error')?.textContent).toContain('That looks like a patient name. Remove it and ask again.')
    expect(q('live-answer')).toBeNull()
  })
})

describe('a spoken question', () => {
  it('shows Heard before the answer and reads only the spoken text aloud', async () => {
    fetcher.mockResolvedValueOnce(res(200, liveBody(1, { heard: 'What changed this week?' })))
    await act(async () => (host.querySelector('[data-testid="send-voice"]') as HTMLButtonElement).click())
    await flush()
    const bubble = q('user-bubble')?.textContent ?? ''
    expect(bubble).toContain('Heard:')
    expect(bubble).toContain('What changed this week?')
    expect(text().indexOf('Heard:')).toBeLessThan(text().indexOf('Answer number 1'))
    expect(spoken).toEqual(['Answer number 1 is about stored reports. A second sentence follows.'])
    const body = (fetcher.mock.calls[0][1] as RequestInit).body as FormData
    expect(body).toBeInstanceOf(FormData)
    expect((body.get('audio') as File).type).toBe('audio/wav')
  })

  it('does not speak when the speaker is off', async () => {
    fetcher.mockResolvedValueOnce(res(200, liveBody(1, { heard: 'What changed this week?' })))
    await act(async () => (q('speaker-toggle') as HTMLButtonElement).click())
    expect(q('speaker-toggle')?.textContent).toContain('Speaker off')
    await act(async () => (host.querySelector('[data-testid="send-voice"]') as HTMLButtonElement).click())
    await flush()
    expect(spoken).toEqual([])
  })

  it('a voice question that fails offers the recorded voice run', async () => {
    fetcher.mockRejectedValueOnce(new TypeError('down'))
    await act(async () => (host.querySelector('[data-testid="send-voice"]') as HTMLButtonElement).click())
    await flush()
    expect(q('turn-error')?.textContent).toContain('Open the recorded voice run')
  })
})

describe('chat tiers', () => {
  const tierBody = (tier: string, extra: Record<string, unknown> = {}) => ({
    mode: tier === 'cache' ? 'live' : tier,
    tier,
    not_medical_advice: true,
    trace: [{ step: 'Fixed reply, no model call', model: null, ms: 0, status: 'ok' }],
    cost_usd: 0,
    limits: { remaining_today: 30, resets_utc: '2026-11-01T00:00:00Z' },
    answer: { speakable: [{ text: 'Hello!', links: [] }], withheld: [], spoken_text: 'Hello!' },
    ...extra,
  })

  it('a greeting shows its badge, $0 and four chips; a chip asks its question', async () => {
    const chips = ['What changed this week?', 'Check product code LLZ', 'Recalls for QIH', 'Show the AI device sweep']
    fetcher.mockResolvedValueOnce(res(200, tierBody('canned', { badge: 'No FDA facts in this message', suggestions: chips })))
    await type('namaste')
    await key('Enter')
    await flush()
    expect(q('mode-badge')?.textContent).toBe('No FDA facts in this message')
    expect(q('live-answer')?.getAttribute('data-tier')).toBe('canned')
    expect(q('answer-cost')?.textContent).toContain('$0.0000')
    expect(q('answer-cost')?.textContent).toContain('no model call')
    const buttons = Array.from(host.querySelectorAll('[data-testid="suggestion-chip"]')) as HTMLButtonElement[]
    expect(buttons.map((b) => b.textContent)).toEqual(chips)
    expect(q('held-back')).toBeNull()
    fetcher.mockResolvedValueOnce(res(200, liveBody(2)))
    await act(async () => buttons[2].click())
    await flush()
    const sent = JSON.parse((fetcher.mock.calls[1][1] as RequestInit).body as string)
    expect(sent.question).toBe('Recalls for QIH')
  })

  it('a direct lookup shows its badge, its links and the page it points to', async () => {
    const opened: unknown[] = []
    await act(async () => root.unmount())
    root = createRoot(host)
    function WithOpen() {
      const live = useLiveChat({ apiBase: 'https://api.example', ref: null, threads: T, evidence: EV, fetcher: (u, i) => fetcher(u, i) })
      return (
        <>
          <LiveChatView chat={live} threads={T} onStarter={(x) => void live.ask(x)} onRecordedVoice={() => undefined} onOpen={(o) => opened.push(o)} />
          <Composer threads={T} onThread={() => undefined} viewKey="live" codes={[]} onCode={() => undefined} onCamera={() => undefined} onMic={() => undefined} live={{ busy: live.busy, recorder: idle, onAsk: live.ask }} />
        </>
      )
    }
    await act(async () => root.render(<WithOpen />))
    const body = tierBody('direct', {
      badge: 'Direct FDA lookup — no AI',
      answer: {
        speakable: [{ text: 'The stored snapshot holds 2 recalls for product code QIH (one per recalled product).', links: [{ label: 'openFDA recalls', url: 'https://api.fda.gov/device/recall.json?search=product_code%3AQIH&limit=1' }] }],
        withheld: [],
        spoken_text: 'x',
      },
      open: { view: 'check-device', code: 'QIH' },
    })
    fetcher.mockResolvedValueOnce(res(200, body))
    await type('Check QIH')
    await key('Enter')
    await flush()
    expect(q('mode-badge')?.textContent).toBe('Direct FDA lookup — no AI')
    expect(q('sentence-links')?.querySelector('a')?.getAttribute('href')).toContain('api.fda.gov')
    const open = q('open-view') as HTMLButtonElement
    expect(open.textContent).toBe('Open Check any device type for QIH')
    await act(async () => open.click())
    expect(opened).toEqual([{ view: 'check-device', code: 'QIH' }])
  })

  it('a reused answer says when it was first answered', async () => {
    fetcher.mockResolvedValueOnce(res(200, tierBody('cache', { badge: 'Answered earlier today', answered_at: '2026-10-31T09:05:00Z' })))
    await type('Why did LLZ increase?')
    await key('Enter')
    await flush()
    expect(q('mode-badge')?.textContent).toBe('Answered earlier today')
    expect(q('answered-at')?.textContent).toBe('First answered 09:05 UTC')
  })

  it('a live answer from an older server (no tier) keeps the live badge and no chips', async () => {
    fetcher.mockResolvedValueOnce(res(200, liveBody(1)))
    await type('Why did LLZ increase?')
    await key('Enter')
    await flush()
    expect(q('mode-badge')?.textContent).toBe('Live answer')
    expect(q('suggestions')).toBeNull()
  })
})
