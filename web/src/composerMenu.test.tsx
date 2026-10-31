// @vitest-environment jsdom
// The message box with the + menu (Track A): the on/off switch, the menu's keyboard behaviour, photo attach and remove,
// the camera fallback, voice (cancel sends nothing, pause and resume, stop -> words in the box -> edit -> one ask), the
// web-research toggle (hidden unless the API offers it) and the web-research section with "Save to audit".
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import evidence from '../public/data/evidence.json'
import threads from '../public/data/threads.json'
import { CameraSheet, cameraDenied, cameraFallbackText, openCamera } from './components/CameraSheet'
import { LiveChatView } from './components/LiveChat'
import { MessageBox } from './components/MessageBox'
import { menuMove } from './components/PlusMenu'
import { ResearchSection } from './components/ResearchSection'
import { voiceAnnouncement, waveHeights } from './components/VoiceBar'
import { composerMenuOn } from './composerFlag'
import {
  buildAskBody,
  LiveError,
  parseAsk,
  parseResearch,
  parseTranscribe,
  postResearchSave,
  RESEARCH_LABEL,
  transcribeErrorText,
  VOICE_PATH,
} from './live/api'
import { applyCodeSuggestion, editDistance, heardCodeFor } from './live/codeSuggest'
import { fetchFeatures, NO_FEATURES, parseFeatures, type ApiFeatures } from './live/features'
import { useLiveChat } from './live/useLiveChat'
import { elapsedSeconds, pushLevel, WAVE_BARS } from './live/useRecorder'
import type { Evidence, Thread } from './types'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const T = threads.threads as unknown as Thread[]
const EV = evidence as unknown as Evidence
const res = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

// --- pure parts -----------------------------------------------------------------------------------------------------

describe('the on/off switch', () => {
  it('is on by default and when the flag says so; off for 0/false/off/no', () => {
    expect(composerMenuOn(undefined, '')).toBe(true)
    expect(composerMenuOn('', '')).toBe(true)
    expect(composerMenuOn('1', '')).toBe(true)
    for (const off of ['0', 'false', 'OFF', ' no ']) expect(composerMenuOn(off, '')).toBe(false)
  })
  it('?composer=classic forces the earlier composer at run time', () => {
    expect(composerMenuOn('1', '?composer=classic')).toBe(false)
    expect(composerMenuOn(undefined, '?r=TEST-0&composer=Classic')).toBe(false)
    expect(composerMenuOn(undefined, '?composer=menu')).toBe(true)
  })
})

describe('API features from GET /v1/health', () => {
  it('counts only an explicit true', () => {
    expect(parseFeatures({ features: { research: true, voice_transcribe_only: true } })).toEqual({ research: true, transcribeOnly: true })
    expect(parseFeatures({ features: { research: 'yes' } })).toEqual(NO_FEATURES)
    expect(parseFeatures({ status: 'ok' })).toEqual(NO_FEATURES)
    expect(parseFeatures(null)).toEqual(NO_FEATURES)
  })
  it('any failure means no optional feature', async () => {
    const ok = vi.fn(async (_u: string, _i?: RequestInit) => res(200, { features: { research: true } }))
    expect(await fetchFeatures('https://api.example', ok)).toEqual({ research: true, transcribeOnly: false })
    expect(ok.mock.calls[0][0]).toBe('https://api.example/v1/health')
    expect(await fetchFeatures('https://api.example', async () => res(500, {}))).toEqual(NO_FEATURES)
    expect(await fetchFeatures('https://api.example', async () => Promise.reject(new Error('offline')))).toEqual(NO_FEATURES)
    expect(await fetchFeatures(null, ok)).toEqual(NO_FEATURES)
  })
})

