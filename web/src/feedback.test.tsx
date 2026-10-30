import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { FeedbackDialog, PATIENT_WARNING, PRIVATE_NOTE } from './components/FeedbackDialog'
import {
  EMPTY_FORM,
  buildPayload,
  dialogKey,
  parseRef,
  resetVisits,
  resolveRef,
  sendVisit,
  submitFeedback,
  type FeedbackForm,
  type KeyValueStore,
} from './feedback'

function fakeStore(): KeyValueStore & { data: Map<string, string> } {
  const data = new Map<string, string>()
  return { data, getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v) }
}

const NOW = () => new Date('2026-10-30T12:00:00Z')
const BASE = 'https://api.example'
const form = (over: Partial<FeedbackForm> = {}): FeedbackForm => ({ ...EMPTY_FORM, rating: 4, ...over })

describe('ref codes', () => {
  it('accepts allowed codes and ignores the rest', () => {
    expect(parseRef('?r=abc_DEF-12')).toBe('abc_DEF-12')
    expect(parseRef('?x=1&r=ok')).toBe('ok')
    expect(parseRef('')).toBeNull()
    expect(parseRef('?r=')).toBeNull()
    expect(parseRef('?r=has space')).toBeNull()
    expect(parseRef('?r=a<b>')).toBeNull()
    expect(parseRef('?r=' + 'a'.repeat(33))).toBeNull()
    expect(parseRef('?r=' + 'a'.repeat(32))).toBe('a'.repeat(32))
  })

  it('is kept for the session after the parameter is gone', () => {
    const s = fakeStore()
    expect(resolveRef('?r=dr-smith', s)).toBe('dr-smith')
    expect(resolveRef('', s)).toBe('dr-smith')
    expect(resolveRef('?r=bad code!', s)).toBe('dr-smith')
  })

  it('does not store an invalid code, and survives a throwing store', () => {
    const s = fakeStore()
    expect(resolveRef('?r=bad!', s)).toBeNull()
    expect(s.data.size).toBe(0)
    const boom: KeyValueStore = {
      getItem: () => {
        throw new Error('blocked')
      },
      setItem: () => {
        throw new Error('blocked')
      },
    }
    expect(resolveRef('?r=ok1', boom)).toBe('ok1')
    expect(resolveRef('', boom)).toBeNull()
  })
})

describe('visit pings', () => {
  beforeEach(() => resetVisits())

  it('sends one ping per view per session with only ref, page and time', () => {
    const s = fakeStore()
    const fetcher = vi.fn(() => Promise.resolve({}))
    const sender = { fetcher }
    expect(sendVisit(BASE, 'abc', 'thread:1', s, sender, NOW)).toBe(true)
    expect(sendVisit(BASE, 'abc', 'thread:1', s, sender, NOW)).toBe(false)
    expect(sendVisit(BASE, 'abc', 'run:2', s, sender, NOW)).toBe(true)
    expect(fetcher).toHaveBeenCalledTimes(2)
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe(`${BASE}/v1/visit`)
    expect(JSON.parse(init.body as string)).toEqual({
      ref: 'abc',
      page: 'thread:1',
      client_ts: '2026-10-30T12:00:00.000Z',
    })
    expect(init.keepalive).toBe(true)
    expect(init.credentials).toBe('omit')
  })

  it('does not repeat after a reload within the same session', () => {
    const s = fakeStore()
    const fetcher = vi.fn(() => Promise.resolve({}))
    sendVisit(BASE, 'abc', 'new', s, { fetcher }, NOW)
    resetVisits() // a reload clears memory, sessionStorage stays
    expect(sendVisit(BASE, 'abc', 'new', s, { fetcher }, NOW)).toBe(false)
  })

  it('prefers sendBeacon and falls back to fetch', () => {
    const beacon = vi.fn(() => true)
    const fetcher = vi.fn(() => Promise.resolve({}))
    sendVisit(BASE, 'abc', 'a', fakeStore(), { beacon, fetcher }, NOW)
    expect(beacon).toHaveBeenCalledTimes(1)
    expect(fetcher).not.toHaveBeenCalled()
    sendVisit(BASE, 'abc', 'b', fakeStore(), { beacon: () => false, fetcher }, NOW)
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('sends nothing without a ref or an API base, and fetch failures are silent', async () => {
    const fetcher = vi.fn(() => Promise.reject(new Error('offline')))
    expect(sendVisit(BASE, null, 'a', null, { fetcher }, NOW)).toBe(false)
    expect(sendVisit(null, 'abc', 'a', null, { fetcher }, NOW)).toBe(false)
    expect(fetcher).not.toHaveBeenCalled()
    expect(sendVisit(BASE, 'abc', 'a', null, { fetcher }, NOW)).toBe(true)
    await Promise.resolve()
  })
})

describe('feedback payload', () => {
  it('has the agreed fields and trims text', () => {
    const p = buildPayload(
      form({ comment: ' hi ', blocker: 'b', one_thing: 'o', name: ' Ann ', role: 'RA', consent: 'quote_name_role' }),
      'abc',
      'thread:1',
      NOW,
    )
    expect(p).toEqual({
      rating: 4,
      comment: 'hi',
      blocker: 'b',
      one_thing: 'o',
      name: 'Ann',
      role: 'RA',
      consent: 'quote_name_role',
      ref: 'abc',
      page: 'thread:1',
      client_ts: '2026-10-30T12:00:00.000Z',
    })
  })

  it('defaults consent to no_quote and needs a rating', () => {
    expect(EMPTY_FORM.consent).toBe('no_quote')
    expect(buildPayload(EMPTY_FORM, null, 'new', NOW)).toBeNull()
    expect(buildPayload(form({ rating: 6 }), null, 'new', NOW)).toBeNull()
    expect(buildPayload(form({ consent: 'quote_anonymous' }), null, 'new', NOW)?.consent).toBe('quote_anonymous')
  })

  it('posts JSON to /v1/feedback and reports sent only on success', async () => {
    const fetcher = vi.fn(() => Promise.resolve({ ok: true, status: 201 }))
    const r = await submitFeedback(BASE, form(), 'abc', 'new', fetcher, NOW)
    expect(r).toEqual({ ok: true })
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe(`${BASE}/v1/feedback`)
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string).ref).toBe('abc')
  })
})

