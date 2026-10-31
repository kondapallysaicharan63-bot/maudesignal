// Unit tests: alert detail helpers, outside mentions (validation, never-trust rules, the POST), the connect answer.
import { describe, expect, it } from 'vitest'
import { chatQuestion, detailFor, findAlert, gateLine, hasPersonalDetails, parseAlerts, rangeLine, safeUrl, showingLine, type AlertsFile } from './alerts'
import { connectSteps, fetchConnect, FALLBACK_INFO, parseConnect } from './connect'
import { LiveError, postMentions } from './live/api'
import {
  buildMentionsBody,
  cleanCode,
  cleanTerms,
  droppedLine,
  isOfficialUrl,
  MENTION_BADGE,
  parseMentions,
  storedMentions,
  type MentionsFile,
} from './mentions'
import alerts from '../public/data/alerts.json'

const file = alerts as unknown as AlertsFile

describe('alerts.json as exported', () => {
  it('has the contract fields on every alert', () => {
    expect(file.alerts.length).toBeGreaterThan(0)
    for (const a of file.alerts) {
      expect(a.id).toMatch(/^(sweep|brief|company):/)
      expect(a.next_steps.some((s) => s.includes('A person decides'))).toBe(true)
      expect(a.gate.checked).toBe(a.gate.passed + a.gate.withheld)
      expect(a.reports.length).toBeLessThanOrEqual(10)
      for (const n of a.numbers) expect(n.openfda_url).toMatch(/^https:\/\/api\.fda\.gov\//)
      for (const r of a.reports) if (r.quote) expect(hasPersonalDetails(r.quote)).toBe(false)
      expect(JSON.stringify(a)).not.toMatch(/\b(safe|unsafe|compliant|validated|overnight)\b|FDA-approved|complaint data/i)
    }
  })
  it('a quote never invents text: it is a sentence of at most 220 characters', () => {
    for (const a of file.alerts) for (const r of a.reports) if (r.quote) expect(r.quote.length).toBeLessThanOrEqual(220)
  })
})

describe('alert helpers', () => {
  it('finds by id, then by product code, else null', () => {
    const first = file.alerts[0]
    expect(findAlert(file, first.id)?.id).toBe(first.id)
    expect(findAlert(file, 'nope:XXX', first.product_code)?.product_code).toBe(first.product_code)
    expect(findAlert(file, 'nope:XXX')).toBeNull()
    expect(findAlert(null, first.id)).toBeNull()
    expect(findAlert({ alerts: 'x' } as unknown as AlertsFile, first.id)).toBeNull()
  })
  it('detailFor takes a bell item', () => {
    const a = file.alerts[0]
    expect(detailFor(file, { id: a.id, productCode: a.product_code } as never)?.id).toBe(a.id)
  })
  it('prints the gate line and the showing line in the contract words', () => {
    expect(gateLine({ checked: 13, passed: 12, withheld: 1 })).toBe('13 facts checked, 12 passed, 1 held back')
    expect(gateLine({ checked: 1, passed: 1, withheld: 0 })).toBe('1 fact checked, 1 passed, 0 held back')
    expect(showingLine(10, 21)).toBe('showing 10 of 21')
    expect(showingLine(3, null)).toBe('showing 3 of 3')
    expect(rangeLine({ from: '2026-09-24', to: '2026-09-30' })).toBe('2026-09-24 to 2026-09-30')
  })
  it('only https links are links', () => {
    expect(safeUrl('https://api.fda.gov/x')).toBe('https://api.fda.gov/x')
    for (const u of ['http://x.test', 'javascript:alert(1)', '', null, undefined, 'ftp://x']) expect(safeUrl(u as string)).toBeNull()
  })
  it('the chat question names the code and the rule and nothing else', () => {
    expect(chatQuestion({ product_code: 'IYN', rule: 'reports suddenly increased' })).toContain('IYN')
    expect(chatQuestion({ product_code: 'IYN', rule: null })).toBe('What changed for IYN this week?')
  })
  it('parseAlerts rejects odd shapes and keeps only usable alerts', () => {
    expect(parseAlerts(null)).toBeNull()
    expect(parseAlerts('x')).toBeNull()
    expect(parseAlerts({ alerts: 3 })).toBeNull()
    expect(parseAlerts({ alerts: [null, 1, { id: 'a' }, file.alerts[0]] })?.alerts).toHaveLength(1)
  })
  it('detects personal details', () => {
    for (const t of ['Dr. Smith called', 'patient Jones fell', 'A 54-year-old man', 'aged 61', 'mail a@b.com', 'call 555-123-4567'])
      expect(hasPersonalDetails(t), t).toBe(true)
    for (const t of ['The device stopped responding.', 'The patient was monitored.', 'Patient information is limited.', 'It was 3 years ago.'])
      expect(hasPersonalDetails(t), t).toBe(false)
  })
})

const ok = (m: Record<string, unknown>) => ({
  source_name: 'S',
  source_kind: 'news',
  date: '2026-10-20',
  url: 'https://example.com/a',
  quote: 'A sentence found on the page.',
  why_matched: 'matched: LLZ',
  badge: 'whatever',
  ...m,
})

describe('mentions: never trust the answer further than the page can see', () => {
  const body = (mentions: unknown[], extra: Record<string, unknown> = {}) => ({ product_code: 'llz', searched_utc: '2026-10-31T00:00:00Z', mentions, ...extra })
  it('prints its own fixed badge, whatever the server wrote', () => {
    const r = parseMentions(body([ok({ badge: 'Verified by FDA' })]))!
    expect(r.mentions[0].badge).toBe(MENTION_BADGE)
    expect(r.mentions[0].badge).toBe('Unverified — not checked against FDA records')
  })
  it('Official source only for a fda.gov address', () => {
    const r = parseMentions(
      body([
        ok({ source_kind: 'official', url: 'https://example.com/fda.gov' }),
        ok({ source_kind: 'news', url: 'https://www.fda.gov/news' }),
        ok({ source_kind: 'official', url: 'https://fda.gov.evil.test/x' }),
        ok({ source_kind: 'official', url: 'https://www.fda.gov/safety/recalls' }),
      ]),
    )!
    expect(r.mentions.map((m) => m.source_kind)).toEqual(['web', 'official', 'web', 'official'])
    expect(isOfficialUrl('http://www.fda.gov/x')).toBe(false)
    expect(isOfficialUrl('not a url')).toBe(false)
  })
  it('drops and counts a quote with personal details; drops non-https links and empty quotes', () => {
    const r = parseMentions(body([ok({ quote: 'Dr. Smith said it failed.' }), ok({ url: 'http://example.com/a' }), ok({ quote: '   ' }), ok({})], { dropped: { quote_not_found: 2, personal_details: 1, off_topic: 4 } }))!
    expect(r.mentions).toHaveLength(1)
    expect(r.dropped).toEqual({ quote_not_found: 2, personal_details: 2, off_topic: 4 })
  })
  it('keeps at most 10 mentions and rejects a body without the list', () => {
    expect(parseMentions(body(Array.from({ length: 14 }, (_, i) => ok({ url: `https://example.com/${i}` }))))!.mentions).toHaveLength(10)
    expect(parseMentions({})).toBeNull()
    expect(parseMentions(null)).toBeNull()
    expect(parseMentions({ mentions: 'x' })).toBeNull()
  })
  it('wrong types become zero or empty, never a crash', () => {
    const r = parseMentions({ mentions: [], dropped: { quote_not_found: 'x', personal_details: -3, off_topic: null }, sources_tried: [null, { name: 1, url: 'http://x', status: 2, n: 'z' }], limits: 'x', trace: 5 })!
    expect(r.dropped).toEqual({ quote_not_found: 0, personal_details: 0, off_topic: 0 })
    expect(r.sources_tried[0]).toEqual({ name: '1', url: '', status: '2', n: 0 })
    expect(r.limits).toBeNull()
    expect(r.trace).toEqual([])
    expect(r.mode).toBe('live')
  })
  it('the dropped line is in the contract words', () => {
    expect(droppedLine(3, { quote_not_found: 2, personal_details: 1, off_topic: 0 })).toBe('3 found, 2 dropped because the quote was not on the page, 1 dropped for personal details')
  })
  it('a stored search is shown as recorded; none stored gives null (nothing invented)', () => {
    const f: MentionsFile = { schema_version: '1.0', codes: { LLZ: body([ok({})]) as never }, notes: [] }
    expect(storedMentions(f, 'llz')?.mode).toBe('recorded')
    expect(storedMentions(f, 'QIH')).toBeNull()
    expect(storedMentions(null, 'LLZ')).toBeNull()
    expect(storedMentions({ schema_version: '1.0', codes: {}, notes: [] }, 'LLZ')).toBeNull()
  })
})

describe('mentions request', () => {
  it('sends only a three-letter code and at most 5 short terms', () => {
    expect(buildMentionsBody('llz')).toEqual({ product_code: 'LLZ' })
    expect(buildMentionsBody('llz', ['a', ' ', 'A', 'b', 'c', 'd', 'e', 'f'])).toEqual({ product_code: 'LLZ', device_terms: ['a', 'b', 'c', 'd', 'e'] })
    expect(cleanTerms(['x'.repeat(100)])[0]).toHaveLength(60)
    for (const bad of ['', 'AB', 'ABCD', '123', 'A B', 'L1Z']) expect(() => buildMentionsBody(bad)).toThrow()
    expect(cleanCode(' qih ')).toBe('QIH')
  })
  const fakeFetch = (status: number, body: unknown) => {
    const calls: { url: string; init?: RequestInit }[] = []
    const f = async (url: string, init?: RequestInit) => {
      calls.push({ url, init })
      return new Response(JSON.stringify(body), { status })
    }
    return { f, calls }
  }
  it('POSTs JSON without credentials to /v1/live/mentions', async () => {
    const { f, calls } = fakeFetch(200, { mentions: [], product_code: 'LLZ' })
    const r = await postMentions('llz', ['x'], { apiBase: 'https://api.test', fetcher: f })
    expect(r.mentions).toEqual([])
    expect(calls[0].url).toBe('https://api.test/v1/live/mentions')
    expect(calls[0].init?.method).toBe('POST')
    expect(calls[0].init?.credentials).toBe('omit')
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ product_code: 'LLZ', device_terms: ['x'] })
  })
  it('429 is rate_limited, a bad body is bad_response, no address is not_configured, a bad code never leaves the page', async () => {
    await expect(postMentions('LLZ', [], { apiBase: 'https://a.test', fetcher: fakeFetch(429, { message: 'limit' }).f })).rejects.toMatchObject({ kind: 'rate_limited' })
    await expect(postMentions('LLZ', [], { apiBase: 'https://a.test', fetcher: fakeFetch(200, { x: 1 }).f })).rejects.toMatchObject({ kind: 'bad_response' })
    await expect(postMentions('LLZ', [], { apiBase: null, fetcher: fakeFetch(200, {}).f })).rejects.toMatchObject({ kind: 'not_configured' })
    const { f, calls } = fakeFetch(200, {})
    await expect(postMentions('12', [], { apiBase: 'https://a.test', fetcher: f })).rejects.toBeInstanceOf(LiveError)
    expect(calls).toHaveLength(0)
  })
})

