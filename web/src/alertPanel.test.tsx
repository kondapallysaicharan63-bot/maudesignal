// @vitest-environment jsdom
// DOM tests: the alert panel, the mentions box and the Connect page in jsdom (no network: fake fetch).
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AlertDetail, AlertsFile } from './alerts'
import { AlertPanel } from './components/AlertPanel'
import { ConnectView } from './components/ConnectView'
import { MentionsBox } from './components/MentionsBox'
import { parseMentions, zeroLine, statusLabel } from './mentions'
import alerts from '../public/data/alerts.json'
import publicMentions from '../public/data/mentions.json'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const file = alerts as unknown as AlertsFile
const company = file.alerts.find((a) => a.id.startsWith('company:') && a.reports.length > 0)!
const noOwner = file.alerts.find((a) => !a.owner) ?? { ...file.alerts[0], owner: null }

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
})
const q = (id: string) => host.querySelector(`[data-testid=${id}]`)
const tick = async () => {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0))
  })
}

function panel(detail: AlertDetail | null, over: Partial<Parameters<typeof AlertPanel>[0]> = {}) {
  const onClose = vi.fn()
  const onOpenInChat = vi.fn()
  act(() => root.render(<AlertPanel detail={detail} fallbackCode="ZZZ" onClose={onClose} onOpenInChat={onOpenInChat} apiBase={null} mentions={null} {...over} />))
  return { onClose, onOpenInChat }
}

describe('AlertPanel', () => {
  it('prints every section for a device alert, with the simulated banner and the gate line', () => {
    panel(company)
    const text = host.textContent ?? ''
    for (const s of ['What changed', 'Reports behind it', 'Recalls and 510(k)', 'Who filed', 'Next steps', 'Owner and status']) expect(text).toContain(s)
    expect(q('alert-simulated-banner')?.textContent).toBe('Simulated company — sample data. Problem evidence is real FDA data.')
    expect(q('alert-gate')?.textContent).toMatch(/^\d+ facts? checked, \d+ passed, \d+ held back$/)
    expect(q('alert-showing')?.textContent).toMatch(/^showing \d+ of \d+/)
    expect(text).toContain('A person decides')
    expect(q('alert-owner')?.textContent).toContain('(simulated)')
  })
  it('every number links to openFDA and every quote is in quotation marks', () => {
    panel(company)
    const nums = host.querySelectorAll('[data-testid=alert-number]')
    expect(nums.length).toBeGreaterThan(2)
    for (const n of nums) expect(n.querySelector('a')?.getAttribute('href')).toMatch(/^https:\/\/api\.fda\.gov\//)
    for (const b of host.querySelectorAll('[data-testid=alert-report] blockquote')) expect(b.textContent).toMatch(/^“.+”$/)
  })
  it('an alert without an owner has no owner section and no banner', () => {
    panel({ ...noOwner, owner: null })
    expect(q('alert-owner')).toBeNull()
    expect(q('alert-simulated-banner')).toBeNull()
  })
  it('hides the empty 0 and 0 window when the owner marked Needs review and no weekly rule fired', () => {
    const w = company.window ?? { this_week: { from: '2026-09-24', to: '2026-09-30', count: 0 }, baseline_4wk: { from: '2026-08-27', to: '2026-09-23', count: 0, weekly_mean: 0 } }
    panel({ ...company, rule: null, window: { this_week: { ...w.this_week, count: 0 }, baseline_4wk: { ...w.baseline_4wk, count: 0 } } })
    expect(q('alert-window')).toBeNull()
    expect(q('alert-rule-words')).not.toBeNull()
  })
  it('no stored detail says so and still offers Open in chat for the code', () => {
    const { onOpenInChat } = panel(null)
    expect(q('alert-no-detail')?.textContent).toContain('No stored detail')
    act(() => (q('open-in-chat') as HTMLButtonElement).click())
    expect(onOpenInChat).toHaveBeenCalledWith({ product_code: 'ZZZ', rule: null })
  })
  it('no stored reports: says so and points at the openFDA links', () => {
    panel({ ...company, reports: [], reports_total: 4, reports_stored: null })
    expect(q('alert-no-reports')?.textContent).toContain('No reports are stored')
  })
  it('a report without a quote says why instead of showing a blank', () => {
    panel({ ...company, reports: [{ ...company.reports[0], quote: null, quote_note: 'No sentence of this report could be quoted (no narrative text, or no usable sentence).' }] })
    expect(host.textContent).toContain('No sentence of this report could be quoted')
  })
  it('Esc closes and the scrim closes', () => {
    const { onClose } = panel(company)
    act(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    })
    expect(onClose).toHaveBeenCalledTimes(1)
    act(() => (q('alert-panel-scrim') as HTMLElement).click())
    expect(onClose).toHaveBeenCalledTimes(2)
  })
  it('Tab on the last control wraps to the first; Shift+Tab on the first wraps to the last', () => {
    panel(company)
    const dlg = q('alert-panel') as HTMLElement
    const els = Array.from(dlg.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), summary')).filter((e) => !e.closest('[hidden]'))
    const first = els[0]
    const last = els[els.length - 1]
    last.focus()
    const ev = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    act(() => {
      last.dispatchEvent(ev)
    })
    // jsdom has no layout (offsetParent is null), so the trap sees the focused element only; the rule under test is the wrap itself.
    expect(ev.defaultPrevented || document.activeElement === last).toBe(true)
    first.focus()
    expect(dlg.contains(document.activeElement)).toBe(true)
  })
  it('forbidden words never appear in the panel text', () => {
    panel(company)
    expect(host.textContent).not.toMatch(/\b(safe|unsafe|compliant|validated|overnight)\b|FDA-approved|complaint data|worsening signals|citation-checked/i)
  })
})

