// @vitest-environment jsdom
// Investigate a complaint (F25): the recorded example (no API address, nothing called), the live call and every error,
// the evidence text (fixed notice, "as entered; not stored", every count with its openFDA query), Copy and Download,
// the address contract (?code=&device=) and the two entry points.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import example from '../fixtures/investigateExample.json'
import threads from '../../public/data/threads.json'
import { MessageBox } from '../components/MessageBox'
import { isV2Path, V2_SEGMENTS } from '../layoutFlag'
import type { Thread } from '../types'
import { formatRoute, hrefFor, parseRoute, routeName, withRouteQuery } from '../v2/router'
import vercel from '../../vercel.json'
import {
  BANNER,
  evidenceFileName,
  evidenceText,
  fdaUrl,
  investigate,
  NOTICE,
  parseInvestigation,
  type Investigation,
} from './api'
import { InvestigateCard, InvestigateEntry } from './entry'
import { InvestigatePage } from './InvestigatePage'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const FIX = (example as { answer: unknown }).answer
const INPUT = (example as { input: { product_code: string; description: string } }).input
const A = parseInvestigation(FIX) as Investigation
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

let host: HTMLDivElement
let root: Root
beforeEach(() => {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})
afterEach(() => {
  act(() => root.unmount())
  host.remove()
  vi.restoreAllMocks()
})
const q = (id: string) => document.querySelector(`[data-testid="${id}"]`) as HTMLElement | null
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 20)) })
const click = (el: Element | null) => act(async () => { (el as HTMLElement).click() })
function typeInto(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  return act(async () => {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
    Object.getOwnPropertyDescriptor(proto, 'value')?.set?.call(el, value)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

describe('the recorded fixture', () => {
  it('parses, is labelled recorded, and its counts add up', () => {
    expect(A.mode).toBe('recorded')
    expect(A.source_note).toMatch(/^Recorded example\./)
    expect(A.months).toHaveLength(12)
    expect(A.months.reduce((n, m) => n + m.code_wide, 0)).toBe(A.total_code_wide.value)
    expect(A.months.reduce((n, m) => n + (m.keyword_matched ?? 0), 0)).toBe(A.total_keyword_matched?.value)
    expect(A.total_keyword_matched!.value).toBeLessThan(A.total_code_wide.value)
  })
  it('keeps an openFDA link on every figure and never the description', () => {
    const urls = [A.total_code_wide.url, ...A.months.map((m) => m.code_wide_url), ...A.quotes.map((x) => x.url)]
    expect(urls.every((u) => u.startsWith('https://api.fda.gov/'))).toBe(true)
    expect(JSON.stringify(FIX)).not.toContain('report manager would not let users save')
  })
  it('has verbatim, gate-checked quotes with report numbers', () => {
    expect(A.quotes.length).toBeGreaterThan(0)
    for (const x of A.quotes) {
      expect(x.gate).toBe('verbatim match')
      expect(x.report_number).toBeTruthy()
    }
  })
})

describe('parsing', () => {
  it('drops a link that is not on openFDA', () => {
    expect(fdaUrl('https://evil.example/x')).toBe('')
    expect(fdaUrl('http://api.fda.gov/x')).toBe('')
    const b = JSON.parse(JSON.stringify(FIX))
    b.total_code_wide.url = 'https://evil.example/'
    expect(parseInvestigation(b)?.total_code_wide.url).toBe('')
  })
  it('refuses an answer without its main figures', () => {
    expect(parseInvestigation(null)).toBeNull()
    expect(parseInvestigation({ product_code: 'LLZ' })).toBeNull()
    expect(parseInvestigation({ ...(FIX as object), product_code: 'llz1' })).toBeNull()
  })
})

describe('the evidence text', () => {
  const text = evidenceText(A, INPUT.description)
  it('has the date and time, the code, the description marked as not stored and the fixed notice', () => {
    expect(text).toContain(`Search date and time: ${A.retrieved_utc.slice(0, 10)}`)
    expect(text).toContain('Product code: LLZ')
    expect(text).toContain('Problem description (as entered by the user; not stored):')
    expect(text).toContain(INPUT.description)
    expect(text.endsWith(`${NOTICE}\n`)).toBe(true)
    expect(NOTICE).toBe(A.notice)
  })
  it('puts every count next to its openFDA query', () => {
    const lines = text.split('\n')
    for (const m of A.months) {
      const i = lines.findIndex((l) => l.startsWith(m.month))
      expect(i).toBeGreaterThan(-1)
      expect(lines[i]).toContain(`A: ${m.code_wide}`)
      expect(lines[i + 1]).toContain(m.code_wide_url)
    }
    expect(text).toContain(A.total_code_wide.url)
    expect(text).toContain(A.recalls.total!.url)
    expect(text).toContain(A.clearances.total!.url)
  })
  it('lists the quotes with report numbers and the recalls and 510(k)s', () => {
    for (const x of A.quotes) {
      expect(text).toContain(`"${x.quote}"`)
      expect(text).toContain(x.report_number as string)
    }
    for (const r of A.recalls.items) expect(text).toContain(r.recall_number)
    for (const c of A.clearances.items) expect(text).toContain(c.k_number)
  })
  it('never says MaudeSignal decided anything and names no file after the description', () => {
    expect(text).not.toMatch(/MaudeSignal determined|MaudeSignal decided|MaudeSignal found that/)
    expect(evidenceFileName(A)).toBe(`complaint-evidence-LLZ-${A.retrieved_date}.txt`)
    expect(evidenceFileName(A)).not.toContain('report')
  })
})

describe('the page without an API address (recorded example)', () => {
  it('shows the banner, the recorded label and the results, and calls nothing', async () => {
    const f = vi.fn()
    vi.stubGlobal('fetch', f)
    await act(async () => root.render(<InvestigatePage apiBase={null} />))
    expect(q('inv-banner')?.textContent).toBe(BANNER)
    expect(q('inv-recorded-note')?.textContent).toContain('Recorded example')
    expect(q('inv-provenance')?.textContent).toContain('Recorded example')
    expect((q('inv-code') as HTMLInputElement).value).toBe('LLZ')
    expect((q('inv-desc') as HTMLTextAreaElement).value).toBe(INPUT.description)
    expect(q('inv-run')).toBeNull()
    expect(q('inv-similar')?.textContent).toContain('Similar MAUDE events at other makers')
    expect(q('inv-quotes')?.querySelectorAll('[data-testid=inv-quote]').length).toBe(A.quotes.length)
    expect(q('inv-own-maker')?.textContent).toContain('cannot be separated')
    expect(q('inv-evidence')?.textContent).toContain('Evidence for the complaint file')
    expect(f).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })
  it('Copy puts the evidence text on the clipboard', async () => {
    const write = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: write }, configurable: true })
    await act(async () => root.render(<InvestigatePage apiBase={null} />))
    await click(q('inv-copy'))
    await flush()
    expect(write).toHaveBeenCalledTimes(1)
    expect(write.mock.calls[0][0]).toBe(evidenceText(A, INPUT.description))
    expect(q('inv-copy-status')?.textContent).toBe('Copied.')
  })
  it('Copy says so when the browser refuses, and selects the text', async () => {
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn().mockRejectedValue(new Error('no')) }, configurable: true })
    await act(async () => root.render(<InvestigatePage apiBase={null} />))
    await click(q('inv-copy'))
    await flush()
    expect(q('inv-copy-status')?.textContent).toContain('Ctrl+C')
  })
  it('Download makes a .txt file named after the code and date', async () => {
    const make = vi.fn(() => 'blob:x')
    Object.assign(URL, { createObjectURL: make, revokeObjectURL: vi.fn() })
    const names: string[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      names.push(this.download)
    })
    await act(async () => root.render(<InvestigatePage apiBase={null} />))
    await click(q('inv-download'))
    expect(make).toHaveBeenCalledTimes(1)
    expect(names).toEqual([evidenceFileName(A)])
  })
})