describe('request and response shapes', () => {
  it('research: true is sent only when the toggle is on', () => {
    expect(buildAskBody('What changed for LLZ?', { research: true }).research).toBe(true)
    expect('research' in buildAskBody('What changed for LLZ?', { research: false })).toBe(false)
    expect('research' in buildAskBody('What changed for LLZ?')).toBe(false)
  })
  it('reads the web-research block, keeping only titled http(s) links', () => {
    const r = parseResearch({
      status: 'ok',
      label: 'x',
      items: [
        { title: 'A recall notice', url: 'https://example.org/a', date: '2026-10-01', source: 'example.org' },
        { title: 'No link', url: 'javascript:alert(1)' },
        { title: '', url: 'https://example.org/b' },
      ],
    })
    expect(r?.items).toEqual([{ title: 'A recall notice', url: 'https://example.org/a', date: '2026-10-01', source: 'example.org' }])
    expect(parseResearch(undefined)).toBeNull()
    const ask = parseAsk({ answer: { speakable: [], withheld: [] }, research: { status: 'ok', items: [] } })
    expect(ask?.research?.status).toBe('ok')
  })
  it('reads a transcribe-only answer: the words, the codes offered and the voice questions left', () => {
    const t = parseTranscribe({ heard: ' What changed for LLC? ', did_you_mean: ['LLZ', 'bad'], limits: { remaining_today: 7, resets_utc: 'z' }, cost_usd: 0.0002 })
    expect(t).toEqual({ heard: 'What changed for LLC?', did_you_mean: ['LLZ'], limits: { remaining_today: 7, resets_utc: 'z' }, cost_usd: 0.0002 })
    expect(parseTranscribe({ heard: '  ' })).toBeNull()
  })
  it('says why a transcription failed, using the server text where it has one', () => {
    expect(transcribeErrorText(new LiveError('rate_limited', 'Daily limit of 10 voice requests reached.'))).toContain('Daily limit of 10 voice')
    expect(transcribeErrorText(new LiveError('server', 'HTTP 503', undefined, 'No live model key. Type your question instead.'))).toContain('Type your question')
    expect(transcribeErrorText(new LiveError('network', 'The live service could not be reached.'))).toContain('Nothing was sent')
  })
  it('save to audit: 404 means the route is not there yet', async () => {
    const item = { title: 't', url: 'https://example.org/a', date: '2026-10-01', source: null }
    const f404 = vi.fn(async () => res(404, {}))
    expect(await postResearchSave(item, { apiBase: 'https://api.example', fetcher: f404 })).toBe('unsupported')
    const ok = vi.fn(async (_u: string, _i?: RequestInit) => res(201, {}))
    expect(await postResearchSave(item, { apiBase: 'https://api.example', fetcher: ok })).toBe('saved')
    expect(ok.mock.calls[0][0]).toBe('https://api.example/v1/live/research/save')
    expect(JSON.parse(ok.mock.calls[0][1]?.body as string)).toEqual({ url: 'https://example.org/a', title: 't', date: '2026-10-01' })
    expect(await postResearchSave(item, { apiBase: 'https://api.example', fetcher: async () => res(500, {}) })).toBe('failed')
  })
})

describe('"did you mean" after a spoken question', () => {
  it('swaps only the heard word, and only on request', () => {
    expect(editDistance('LLC', 'LLZ')).toBe(1)
    expect(heardCodeFor('What changed for LLC?', 'LLZ')).toBe('LLC')
    expect(heardCodeFor('What changed for LLZ?', 'LLZ')).toBeNull()
    expect(applyCodeSuggestion('What changed for LLC this week?', 'LLZ')).toBe('What changed for LLZ this week?')
    expect(applyCodeSuggestion('nothing to change', 'LLZ')).toBe('nothing to change')
  })
})

describe('menu keys, waveform and timer helpers', () => {
  it('arrow keys wrap; Home and End jump', () => {
    expect(menuMove('ArrowDown', 4, 5)).toBe(0)
    expect(menuMove('ArrowUp', 0, 5)).toBe(4)
    expect(menuMove('Home', 3, 5)).toBe(0)
    expect(menuMove('End', 0, 5)).toBe(4)
    expect(menuMove('x', 0, 5)).toBeNull()
  })
  it('keeps the last levels only and does not count paused time', () => {
    let l: number[] = []
    for (let i = 0; i < WAVE_BARS + 5; i++) l = pushLevel(l, i === WAVE_BARS + 4 ? 2 : 0.1)
    expect(l).toHaveLength(WAVE_BARS)
    expect(l[l.length - 1]).toBe(1)
    expect(elapsedSeconds(4000, null, 99999)).toBe(4)
    expect(elapsedSeconds(4000, 10000, 12500)).toBe(6.5)
  })
  it('the waveform has 24 bars from the newest levels; flat while paused', () => {
    const h = waveHeights([0, 0.04, 0.25, 1], true)
    expect(h).toHaveLength(24)
    expect(h.slice(-3).map((v) => Math.round(v * 100) / 100)).toEqual([0.32, 0.8, 1])
    expect(h[0]).toBe(0)
    expect(waveHeights([0.5, 0.5], false).every((v) => v === 0)).toBe(true)
  })
  it('announces the state, and the time only every 15 seconds', () => {
    expect(voiceAnnouncement('recording', 0)).toContain('Recording')
    expect(voiceAnnouncement('recording', 15)).toBe('Recording, 0:15.')
    expect(voiceAnnouncement('paused', 7)).toBe('Paused at 0:07.')
    expect(voiceAnnouncement('transcribing', 7)).toContain('nothing is sent until you press Send')
  })
  it('names why the camera falls back to the file picker', () => {
    expect(cameraFallbackText({ name: 'NotAllowedError' })).toBe('Camera blocked — choose a photo instead')
    expect(cameraFallbackText({ name: 'NotFoundError' })).toBe('No camera found — choose a photo instead')
    expect(cameraFallbackText({ name: 'insecure' })).toContain('secure')
  })
  it('reads a refusal from the Permissions API; anything else asks as usual', async () => {
    const perms = (state: string) => ({ query: async () => ({ state }) }) as unknown as Permissions
    expect(await cameraDenied(perms('denied'))).toBe(true)
    expect(await cameraDenied(perms('prompt'))).toBe(false)
    expect(await cameraDenied(perms('granted'))).toBe(false)
    expect(await cameraDenied({ query: async () => Promise.reject(new TypeError('camera')) } as unknown as Permissions)).toBe(false)
    expect(await cameraDenied(undefined)).toBe(false)
  })
  it('asks for the back camera first and any camera when that is impossible', async () => {
    await expect(openCamera(undefined, false)).rejects.toMatchObject({ name: 'insecure' })
    await expect(openCamera({} as MediaDevices, true)).rejects.toMatchObject({ name: 'unsupported' })
    const stream = {} as MediaStream
    const gum = vi.fn().mockRejectedValueOnce(Object.assign(new Error('x'), { name: 'OverconstrainedError' })).mockResolvedValueOnce(stream)
    expect(await openCamera({ getUserMedia: gum } as unknown as MediaDevices, true)).toBe(stream)
    expect(gum.mock.calls[0][0]).toEqual({ video: { facingMode: { ideal: 'environment' } }, audio: false })
    expect(gum.mock.calls[1][0]).toEqual({ video: true, audio: false })
  })
})