describe('connect', () => {
  it('uses the API values and falls back per field', () => {
    const i = parseConnect({ mcp_url: 'https://x.test/mcp', openapi_url: 'http://insecure', demo_key: ' k ', limits: { read_only: true, live_spark: false } })!
    expect(i.mcp_url).toBe('https://x.test/mcp')
    expect(i.openapi_url).toBe('https://x.test/openapi.json')
    expect(i.demo_key).toBe('k')
    expect(i.limits.note).toContain('read-only')
    expect(i.limits.note).toContain('no live Spark')
    expect(i.fromApi).toBe(true)
  })
  it('reads the real API body: auth_header and demo_limits', () => {
    const i = parseConnect({
      mcp_url: 'https://maudesignal-api.vercel.app/mcp',
      openapi_url: 'https://maudesignal-api.vercel.app/openapi.json',
      docs_url: 'https://maudesignal-api.vercel.app/docs-page',
      auth_header: 'X-Demo-Key',
      demo_key: 'k1',
      demo_limits: { per_minute: 10, per_day: 200, live_model: false, note: 'Read tools only.' },
      steps: ['a'],
    })!
    expect(i.key_header).toBe('X-Demo-Key')
    expect(i.limits.live_spark).toBe(false)
    expect(i.limits.note).toBe('Read tools only. No live Spark answers. Rate limit: 10 calls a minute, 200 a day.')
    expect(i.privacy_url).toBe('https://maudesignal-api.vercel.app/privacy')
    expect(parseConnect({ demo_limits: { live_model: true, per_minute: 'x', per_day: -1 } })!.limits.note).toBe('Live Spark answers are on for this key.')
  })
  it('no key means null; a non-object means null', () => {
    expect(parseConnect({})!.demo_key).toBeNull()
    expect(parseConnect({ demo_key: '' })!.demo_key).toBeNull()
    expect(parseConnect([])).toBeNull()
    expect(parseConnect('x')).toBeNull()
  })
  it('any failure gives the fixed fallback with the MCP and OpenAPI addresses', async () => {
    expect(await fetchConnect(null)).toBe(FALLBACK_INFO)
    expect(await fetchConnect('https://a.test', async () => new Response('{}', { status: 404 }))).toBe(FALLBACK_INFO)
    expect(await fetchConnect('https://a.test', async () => Promise.reject(new TypeError('net')))).toBe(FALLBACK_INFO)
    expect(await fetchConnect('https://a.test', async () => new Response('not json', { status: 200 }))).toBe(FALLBACK_INFO)
    expect(FALLBACK_INFO.mcp_url).toBe('https://maudesignal-api.vercel.app/mcp')
    expect(FALLBACK_INFO.openapi_url).toBe('https://maudesignal-api.vercel.app/openapi.json')
  })
  it('three numbered steps: open connectors, add the MCP URL, paste the key in X-API-Key', () => {
    const s = connectSteps(FALLBACK_INFO)
    expect(s.map((x) => x.n)).toEqual([1, 2, 3])
    expect(s[0].text).toMatch(/connectors/)
    expect(s[1].text).toContain('https://maudesignal-api.vercel.app/mcp')
    expect(s[2].text).toContain('X-API-Key')
    expect(s.map((x) => x.text).join(' ')).not.toMatch(/sign in with/i)
  })
})