describe('error states never claim success', () => {
  const run = (res: () => Promise<{ ok: boolean; status: number }>, base: string | null = BASE) =>
    submitFeedback(base, form(), null, 'new', res, NOW)

  it('422 shows the patient-details message', async () => {
    const r = await run(() => Promise.resolve({ ok: false, status: 422 }))
    expect(r).toMatchObject({ ok: false, kind: 'patient_data' })
  })
  it('429 shows too many submissions', async () => {
    const r = await run(() => Promise.resolve({ ok: false, status: 429 }))
    expect(r).toMatchObject({ ok: false, kind: 'rate_limited', message: 'Too many submissions, try later' })
  })
  it('network error shows could not send', async () => {
    const r = await run(() => Promise.reject(new Error('x')))
    expect(r).toMatchObject({ ok: false, kind: 'network', message: 'Could not send; please try again later' })
  })
  it('500 and a missing API base are not success', async () => {
    expect((await run(() => Promise.resolve({ ok: false, status: 500 }))).ok).toBe(false)
    const fetcher = vi.fn()
    expect((await run(fetcher, null)).ok).toBe(false)
    expect(fetcher).not.toHaveBeenCalled()
  })
  it('no rating is not sent', async () => {
    const fetcher = vi.fn()
    const r = await submitFeedback(BASE, EMPTY_FORM, null, 'new', fetcher, NOW)
    expect(r).toMatchObject({ ok: false, kind: 'invalid' })
    expect(fetcher).not.toHaveBeenCalled()
  })
})

describe('dialog', () => {
  const html = renderToStaticMarkup(
    <FeedbackDialog open onClose={() => undefined} apiBase={BASE} refCode={null} page="new" />,
  ).split('&#x27;').join("'")
  it('shows the patient-data warning, private note and labelled fields', () => {
    expect(html).toContain(PATIENT_WARNING)
    expect(html).toContain(PRIVATE_NOTE)
    for (const t of [
      'Does this match real PMS/RA work?',
      'Comment',
      'What would stop your team using it?',
      'One thing that would make it useful?',
      'Name (optional)',
      'Role (optional)',
      'Quote me by name and role',
      'Quote me anonymously',
      "Don't quote me",
    ])
      expect(html).toContain(t)
    expect(html).toContain('role="dialog"')
    expect(html).toContain('aria-modal="true"')
  })
  it('submit is disabled until a rating is chosen, and the default consent is Do not quote', () => {
    expect(html).toMatch(/<button type="submit"[^>]*disabled/)
    expect(html).toMatch(/value="no_quote"[^>]*checked|checked[^>]*value="no_quote"/)
  })
  it('renders nothing when closed', () => {
    expect(
      renderToStaticMarkup(<FeedbackDialog open={false} onClose={() => undefined} apiBase={BASE} refCode={null} page="x" />),
    ).toBe('')
  })
})

describe('dialog keyboard', () => {
  const key = (k: string, shiftKey = false) => ({ key: k, shiftKey, preventDefault: vi.fn() })
  it('Escape closes', () => {
    const close = vi.fn()
    dialogKey(key('Escape'), ['a', 'b'], 'a', close, vi.fn())
    expect(close).toHaveBeenCalledTimes(1)
  })
  it('Tab wraps last to first and Shift+Tab first to last', () => {
    const focus = vi.fn()
    const close = vi.fn()
    dialogKey(key('Tab'), ['a', 'b', 'c'], 'c', close, focus)
    expect(focus).toHaveBeenLastCalledWith('a')
    dialogKey(key('Tab', true), ['a', 'b', 'c'], 'a', close, focus)
    expect(focus).toHaveBeenLastCalledWith('c')
    dialogKey(key('Tab'), ['a', 'b', 'c'], 'b', close, focus)
    expect(focus).toHaveBeenCalledTimes(2)
    expect(close).not.toHaveBeenCalled()
  })
})