// --- the message box in a page ----------------------------------------------------------------------------------------

class FakeMediaRecorder {
  static last: FakeMediaRecorder | null = null
  state: 'inactive' | 'recording' | 'paused' = 'inactive'
  mimeType = 'audio/webm'
  ondataavailable: ((e: { data: Blob }) => void) | null = null
  onstop: (() => void) | null = null
  constructor() {
    FakeMediaRecorder.last = this
  }
  start() {
    this.state = 'recording'
  }
  pause() {
    this.state = 'paused'
  }
  resume() {
    this.state = 'recording'
  }
  stop() {
    this.state = 'inactive'
    this.ondataavailable?.({ data: new Blob([new Uint8Array(64)]) })
    this.onstop?.()
  }
}
class FakeAudioContext {
  createAnalyser() {
    return { fftSize: 512, getByteTimeDomainData: (b: Uint8Array) => b.fill(150) }
  }
  createMediaStreamSource() {
    return { connect: () => undefined }
  }
  decodeAudioData() {
    return Promise.resolve({ numberOfChannels: 1, sampleRate: 16000, getChannelData: () => new Float32Array(16000) })
  }
  close() {
    return Promise.resolve()
  }
}

let host: HTMLDivElement
let root: Root
let fetcher: ReturnType<typeof vi.fn<(u: string, i?: RequestInit) => Promise<Response>>>
let clicks: string[]
let features: ApiFeatures
let phone = false

function Harness() {
  const live = useLiveChat({ apiBase: 'https://api.example', ref: null, threads: T, evidence: EV, fetcher: (u, i) => fetcher(u, i) })
  return (
    <>
      <LiveChatView chat={live} threads={T} onStarter={(q) => void live.ask(q)} onRecordedVoice={() => undefined} />
      <MessageBox
        threads={T}
        onThread={() => undefined}
        viewKey="live"
        codes={[]}
        onCode={() => undefined}
        onCamera={() => clicks.push('recorded-camera')}
        onMic={() => clicks.push('recorded-mic')}
        onSample={() => clicks.push('sample')}
        phone={phone}
        live={{
          busy: live.busy,
          features,
          onAsk: (q, o) => live.ask(q, { research: o.research }),
          onPhoto: (b, f) => live.askPhoto(b, f),
          transcribe: live.transcribe,
        }}
      />
    </>
  )
}

const q = (id: string) => document.querySelector(`[data-testid="${id}"]`) as HTMLElement | null
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 30)) })
const click = (el: Element | null) => act(async () => { (el as HTMLElement).click() })
const keyOn = (el: Element | null, key: string) =>
  act(async () => { (el as HTMLElement).dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true })) })
const box = () => host.querySelector('textarea') as HTMLTextAreaElement
async function typeInto(text: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(box(), text)
    box().dispatchEvent(new Event('input', { bubbles: true }))
  })
}
async function menuItem(id: string) {
  await click(q('composer-plus'))
  await click(q(`menu-${id}`))
}
const calls = (path: string) => fetcher.mock.calls.filter((c) => String(c[0]).endsWith(path))