const mentionsBody = {
  product_code: 'LLZ',
  searched_utc: '2026-10-31T00:00:00Z',
  mentions: [
    { source_name: 'FDA', source_kind: 'official', date: '2026-10-01', url: 'https://www.fda.gov/x', quote: 'A sentence on an FDA page.', why_matched: 'matched: LLZ', badge: 'x' },
    { source_name: 'News', source_kind: 'news', date: null, url: 'https://example.com/n', quote: 'Dr. Smith said so.', why_matched: 'matched', badge: 'x' },
    { source_name: 'Blog', source_kind: 'web', date: '2026-10-02', url: 'https://example.com/b', quote: 'A sentence on a blog.', why_matched: 'matched: device', badge: 'x' },
  ],
  dropped: { quote_not_found: 1, personal_details: 0, off_topic: 0 },
  sources_tried: [{ name: 'GDELT', url: 'https://api.gdeltproject.org/x', status: 'ok', n: 3 }],
  mode: 'live',
}

describe('MentionsBox', () => {
  it('nothing stored: "No stored search yet", no mention invented', () => {
    act(() => root.render(<MentionsBox code="LLZ" apiBase={null} stored={null} />))
    expect(q('mentions-none')?.textContent).toBe('No stored search yet')
    expect(host.querySelectorAll('[data-testid=mention]')).toHaveLength(0)
    expect(host.textContent).toContain('News and public web (unverified)')
  })
  it('no API: the button explains and leaves the stored search in place', () => {
    const stored = { ...parseMentions(mentionsBody)!, mode: 'recorded' as const }
    act(() => root.render(<MentionsBox code="LLZ" apiBase={null} stored={stored} />))
    expect(host.querySelectorAll('[data-testid=mention]')).toHaveLength(2)
    act(() => (q('search-outside') as HTMLButtonElement).click())
    expect(q('mentions-notice')?.textContent).toContain('not connected')
    expect(host.querySelectorAll('[data-testid=mention]')).toHaveLength(2)
  })
  it('live: drops the quote with a name, counts it, marks only fda.gov as Official source, every one Unverified', async () => {
    const f = vi.fn(async () => new Response(JSON.stringify(mentionsBody), { status: 200 }))
    act(() => root.render(<MentionsBox code="LLZ" terms={['x']} apiBase="https://a.test" stored={null} fetcher={f} />))
    act(() => (q('search-outside') as HTMLButtonElement).click())
    await tick()
    expect(q('mentions-dropped')?.textContent).toBe('2 found, 1 dropped because the quote was not on the page, 1 dropped for personal details')
    expect(host.querySelectorAll('[data-testid=official-badge]')).toHaveLength(1)
    const badges = Array.from(host.querySelectorAll('[data-testid=unverified-badge]')).map((b) => b.textContent)
    expect(badges).toEqual(['Unverified — not checked against FDA records', 'Unverified — not checked against FDA records'])
    expect(host.textContent).not.toContain('Dr. Smith')
    expect(f).toHaveBeenCalledTimes(1)
  })
  it('zero mentions: "0 found in these sources (date)" and every source with status and count; MassDevice never shown', () => {
    const zero = {
      ...mentionsBody,
      mentions: [],
      dropped: { quote_not_found: 0, personal_details: 0, off_topic: 0 },
      sources_tried: [
        { name: 'GDELT DOC 2.0 (news index)', url: 'https://api.gdeltproject.org/x', status: 'failed: ConnectTimeout', n: 0 },
        { name: 'FDA recalls (RSS)', url: 'https://www.fda.gov/r.xml', status: 'ok', n: 0 },
        { name: 'MassDevice (RSS)', url: 'https://www.massdevice.com/feed/', status: 'failed: http 403', n: 0 },
      ],
      mode: 'recorded',
    }
    const stored = parseMentions(zero)!
    act(() => root.render(<MentionsBox code="LLZ" apiBase={null} stored={stored} />))
    expect(q('mentions-zero-line')?.textContent).toBe('0 found in these sources (2026-10-31)')
    const rows = Array.from(host.querySelectorAll('[data-testid=source-row]')).map((r) => r.textContent ?? '')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toContain('failed: ConnectTimeout')
    expect(rows[1]).toContain('done')
    expect(rows[1]).toContain('0 pages')
    expect(host.textContent).not.toMatch(/massdevice/i)
    expect(host.textContent).not.toContain('Nothing was kept')
    expect(host.querySelectorAll('[data-testid=mention]')).toHaveLength(0)
  })
  it('the shipped LLZ record: no MassDevice anywhere (sources and steps), failed steps read failed', () => {
    const llz = parseMentions((publicMentions as unknown as { codes: Record<string, unknown> }).codes.LLZ)!
    act(() => root.render(<MentionsBox code="LLZ" apiBase={null} stored={{ ...llz, mode: 'recorded' }} />))
    expect(host.textContent).not.toMatch(/massdevice/i)
    const steps = Array.from(host.querySelectorAll('[data-testid=trace-step]')).map((r) => r.textContent ?? '')
    expect(steps.length).toBeGreaterThan(0)
    const gdelt = steps.find((t) => t.includes('GDELT'))!
    expect(gdelt).toContain('failed')
    expect(gdelt).not.toContain('done')
    const warn = steps.find((t) => t.includes('warning letters'))!
    expect(warn).toContain('failed')
    expect(warn).not.toContain('done')
    expect(steps.find((t) => t.includes('recalls'))).toContain('done')
  })
  it('a "failed: ConnectTimeout" trace step is failed, a skipped one not searched, anything else unknown', () => {
    const r = parseMentions({
      ...mentionsBody,
      trace: [
        { step: 'A', ms: 1, status: 'failed: ConnectTimeout' },
        { step: 'B', ms: 1, status: 'skipped' },
        { step: 'C', ms: 1, status: 'ok' },
        { step: 'D', ms: 1, status: '0 page(s) tried' },
        { step: 'Search: MassDevice (RSS)', ms: 1, status: 'ok' },
      ],
    })!
    expect(r.trace.map((t) => t.step)).toEqual(['A', 'B', 'C', 'D'])
    expect(r.trace.map((t) => t.status)).toEqual(['failed', 'not_searched', 'ok', 'unknown'])
    expect(r.trace[0].note).toBe('ConnectTimeout')
  })
  it('zeroLine and statusLabel handle missing data honestly', () => {
    expect(zeroLine('')).toBe('0 found in these sources (date not recorded)')
    expect(statusLabel('')).toBe('unknown')
    expect(statusLabel('http 500')).toBe('unknown: http 500')
    expect(statusLabel('ok')).toBe('done')
  })
  it('a MassDevice mention in the data is dropped', () => {
    const r = parseMentions({ ...mentionsBody, mentions: [{ source_name: 'MassDevice', source_kind: 'news', url: 'https://www.massdevice.com/a', quote: 'A sentence.', why_matched: 'x', badge: 'x' }] })!
    expect(r.mentions).toHaveLength(0)
  })
  it('429: falls back to the stored search and says why', async () => {
    const stored = { ...parseMentions(mentionsBody)!, mode: 'recorded' as const }
    const f = vi.fn(async () => new Response(JSON.stringify({ message: 'x' }), { status: 429 }))
    act(() => root.render(<MentionsBox code="LLZ" apiBase="https://a.test" stored={stored} fetcher={f} />))
    act(() => (q('search-outside') as HTMLButtonElement).click())
    await tick()
    expect(q('mentions-notice')?.textContent).toContain('Daily live limit reached')
    expect(q('mentions-result')?.getAttribute('data-mode')).toBe('recorded')
  })
  it('a network error with nothing stored says "No stored search yet"', async () => {
    const f = vi.fn(async () => Promise.reject(new TypeError('x')))
    act(() => root.render(<MentionsBox code="LLZ" apiBase="https://a.test" stored={null} fetcher={f} />))
    act(() => (q('search-outside') as HTMLButtonElement).click())
    await tick()
    expect(q('mentions-notice')?.textContent).toContain('No stored search yet')
    expect(q('mentions-none')).not.toBeNull()
  })
})

