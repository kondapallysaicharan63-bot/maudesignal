import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it } from 'vitest'
import { OutcomeView } from './components/LiveCheckView'
import shapes from './fixtures/publicCheckAnswers.json'
import { checkDevice, resetLiveCheckMemory, type KeyStore } from './liveCheck'

// The exact JSON the merged API returns for GET /v1/public/check_device_type (captured, not hand-written).
// Release check 41193468764: with openFDA unreachable the API answers 200 with "check": null and a stored
// snapshot; the page used to treat that as "no readable check" and showed "the API did not answer".

const BASE = 'https://api.example.test'
const now = Date.UTC(2026, 9, 29, 8)
const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }))
const memStore = (): KeyStore => {
  const data = new Map<string, string>()
  return { getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v) }
}
const html = (out: Awaited<ReturnType<typeof checkDevice>>) => renderToStaticMarkup(<OutcomeView out={out} />)

describe('every answer shape of the merged API', () => {
  beforeEach(() => resetLiveCheckMemory())
  const run = (code: string, shape: { status: number; body: unknown }, local = memStore()) =>
    checkDevice(code, { fetcher: () => json(shape.body, shape.status), apiBase: BASE, session: memStore(), local, now })

  it('live answer: the result card', async () => {
    const out = await run('QAS', shapes.live)
    expect(out.ok && out.result?.product_code).toBe('QAS')
    expect(html(out)).toContain('Live from openFDA')
  })

  it('stored fallback (HTTP 200, "check": null): shown as a stored snapshot, not as a failure', async () => {
    const local = memStore()
    const out = await run('LLZ', shapes.stored, local)
    expect(out.ok && out.stored?.product_code).toBe('LLZ')
    const page = html(out)
    expect(page).toContain('Stored snapshot, not live')
    expect(page).toContain('33 reports')
    expect(page).toContain('href="https://api.fda.gov/device/event.json?search=device.device_report_product_code%3ALLZ')
    expect(page).not.toMatch(/did not answer|No result is shown|Live from openFDA/)
    expect(local.getItem('ms-live-cache:LLZ')).toBeNull() // never cached: the next check asks openFDA again
  })

  it('zero reports: a "no report" result card, not a failure', async () => {
    const out = await run('QAS', shapes.zero)
    expect(out.ok && out.result?.as_of).toBeNull()
    expect(html(out)).toContain('No report in the last two years')
  })

  it('unknown code (422): the API message with its "did you mean" code, no Streamlit hand-off', async () => {
    const out = await run('QAH', shapes.unknown)
    expect(!out.ok && out.kind === 'unknown-code').toBe(true)
    const page = html(out)
    expect(page).toContain('did you mean QIH?')
    expect(page).not.toContain('No result is shown')
  })

  it('openFDA down and code not stored (502): a server message with the API reason', async () => {
    const out = await run('ZZZ', shapes.down)
    expect(!out.ok && out.kind === 'server' && out.message).toContain('openFDA could not be reached just now')
  })
})