async function mount() {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => root.render(<Harness />))
}

beforeEach(async () => {
  clicks = []
  phone = false
  features = { research: false, transcribeOnly: true }
  fetcher = vi.fn()
  window.matchMedia = ((query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
  const g = globalThis as unknown as Record<string, unknown>
  g.MediaRecorder = FakeMediaRecorder
  ;(window as unknown as Record<string, unknown>).AudioContext = FakeAudioContext
  g.requestAnimationFrame = (cb: (t: number) => void) => setTimeout(() => cb(Date.now()), 16) as unknown as number
  g.cancelAnimationFrame = (id: number) => clearTimeout(id)
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop: () => undefined }] })) },
  })
  URL.createObjectURL = vi.fn(() => 'blob:thumb')
  URL.revokeObjectURL = vi.fn()
  g.createImageBitmap = vi.fn(async () => ({ width: 120, height: 80, close: () => undefined }))
  HTMLCanvasElement.prototype.getContext = (() => ({ drawImage: () => undefined })) as unknown as HTMLCanvasElement['getContext']
  HTMLCanvasElement.prototype.toBlob = function (cb: BlobCallback) {
    cb(new Blob([new Uint8Array([255, 216, 255, 1])], { type: 'image/jpeg' }))
  }
  HTMLMediaElement.prototype.play = vi.fn(async () => undefined)
  // jsdom's Blob has no arrayBuffer(); the fake AudioContext decodes nothing real anyway
  if (!Blob.prototype.arrayBuffer) Blob.prototype.arrayBuffer = async () => new ArrayBuffer(8)
  await mount()
})
afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
  vi.restoreAllMocks()
})

describe('the + menu', () => {
  it('is one menu button; it opens a menu of items, arrow keys move, Escape closes and returns focus', async () => {
    const plus = q('composer-plus') as HTMLButtonElement
    expect(plus.getAttribute('aria-haspopup')).toBe('menu')
    expect(plus.getAttribute('aria-expanded')).toBe('false')
    expect(plus.getAttribute('aria-label')).toBe('More: photo, sample label, web research, voice')
    expect(q('composer-send')?.getAttribute('aria-label')).toBe('Send')
    expect((q('composer-send') as HTMLButtonElement).disabled).toBe(true) // empty box
    // the scattered camera / mic buttons of the earlier composer are gone
    expect(q('composer-camera')).toBeNull()
    expect(q('composer-mic')).toBeNull()
    plus.focus()
    await keyOn(plus, 'ArrowDown')
    const menu = host.querySelector('[role="menu"]') as HTMLElement
    expect(menu).not.toBeNull()
    expect(plus.getAttribute('aria-expanded')).toBe('true')
    const labels = Array.from(menu.querySelectorAll('[role^="menuitem"]')).map((b) => b.textContent)
    expect(labels.map((l) => ['Take photo', 'Upload photo', 'Try a sample label', 'Ask by voice'].find((w) => l?.startsWith(w)))).toEqual([
      'Take photo',
      'Upload photo',
      'Try a sample label',
      'Ask by voice',
    ])
    expect(document.activeElement?.textContent).toContain('Take photo')
    await keyOn(document.activeElement, 'ArrowDown')
    expect(document.activeElement?.textContent).toContain('Upload photo')
    await keyOn(document.activeElement, 'ArrowUp')
    await keyOn(document.activeElement, 'ArrowUp')
    expect(document.activeElement?.textContent).toContain('Ask by voice')
    await keyOn(document.activeElement, 'Home')
    expect(document.activeElement?.textContent).toContain('Take photo')
    await keyOn(document.activeElement, 'Escape')
    expect(host.querySelector('[role="menu"]')).toBeNull()
    expect(document.activeElement).toBe(plus)
    // Arrow Up opens on the last item
    await keyOn(plus, 'ArrowUp')
    expect(document.activeElement?.textContent).toContain('Ask by voice')
  })

  it('"Try a sample label" opens the stored samples; there are no examples on the photo path', async () => {
    await menuItem('sample-label')
    expect(clicks).toEqual(['sample'])
    expect(host.querySelector('[role="menu"]')).toBeNull()
  })

  it('"Research the web" is hidden when the API does not offer it', async () => {
    await click(q('composer-plus'))
    expect(q('menu-research')).toBeNull()
  })

  it('"Research the web" is an on/off item when offered; on, the ask carries research: true', async () => {
    await act(async () => root.unmount())
    host.remove()
    features = { research: true, transcribeOnly: true }
    await mount()
    await click(q('composer-plus'))
    const item = q('menu-research') as HTMLElement
    expect(item.getAttribute('role')).toBe('menuitemcheckbox')
    expect(item.getAttribute('aria-checked')).toBe('false')
    expect(q('menu-research-state')?.textContent).toBe('Off')
    await click(item)
    expect(q('research-pill')?.textContent).toContain('Web research on')
    await click(q('composer-plus'))
    expect(q('menu-research')?.getAttribute('aria-checked')).toBe('true')
    expect(q('menu-research-state')?.textContent).toBe('On')
    await keyOn(host.querySelector('[role="menu"]'), 'Escape')
    fetcher.mockResolvedValueOnce(res(200, { answer: { speakable: [], withheld: [] } }))
    await typeInto('Any news about LLZ?')
    await keyOn(box(), 'Enter')
    const sent = JSON.parse(calls('/v1/live/ask')[0][1]?.body as string)
    expect(sent).toMatchObject({ question: 'Any news about LLZ?', research: true })
  })
})