describe('the page with an API address', () => {
  const base = 'https://api.example'
  const live = { ...(FIX as object), mode: 'live', source_note: null }
  it('sends the code and the description once, and shows results labelled as real FDA data', async () => {
    const f = vi.fn().mockResolvedValue(json(200, live))
    await act(async () => root.render(<InvestigatePage apiBase={base} fetcher={f} code="llz" device="sim-3" />))
    expect(q('inv-device-note')?.textContent).toContain('sim-3')
    expect((q('inv-code') as HTMLInputElement).value).toBe('LLZ')
    expect((q('inv-run') as HTMLButtonElement).disabled).toBe(true)
    expect(q('inv-results')).toBeNull()
    await typeInto(q('inv-desc') as HTMLTextAreaElement, 'The viewer froze when saving a study')
    expect((q('inv-run') as HTMLButtonElement).disabled).toBe(false)
    await click(q('inv-run'))
    await flush()
    expect(f).toHaveBeenCalledTimes(1)
    const [url, init] = f.mock.calls[0] as [string, RequestInit]
    expect(url).toBe(`${base}/v1/investigate`)
    expect(init.method).toBe('POST')
    expect(init.credentials).toBe('omit')
    expect(JSON.parse(init.body as string)).toEqual({ product_code: 'LLZ', description: 'The viewer froze when saving a study' })
    expect(q('inv-provenance')?.textContent).toContain('Real FDA data')
    expect(q('inv-evidence-text')?.textContent).toContain('The viewer froze when saving a study')
    expect(q('inv-evidence-text')?.textContent).toContain('as entered by the user; not stored')
    expect(q('inv-notice')?.textContent).toBe(NOTICE)
  })
  it('keeps the description out of the address, storage and cookies', async () => {
    const f = vi.fn().mockResolvedValue(json(200, live))
    const set = vi.spyOn(Storage.prototype, 'setItem')
    await act(async () => root.render(<InvestigatePage apiBase={base} fetcher={f} code="LLZ" />))
    await typeInto(q('inv-desc') as HTMLTextAreaElement, 'zzqx unusual wording here')
    await click(q('inv-run'))
    await flush()
    expect(window.location.href).not.toContain('zzqx')
    expect(set.mock.calls.flat().join(' ')).not.toContain('zzqx')
    expect(document.cookie).not.toContain('zzqx')
  })
  it('shows the server message for patient data and no results', async () => {
    const f = vi.fn().mockResolvedValue(json(422, { code: 'patient_data', message: 'Please remove patient details. Nothing was answered or kept.' }))
    await act(async () => root.render(<InvestigatePage apiBase={base} fetcher={f} code="LLZ" />))
    await typeInto(q('inv-desc') as HTMLTextAreaElement, 'something with a name John Smith')
    await click(q('inv-run'))
    await flush()
    expect(q('inv-error-patient_data')?.textContent).toContain('Nothing was answered or kept')
    expect(q('inv-results')).toBeNull()
  })
  it.each([
    [429, { error: { code: 'rate_limited', message: 'Limit reached.' } }, 'inv-error-rate'],
    [502, { code: 'unavailable', message: 'openFDA could not be reached.' }, 'inv-error-unavailable'],
    [422, { error: { code: 'invalid_input', message: 'Invalid input: product_code.' } }, 'inv-error-invalid'],
    [500, {}, 'inv-error-bad-response'],
  ])('status %i shows an error and no invented numbers', async (status, body, id) => {
    const f = vi.fn().mockResolvedValue(json(status, body))
    await act(async () => root.render(<InvestigatePage apiBase={base} fetcher={f} code="LLZ" />))
    await typeInto(q('inv-desc') as HTMLTextAreaElement, 'the viewer froze')
    await click(q('inv-run'))
    await flush()
    expect(q(id)).not.toBeNull()
    expect(q('inv-results')).toBeNull()
  })
  it('a network error and an unreadable answer show nothing but a message', async () => {
    const o1 = await investigate('LLZ', 'abcde', { apiBase: base, fetcher: () => Promise.reject(new Error('x')) })
    expect(o1).toMatchObject({ ok: false, kind: 'network' })
    const o2 = await investigate('LLZ', 'abcde', { apiBase: base, fetcher: async () => json(200, { nope: 1 }) })
    expect(o2).toMatchObject({ ok: false, kind: 'bad-response' })
    const o3 = await investigate('LLZ', 'abcde', { apiBase: null, fetcher: vi.fn() })
    expect(o3).toMatchObject({ ok: false, kind: 'unconfigured' })
  })
})

