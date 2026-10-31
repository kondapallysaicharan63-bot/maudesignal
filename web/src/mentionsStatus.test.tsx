// Regression tests for the outside-mentions status mapping, using the real stored LLZ file and the API's real status strings.
// @vitest-environment jsdom
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { MentionsBox } from './components/MentionsBox'
import { classifyStatus, parseMentions, statusLabel, storedMentions, zeroLine, type MentionsFile } from './mentions'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const file = JSON.parse(readFileSync(resolve(__dirname, '../public/data/mentions.json'), 'utf8')) as MentionsFile
const llz = storedMentions(file, 'LLZ')

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

describe('status mapping by prefix', () => {
  it('maps the real API strings', () => {
    expect(statusLabel('ok')).toBe('done')
    expect(statusLabel('failed: ConnectTimeout')).toBe('failed: ConnectTimeout')
    expect(statusLabel('failed: http 404')).toBe('failed: http 404')
    expect(statusLabel('skipped: time')).toBe('not searched: time')
    expect(statusLabel('skipped')).toBe('not searched')
  })
  it('anything else is unknown, never done', () => {
    for (const raw of ['', '0 page(s) tried', 'weird', 'done', 'pending']) {
      expect(classifyStatus(raw).kind).toBe('unknown')
      expect(statusLabel(raw).startsWith('unknown')).toBe(true)
    }
    expect(classifyStatus(undefined).kind).toBe('unknown')
  })
})

describe('the real stored LLZ file', () => {
  it('keeps the recorded MassDevice 403 in the stored file but never shows it in the parsed result', () => {
    expect(JSON.stringify(file).toLowerCase()).toContain('massdevice')
    expect(JSON.stringify(llz).toLowerCase()).not.toContain('massdevice')
  })
  it('filters MassDevice out of a live answer in both the sources and the steps', () => {
    const r = parseMentions({
      mentions: [],
      sources_tried: [{ name: 'MassDevice (RSS)', url: 'https://www.massdevice.com/feed/', status: 'failed: http 403', n: 0 }],
      trace: [{ step: 'Search: MassDevice (RSS)', status: 'failed: http 403', ms: 1 }],
    })!
    expect(r.sources_tried).toEqual([])
    expect(r.trace).toEqual([])
  })
  it('source list and steps agree for every source', () => {
    expect(llz).not.toBeNull()
    const steps = llz!.trace.filter((s) => s.step.startsWith('Search: '))
    expect(steps.length).toBe(llz!.sources_tried.length)
    for (const s of llz!.sources_tried) {
      const step = steps.find((t) => t.step === `Search: ${s.name}`)!
      const kind = classifyStatus(s.status).kind
      const want = { done: 'ok', failed: 'failed', not_searched: 'not_searched', unknown: 'unknown' }[kind]
      expect(step.status).toBe(want)
    }
    const failed = llz!.sources_tried.filter((s) => s.status.startsWith('failed'))
    expect(failed.map((s) => s.status)).toEqual(['failed: ConnectTimeout', 'failed: http 404'])
  })
  it('renders the zero state: failed rows say failed with the reason, steps agree, none say done', () => {
    act(() => root.render(<MentionsBox code="LLZ" apiBase={null} stored={llz} />))
    expect(host.querySelector('[data-testid=mentions-zero-line]')?.textContent).toBe(zeroLine(llz!.searched_utc))
    const rows = [...host.querySelectorAll('[data-testid=source-row]')].map((e) => e.textContent ?? '')
    expect(rows).toHaveLength(llz!.sources_tried.length)
    expect(rows.filter((r) => r.includes('failed: ConnectTimeout'))).toHaveLength(1)
    expect(rows.filter((r) => r.includes('failed: http 404'))).toHaveLength(1)
    expect(rows.filter((r) => r.includes('done'))).toHaveLength(3)
    const steps = [...host.querySelectorAll('[data-testid=trace-step]')].map((e) => e.textContent ?? '')
    const search = steps.filter((t) => t.includes('Search:'))
    expect(search.filter((t) => t.includes('failed'))).toHaveLength(2)
    expect(search.filter((t) => t.includes('done'))).toHaveLength(3)
    expect(steps.some((t) => t.includes('Fetch pages') && t.includes('unknown') && !t.includes('done'))).toBe(true)
    expect(host.textContent?.toLowerCase()).not.toContain('massdevice')
  })
  it('shows a skipped source as not searched with its reason in both places', () => {
    const r = parseMentions({
      mentions: [],
      sources_tried: [{ name: 'Example Wire', url: 'https://example.com/f', status: 'skipped: time', n: 0 }],
      trace: [{ step: 'Search: Example Wire', status: 'skipped: time', ms: 0 }],
    })!
    act(() => root.render(<MentionsBox code="LLZ" apiBase={null} stored={r} />))
    expect(host.querySelector('[data-testid=source-row]')?.textContent).toContain('not searched: time')
    const step = host.querySelector('[data-testid=trace-step]')?.textContent ?? ''
    expect(step).toContain('not searched')
    expect(step).toContain('time')
    expect(step).not.toContain('done')
  })
})