describe('photos', () => {
  const upload = async () => {
    const input = q('photo-input') as HTMLInputElement
    const file = new File([new Uint8Array([255, 216, 255, 0])], 'label.jpg', { type: 'image/jpeg' })
    Object.defineProperty(input, 'files', { configurable: true, value: [file] })
    await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })))
    await flush()
  }

  it('an attached photo shows as a thumbnail with ✕; ✕ removes it and nothing is sent', async () => {
    const pick = vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => undefined)
    await menuItem('upload-photo')
    expect(pick).toHaveBeenCalled()
    await upload()
    expect(q('photo-thumb')?.querySelector('img')?.getAttribute('src')).toBe('blob:thumb')
    expect(q('composer-send')?.getAttribute('aria-label')).toBe('Send photo')
    const remove = q('photo-remove') as HTMLButtonElement
    expect(remove.getAttribute('aria-label')).toBe('Remove the attached photo')
    await click(remove)
    expect(q('photo-thumb')).toBeNull()
    expect(fetcher).not.toHaveBeenCalled()
  })

  it('Send sends the photo; the words typed with it are asked after the reading, with its product code', async () => {
    vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => undefined)
    await upload()
    let release: (r: Response) => void = () => undefined
    const cand = { k_number: 'K990001', device_name: 'Sample viewer', applicant: 'Sample Co', product_code: 'QIH', why_matched: ['name'], why_not_matched: [], links: [] }
    fetcher.mockImplementation((u: string) =>
      u.endsWith('/v1/live/label')
        ? new Promise<Response>((r) => (release = r))
        : Promise.resolve(res(200, { answer: { speakable: [], withheld: [] } })),
    )
    await typeInto('Is this one recalled?')
    await click(q('composer-send'))
    await flush()
    expect(calls('/v1/live/label')).toHaveLength(1)
    expect(calls('/v1/live/label')[0][1]?.body).toBeInstanceOf(FormData)
    expect(calls('/v1/live/ask')).toHaveLength(0) // two steps: the question waits for the reading
    expect(q('photo-followup-note')?.textContent).toBe('Your question is sent after the photo reading.')
    expect(q('photo-thumb')).toBeNull()
    await act(async () => release(res(200, { mode: 'live', reading: { legibility: 'clear', fields: {} }, matches: { status: 'needs_person_to_confirm', candidates: [cand] }, trace: [] })))
    await flush()
    const sent = JSON.parse(calls('/v1/live/ask')[0][1]?.body as string)
    expect(sent).toMatchObject({ question: 'Is this one recalled?', product_code: 'QIH' })
    expect(host.querySelector('[data-via="photo"] img')?.getAttribute('alt')).toBe('Your photo of a device label')
    expect(q('match-card')).not.toBeNull()
    expect(q('confirmed-block')).toBeNull() // nothing is confirmed for the person
  })

  it('without a match code the words are asked as typed', async () => {
    vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => undefined)
    await upload()
    fetcher.mockImplementation(async (u: string) =>
      u.endsWith('/v1/live/label')
        ? res(200, { mode: 'recorded', reading: { legibility: 'clear', fields: {} }, matches: { status: 'no_match_found', candidates: [] }, trace: [] })
        : res(200, { answer: { speakable: [], withheld: [] } }),
    )
    await typeInto('Is this one recalled?')
    await click(q('composer-send'))
    await flush()
    const sent = JSON.parse(calls('/v1/live/ask')[0][1]?.body as string)
    expect(sent.question).toBe('Is this one recalled?')
    expect('product_code' in sent).toBe(false)
    expect(q('no-match')).not.toBeNull()
  })

  it('Take photo on a computer opens the live camera at once: Shutter, Retake, Use photo', async () => {
    await menuItem('take-photo')
    await flush()
    expect(q('camera-sheet')).not.toBeNull()
    expect(document.querySelector('[role="dialog"]')?.getAttribute('aria-modal')).toBe('true')
    expect(q('camera-sheet')?.parentElement).toBe(document.body) // a portal: the scrim covers the sidebar too
    const video = q('camera-live') as HTMLVideoElement
    Object.defineProperty(video, 'videoWidth', { value: 640 })
    Object.defineProperty(video, 'videoHeight', { value: 480 })
    await click(q('camera-shutter'))
    await flush()
    expect(q('camera-shot')).not.toBeNull()
    await click(q('camera-retake'))
    expect(q('camera-shot')).toBeNull()
    await click(q('camera-shutter'))
    await flush()
    await click(q('camera-use'))
    await flush()
    expect(q('camera-sheet')).toBeNull()
    expect(q('photo-thumb')).not.toBeNull()
  })

  it('camera refused: the file picker opens with a short reason', async () => {
    ;(navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>).mockRejectedValueOnce(Object.assign(new Error('no'), { name: 'NotAllowedError' }))
    const pick = vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => undefined)
    await menuItem('take-photo')
    await flush()
    expect(q('camera-sheet')).toBeNull()
    expect(q('photo-note')?.textContent).toContain('Camera blocked — choose a photo instead')
    expect(pick).toHaveBeenCalledTimes(1)
    expect((pick.mock.contexts[0] as HTMLInputElement).dataset.testid).toBe('photo-input')
    await click(q('photo-note-pick'))
    expect(pick).toHaveBeenCalledTimes(2)
  })

  it('Take photo on a phone goes straight to the phone camera (capture="environment")', async () => {
    await act(async () => root.unmount())
    host.remove()
    phone = true
    await mount()
    const pick = vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => undefined)
    await menuItem('take-photo')
    expect(q('camera-sheet')).toBeNull()
    const input = pick.mock.contexts[0] as HTMLInputElement
    expect(input.dataset.testid).toBe('phone-camera-input')
    expect(input.getAttribute('capture')).toBe('environment')
    expect(input.getAttribute('accept')).toBe('image/*')
  })
})