describe('the address', () => {
  it('/investigate is a v2 path and is rewritten on Vercel', () => {
    expect(V2_SEGMENTS).toContain('investigate')
    expect(isV2Path('/investigate')).toBe(true)
    expect(vercel.rewrites.some((r) => r.source === '/investigate')).toBe(true)
    for (const seg of V2_SEGMENTS) expect(vercel.rewrites.some((r) => r.source.startsWith(`/${seg}`))).toBe(true)
  })
  it('?code and ?device fill the route; anything else is ignored', () => {
    expect(parseRoute('/investigate', '?layout=v2&code=llz&device=sim-3')).toEqual({ page: 'investigate', code: 'LLZ', device: 'sim-3' })
    expect(parseRoute('/investigate', '?code=LLZZ&device=<script>')).toEqual({ page: 'investigate' })
    expect(parseRoute('/investigate')).toEqual({ page: 'investigate' })
    expect(formatRoute({ page: 'investigate', code: 'LLZ' })).toBe('investigate')
    expect(routeName({ page: 'investigate', code: 'LLZ' })).toBe('investigate')
  })
  it('hrefFor keeps ?layout and ?r and sets code and device; other pages drop them', () => {
    const loc = { pathname: '/', search: '?layout=v2&r=TEST-1' }
    expect(hrefFor({ page: 'investigate', code: 'LLZ', device: 'sim-3' }, loc, 'v2')).toBe('/investigate?layout=v2&r=TEST-1&code=LLZ&device=sim-3')
    expect(hrefFor({ page: 'investigate' }, loc, 'v2')).toBe('/investigate?layout=v2&r=TEST-1')
    const there = { pathname: '/investigate', search: '?layout=v2&code=LLZ&device=sim-3' }
    expect(hrefFor({ page: 'home' }, there, 'v2')).toBe('/?layout=v2')
    expect(withRouteQuery('?layout=v2&r=A%20B', { page: 'home' })).toBe('?layout=v2&r=A%20B')
  })
})

