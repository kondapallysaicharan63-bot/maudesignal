// @vitest-environment jsdom
// The live label result in jsdom: a failed openFDA search shows the server's note, not "No match found".
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { LiveLabelResult } from '../components/CameraPanel'
import { parseLabelResponse } from './api'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const body = (matches: Record<string, unknown>, reading: Record<string, unknown> = {}) => ({
  mode: 'live',
  not_medical_advice: true,
  trace: [{ step: 'openFDA search for possible matches', model: null, ms: 900, status: 'failed', note: '2 openFDA search(es), 2 failed' }],
  cost_usd: 0.12,
  limits: { remaining_today: 4, resets_utc: '2026-11-01T00:00:00Z' },
  reading: {
    legibility: 'partly_legible',
    fields: {
      device_name: { value: 'Stub device', legibility: 'clear' },
      manufacturer: { value: '', legibility: 'illegible' },
      model: { value: '', legibility: '' },
      k_number: { value: '', legibility: '' },
      udi: { value: '', legibility: '' },
      gtin: { value: '', legibility: '' },
    },
    values_withheld: ['lot', 'serial'],
    ...reading,
  },
  matches,
  confirmed: null,
})

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
const show = (b: unknown) => {
  const r = parseLabelResponse(b)
  expect(r).not.toBeNull()
  act(() => root.render(<LiveLabelResult res={r!} />))
}
const q = (id: string) => host.querySelector(`[data-testid=${id}]`)

describe('LiveLabelResult', () => {
  it('search_failed shows the note and a retry hint, not "No match found", and no candidates', () => {
    show(body({ status: 'no_match_found', candidates: [], search_failed: true, note: 'openFDA could not be searched, so there is no match result for this photo.' }))
    expect(q('search-failed-note')?.textContent).toBe('openFDA could not be searched, so there is no match result for this photo.')
    expect(q('search-failed-retry')?.textContent).toMatch(/try again/i)
    expect(q('no-match')).toBeNull()
    expect(host.textContent).not.toContain('No match found')
    expect(host.querySelectorAll('[data-testid=match-card]')).toHaveLength(0)
    expect(q('none-row')).toBeNull()
  })
  it('a note alone (no flag) is shown too', () => {
    show(body({ status: 'no_match_found', candidates: [], note: 'openFDA could not be searched ...' }))
    expect(q('search-failed-note')?.textContent).toContain('could not be searched')
    expect(q('no-match')).toBeNull()
  })
  it('a search that ran and found nothing still says "No match found"', () => {
    show(body({ status: 'no_match_found', candidates: [] }))
    expect(q('no-match')?.textContent).toContain('No match found')
    expect(q('search-failed')).toBeNull()
  })
  it('lot and serial are named as never shown, and empty values read "not read"', () => {
    show(body({ status: 'no_match_found', candidates: [] }))
    expect(q('lot-serial-note')?.textContent).toMatch(/never shown or kept/)
    expect(q('reading-fields')?.textContent).toContain('not read')
  })
})