describe('voice', () => {
  const startVoice = async () => {
    await menuItem('voice')
    await flush()
    expect(q('voice-bar')).not.toBeNull()
    expect(host.querySelector('form[data-testid="message-box"]')).toBeNull()
  }

  it('Cancel discards the recording: no voice request, no transcription, the box comes back', async () => {
    await startVoice()
    expect(q('voice-live')?.getAttribute('aria-live')).toBe('polite')
    expect(q('voice-cancel')?.getAttribute('aria-label')).toContain('Cancel')
    await click(q('voice-cancel'))
    await flush()
    expect(q('voice-bar')).toBeNull()
    expect(box()).not.toBeNull()
    expect(fetcher).not.toHaveBeenCalled()
    expect(calls(VOICE_PATH)).toHaveLength(0)
  })

  it('Pause and Resume use the recorder’s own pause', async () => {
    await startVoice()
    await click(q('voice-pause'))
    expect(FakeMediaRecorder.last?.state).toBe('paused')
    expect(q('voice-bar')?.dataset.state).toBe('paused')
    expect(q('voice-pause')?.getAttribute('aria-label')).toBe('Resume recording')
    expect(q('voice-live')?.textContent).toContain('Paused')
    await click(q('voice-pause'))
    expect(FakeMediaRecorder.last?.state).toBe('recording')
    expect(q('voice-bar')?.dataset.state).toBe('recording')
  })

  it('Stop puts the words in the box; nothing is asked until Send; the edited words are sent once', async () => {
    fetcher.mockResolvedValueOnce(res(200, { heard: 'What changed this week for LLC?', did_you_mean: ['LLZ'], limits: { remaining_today: 7, resets_utc: 'z' } }))
    await startVoice()
    await click(q('voice-stop'))
    await flush()
    await flush()
    expect(calls(VOICE_PATH)).toHaveLength(1)
    const form = calls(VOICE_PATH)[0][1]?.body as FormData
    const meta = await new Promise<string>((r) => { const fr = new FileReader(); fr.onload = () => r(String(fr.result)); fr.readAsText(form.get('meta') as Blob) })
    expect(JSON.parse(meta)).toEqual({ transcribe_only: true })
    expect(q('voice-bar')).toBeNull()
    expect(box().value).toBe('What changed this week for LLC?')
    expect(document.activeElement).toBe(box())
    expect(host.querySelector('[role="listbox"]')).toBeNull() // focus moved by the page does not open the type-ahead
    expect(calls('/v1/live/ask')).toHaveLength(0)
    // the voice questions left are in the "Ask by voice" item, not loose under the box
    await click(q('composer-plus'))
    expect(q('menu-voice')?.textContent).toContain('7 voice questions left today')
    await keyOn(host.querySelector('[role="menu"]'), 'Escape')
    // "Did you mean LLZ? Use LLZ" is one chip inside the box; it swaps the heard code only when clicked
    expect(q('message-box')?.contains(q('did-you-mean'))).toBe(true)
    expect(q('did-you-mean')?.textContent).toContain('Did you mean LLZ?')
    expect(q('did-you-mean')?.textContent).toContain('LLC')
    await click(q('did-you-mean-code'))
    expect(box().value).toBe('What changed this week for LLZ?')
    await typeInto('What changed this week for LLZ in 2026?')
    fetcher.mockResolvedValueOnce(res(200, { answer: { speakable: [], withheld: [] } }))
    await keyOn(box(), 'Enter')
    await flush()
    expect(calls('/v1/live/ask')).toHaveLength(1)
    expect(JSON.parse(calls('/v1/live/ask')[0][1]?.body as string).question).toBe('What changed this week for LLZ in 2026?')
    expect(calls(VOICE_PATH)).toHaveLength(1)
  })

  it('the voice limit message from the API is shown and nothing else is sent', async () => {
    fetcher.mockResolvedValueOnce(res(429, { code: 'rate_limited', message: 'Daily limit of 10 voice requests reached. Resets at 2026-11-01T00:00:00Z.' }))
    await startVoice()
    await click(q('voice-stop'))
    await flush()
    expect(q('voice-problem')?.textContent).toContain('Daily limit of 10 voice requests reached')
    expect(box().value).toBe('')
    expect(calls('/v1/live/ask')).toHaveLength(0)
  })

  it('without transcribe-only confirmed by the API, voice opens the recorded run and never records or sends', async () => {
    await act(async () => root.unmount())
    host.remove()
    features = { research: false, transcribeOnly: false }
    await mount()
    await click(q('composer-plus'))
    expect(q('menu-voice')?.textContent).toContain('Voice needs the live service')
    await click(q('menu-voice'))
    expect(clicks).toEqual(['recorded-mic'])
    expect(q('voice-bar')).toBeNull()
    expect(fetcher).not.toHaveBeenCalled()
  })

  it('at 1:00 the recording pauses (not sent) until Stop; "Stops at 1:00" shows from 0:45', async () => {
    const t0 = Date.now()
    const now = vi.spyOn(Date, 'now').mockReturnValue(t0)
    await startVoice()
    now.mockReturnValue(t0 + 46_000)
    await act(async () => { await new Promise((r) => setTimeout(r, 260)) })
    expect(q('voice-limit')?.textContent).toBe('Stops at 1:00')
    now.mockReturnValue(t0 + 61_000)
    await act(async () => { await new Promise((r) => setTimeout(r, 260)) })
    expect(FakeMediaRecorder.last?.state).toBe('paused')
    expect(q('voice-bar')?.dataset.limit).toBe('true')
    expect(q('voice-timer')?.textContent).toBe('1:00')
    expect(q('voice-limit')?.textContent).toBe('Limit reached — press Stop to use it or ✕ to discard')
    expect((q('voice-pause') as HTMLButtonElement).disabled).toBe(true)
    expect(fetcher).not.toHaveBeenCalled() // no voice question is used yet
    fetcher.mockResolvedValueOnce(res(200, { heard: 'What changed this week for LLZ?', did_you_mean: [] }))
    await click(q('voice-stop'))
    await flush()
    expect(calls(VOICE_PATH)).toHaveLength(1)
    expect(box().value).toBe('What changed this week for LLZ?')
  })
})