describe('the entry points', () => {
  it('the Home card has one main button', async () => {
    const open = vi.fn()
    await act(async () => root.render(<InvestigateCard onOpen={open} />))
    const buttons = q('home-investigate')!.querySelectorAll('button')
    expect(buttons).toHaveLength(1)
    expect(buttons[0].textContent).toBe('Investigate a complaint')
    await click(buttons[0])
    expect(open).toHaveBeenCalledTimes(1)
  })
  const box = (
    <MessageBox
      threads={threads.threads as unknown as Thread[]}
      onThread={() => undefined}
      viewKey="home"
      codes={[]}
      onCode={() => undefined}
      onCamera={() => undefined}
      onMic={() => undefined}
      onSample={() => undefined}
    />
  )
  it('the + menu has the item only where the v2 shell provides it, between the sample label and voice', async () => {
    const open = vi.fn()
    await act(async () => root.render(<InvestigateEntry.Provider value={{ open }}>{box}</InvestigateEntry.Provider>))
    await click(q('composer-plus'))
    const ids = [...document.querySelectorAll('[role=menu] [role^=menuitem]')].map((e) => e.getAttribute('data-testid'))
    expect(ids).toEqual(['menu-take-photo', 'menu-upload-photo', 'menu-sample-label', 'menu-investigate', 'menu-voice'])
    await click(q('menu-investigate'))
    expect(open).toHaveBeenCalledTimes(1)
  })
  it('the classic layout (no provider) has no such item', async () => {
    await act(async () => root.render(box))
    await click(q('composer-plus'))
    expect(q('menu-investigate')).toBeNull()
  })
})