describe('ConnectView', () => {
  it('no API: fixed text with the MCP URL, the OpenAPI URL, ask Charan for a key, and the privacy and terms links', () => {
    act(() => root.render(<ConnectView apiBase={null} />))
    const t = host.textContent ?? ''
    expect(t).toContain('https://maudesignal-api.vercel.app/mcp')
    expect(t).toContain('https://maudesignal-api.vercel.app/openapi.json')
    expect(t).toContain('Ask Charan for a key')
    expect(q('connect-status')?.textContent).toContain("Submitted to Meta's Muse Connector Program — pending review.")
    expect(q('no-demo-key')).not.toBeNull()
    expect(q('link-privacy')?.getAttribute('href')).toBe('https://maudesignal-api.vercel.app/privacy')
    expect(q('link-terms')?.getAttribute('href')).toBe('https://maudesignal-api.vercel.app/terms')
    expect(host.querySelectorAll('[data-testid=connect-steps] li')).toHaveLength(3)
  })
  it('with a key from the API: shows it, its limits, and a Copy button that copies it', async () => {
    const copy = vi.fn(async () => undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: copy }, configurable: true })
    const f = vi.fn(async () => new Response(JSON.stringify({ demo_key: 'abc-key', limits: { read_only: true, live_spark: false } }), { status: 200 }))
    act(() => root.render(<ConnectView apiBase="https://a.test" fetcher={f} />))
    await tick()
    expect(q('value-demo-key')?.textContent).toBe('abc-key')
    expect(q('demo-key-limits')?.textContent).toMatch(/read-only.*no live Spark.*rate-limited/)
    await act(async () => (q('copy-demo-key') as HTMLButtonElement).click())
    expect(copy).toHaveBeenCalledWith('abc-key')
  })
  it('API says nothing about a key: asks to ask Charan', async () => {
    const f = vi.fn(async () => new Response('{}', { status: 200 }))
    act(() => root.render(<ConnectView apiBase="https://a.test" fetcher={f} />))
    await tick()
    expect(q('no-demo-key')?.textContent).toContain('Ask Charan for a key')
    expect(q('value-demo-key')).toBeNull()
  })
})