describe('web research under an answer', () => {
  const block = { status: 'ok', label: 'from server', items: [{ title: 'A recall notice', url: 'https://example.org/a', date: '2026-10-01', source: 'example.org' }] }

  it('is labelled exactly; links open in a new tab safely; Save to audit says Saved', async () => {
    const onSave = vi.fn(async () => 'saved' as const)
    await act(async () => root.render(<ResearchSection block={block} onSave={onSave} />))
    expect(q('research-label')?.textContent).toBe(RESEARCH_LABEL)
    expect(RESEARCH_LABEL).toBe('Web research — not FDA records, not verified by the gate')
    const a = host.querySelector('[data-testid="research-item"] a') as HTMLAnchorElement
    expect(a.getAttribute('rel')).toBe('noopener noreferrer')
    expect(a.getAttribute('target')).toBe('_blank')
    expect(q('research-date')?.textContent).toBe('2026-10-01')
    expect(q('research-source')?.textContent).toBe('example.org')
    await click(q('research-save'))
    await flush()
    expect(onSave).toHaveBeenCalledWith(block.items[0])
    expect(q('research-saved')?.textContent).toBe('Saved')
  })

  it('hides Save to audit when the server has no save route (404)', async () => {
    await act(async () => root.render(<ResearchSection block={block} onSave={async () => 'unsupported'} />))
    await click(q('research-save'))
    await flush()
    expect(q('research-save')).toBeNull()
    expect(q('research-saved')).toBeNull()
  })
})

describe('the camera dialog on its own', () => {
  it('Escape closes it', async () => {
    const onClose = vi.fn()
    await act(async () => root.render(<CameraSheet onUse={() => undefined} onClose={onClose} onFail={() => undefined} onPickFile={() => undefined} />))
    await flush()
    await keyOn(document.querySelector('[role="dialog"]'), 'Escape')
    expect(onClose).toHaveBeenCalled()
  })
})

describe('the camera dialog never closes on time alone', () => {
  const stream = () => {
    const stop = vi.fn()
    return { stop, s: { getTracks: () => [{ stop }] } as unknown as MediaStream }
  }
  const sheet = (h: { onFail?: (r: string) => void; onPickFile?: () => void; onClose?: () => void } = {}) =>
    act(async () =>
      root.render(
        <CameraSheet onUse={() => undefined} onClose={h.onClose ?? (() => undefined)} onFail={h.onFail ?? (() => undefined)} onPickFile={h.onPickFile ?? (() => undefined)} slowAfterMs={40} />,
      ),
    )

  it('a slow start (an open "Allow camera?" prompt) keeps the dialog open, offers a photo, and still shows a late stream', async () => {
    let allow: (s: MediaStream) => void = () => undefined
    ;(navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>).mockReturnValueOnce(new Promise<MediaStream>((r) => (allow = r)))
    const onFail = vi.fn()
    await sheet({ onFail })
    await flush()
    await flush()
    expect(q('camera-sheet')).not.toBeNull()
    expect(q('camera-slow')?.textContent).toBe('Camera not started yet')
    expect(q('camera-use-file')?.textContent).toContain('Use a photo instead')
    expect(onFail).not.toHaveBeenCalled()
    const { stop, s } = stream()
    await act(async () => allow(s))
    await flush()
    expect(q('camera-waiting')).toBeNull()
    expect((q('camera-shutter') as HTMLButtonElement).disabled).toBe(false)
    expect(stop).not.toHaveBeenCalled()
  })

  it('"Use a photo instead" opens the file picker; a stream that arrives afterwards is switched off', async () => {
    let allow: (s: MediaStream) => void = () => undefined
    ;(navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>).mockReturnValueOnce(new Promise<MediaStream>((r) => (allow = r)))
    const onPickFile = vi.fn(() => void act(async () => root.render(<div />)))
    await sheet({ onPickFile })
    await flush()
    await flush()
    await click(q('camera-use-file'))
    await flush()
    expect(onPickFile).toHaveBeenCalled()
    const { stop, s } = stream()
    await act(async () => allow(s))
    await flush()
    expect(stop).toHaveBeenCalled()
  })

  it('a refusal the browser already knows (Permissions API "denied") falls back at once, without asking', async () => {
    Object.defineProperty(navigator, 'permissions', { configurable: true, value: { query: async () => ({ state: 'denied' }) } })
    const onFail = vi.fn()
    try {
      await sheet({ onFail })
      await flush()
      expect(onFail).toHaveBeenCalledWith('Camera blocked — choose a photo instead')
      expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled()
    } finally {
      Object.defineProperty(navigator, 'permissions', { configurable: true, value: undefined })
    }
  })
})

describe('polish: alert bubble and menu rows', () => {
  it('the first-visit bubble is marked auto (hidden on pages with the message box); hover shows a user one', async () => {
    const { AlertBuddy } = await import('./components/AlertBuddy')
    sessionStorage.clear()
    await act(async () => root.render(<AlertBuddy items={[]} count={3} onOpen={() => undefined} />))
    expect(q('buddy-bubble')?.dataset.auto).toBe('true')
    const wrap = q('alert-buddy')?.parentElement as HTMLElement
    await act(async () => { wrap.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body })) })
    await act(async () => { wrap.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, relatedTarget: document.body })) })
    expect(q('buddy-bubble')?.dataset.auto).toBeUndefined()
  })

  it('the message box marks the page; the highlighted menu row has a soft fill, no left bar', async () => {
    expect(document.body.dataset.composerMenu).toBe('true')
    await click(q('composer-plus'))
    const row = q('menu-take-photo') as HTMLElement
    expect(row.className).toContain('rounded-row')
    expect(row.className).toContain('bg-sunk')
    expect(row.className).not.toContain('inset_4px')
  })
})
