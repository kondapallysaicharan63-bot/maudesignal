// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import vision from '../public/data/vision.json'
import { LabelMatches } from './components/artifacts/LabelMatches'
import { buildMatchTrace, fieldRows, legibilityBanner, matchSummary } from './labelMatch'
import { NOT_RECORDED } from './trace'
import type { LabelMatchRecord, LabelReading } from './types'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const labels = vision.labels as unknown as LabelReading[]
const named = (needle: string): LabelReading => {
  const l = labels.find((x) => x.image.includes(needle))
  if (!l) throw new Error(`no label ${needle}`)
  return l
}
const withMatches = (): LabelReading => {
  const l = labels.find((x) => (x.matches?.matches.length ?? 0) > 0)
  if (!l) throw new Error('no label with matches')
  return l
}

let host: HTMLDivElement | null = null
afterEach(() => {
  host?.remove()
  host = null
})

function mount(rec: LabelMatchRecord | null | undefined): HTMLDivElement {
  host = document.createElement('div')
  document.body.appendChild(host)
  const root = createRoot(host)
  act(() => root.render(<LabelMatches rec={rec} />))
  return host
}

const click = (el: Element) =>
  act(() => {
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })

describe('possible matches are never auto-confirmed', () => {
  it('shows every card with a confirm button and no facts, trace or confirmation until a click', () => {
    const rec = withMatches().matches as LabelMatchRecord
    const el = mount(rec)
    const cards = el.querySelectorAll('[data-testid=match-card]')
    expect(cards.length).toBe(Math.min(3, rec.matches.length))
    expect([...el.querySelectorAll('button')].filter((b) => b.textContent === 'Confirm this match').length).toBe(cards.length)
    expect(el.querySelector('[data-testid=confirmed-note]')).toBeNull()
    expect(el.querySelector('[data-testid=match-facts]')).toBeNull()
    expect(el.querySelector('[data-testid=trace]')).toBeNull()
    expect(rec.confirmed).toBeNull()
  })

  it('a click confirms only that card, locally, then shows its device-type facts and the step trace', () => {
    const rec = withMatches().matches as LabelMatchRecord
    const el = mount(rec)
    const buttons = [...el.querySelectorAll('button')].filter((b) => b.textContent === 'Confirm this match')
    click(buttons[0])
    expect(el.querySelectorAll('[data-testid=confirmed-note]').length).toBe(1)
    expect(el.querySelector('[data-testid=confirmed-note]')?.textContent).toBe('Confirmed by you in this browser; not saved.')
    const facts = el.querySelector('[data-testid=match-facts]')
    expect(facts?.textContent).toContain(rec.matches[0].product_code)
    expect(facts?.querySelector('a[href^="https://api.fda.gov/"]')).not.toBeNull()
    expect(el.querySelector('[data-testid=trace]')).not.toBeNull()
    expect(rec.confirmed).toBeNull()
  })

  it('shows "No match found" plainly and no confirm button', () => {
    const none = labels.find((x) => x.matches && x.matches.matches.length === 0)
    expect(none).toBeDefined()
    const el = mount(none?.matches)
    expect(el.querySelector('[data-testid=no-match]')?.textContent).toContain('No match found')
    expect(el.querySelectorAll('button').length).toBe(0)
  })

  it('says so when no matching run was recorded', () => {
    expect(mount(null).textContent).toContain('No matching run was recorded')
  })

  it('carries the recorded-data note', () => {
    expect(mount(withMatches().matches).querySelector('[data-testid=match-recorded-note]')?.textContent).toMatch(/Recorded data/)
  })
})

describe('why it matched and what did not', () => {
  it('shows the stored mismatch reasons, e.g. "applicant differs"', () => {
    const rec = named('nomad-pro2').matches as LabelMatchRecord
    const el = mount(rec)
    const not = [...el.querySelectorAll('[data-testid=why-not-matched] li')].map((li) => li.textContent)
    expect(not.some((t) => t?.startsWith('applicant differs'))).toBe(true)
    const why = [...el.querySelectorAll('[data-testid=why-matched] li')].map((li) => li.textContent)
    expect(why.length).toBeGreaterThan(0)
    for (const m of rec.matches) {
      for (const r of m.why_not_matched) expect(el.textContent).toContain(r)
    }
  })
})

describe('legibility', () => {
  it('has a banner unless the reading is clear', () => {
    expect(legibilityBanner('clear')).toBeNull()
    expect(legibilityBanner('partly_legible')).toMatch(/partly legible/)
    expect(legibilityBanner('illegible')).toMatch(/could not be read/)
  })

  it('hides every field value when the overall reading is illegible', () => {
    const base = named('nomad-pro2')
    const l: LabelReading = {
      ...base,
      matches: {
        ...(base.matches as LabelMatchRecord),
        label: {
          overall_legibility: 'illegible',
          fields: { device_name: { value: 'SECRET NAME', legibility: 'partly_legible' }, model_number: { value: 'M-1', legibility: 'clear' } },
        },
      },
    }
    const { rows, overall } = fieldRows(l)
    expect(overall).toBe('illegible')
    expect(rows.every((r) => r.value === null && r.hidden)).toBe(true)
    expect(JSON.stringify(rows)).not.toContain('SECRET NAME')
  })

  it('hides a single illegible field but keeps a clear one', () => {
    const l = named('welch-module')
    const rows = fieldRows({
      ...l,
      matches: {
        ...(l.matches as LabelMatchRecord),
        label: {
          overall_legibility: 'partly_legible',
          fields: { manufacturer: { value: 'Acme', legibility: 'illegible' }, model_number: { value: 'X-9', legibility: 'clear' } },
        },
      },
    }).rows
    expect(rows.find((r) => r.key === 'manufacturer')?.value).toBeNull()
    expect(rows.find((r) => r.key === 'model_number')?.value).toBe('X-9')
  })

  it('the stored welch-module reading is illegible, so its values are hidden', () => {
    const { rows, overall } = fieldRows(named('welch-module'))
    expect(overall).toBe('illegible')
    expect(rows.every((r) => r.value === null)).toBe(true)
  })
})

describe('timings are never invented', () => {
  it('uses only stored times and costs and says "not recorded" for the rest', () => {
    const rec = withMatches().matches as LabelMatchRecord
    const t = buildMatchTrace(rec)
    expect(t.steps.length).toBe(rec.trace.length)
    rec.trace.forEach((s, i) => {
      const step = t.steps[i]
      expect(step.time.recorded).toBe(typeof s.elapsed_ms === 'number')
      expect(step.cost.recorded).toBe(typeof s.cost_usd === 'number')
    })
    expect(t.steps.map((s) => s.kind).slice(0, 2)).toEqual(['sam', 'read'])
    expect(t.steps.at(-1)?.kind).toBe('done')
  })

  it('a run recorded without timings shows "not recorded", never a number', () => {
    const rec = withMatches().matches as LabelMatchRecord
    const stripped: LabelMatchRecord = {
      ...rec,
      reading: undefined,
      trace: rec.trace.map((s) => ({ step: s.step, model: s.model, elapsed_ms: null, timing: 'not recorded' })),
    }
    const t = buildMatchTrace(stripped)
    expect(t.steps.every((s) => !s.time.recorded && !s.cost.recorded && !s.tokens.recorded)).toBe(true)
    expect(t.usage.time.text).toBe(NOT_RECORDED)
    expect(t.usage.cost.text).toBe(NOT_RECORDED)
    const el = mount(stripped)
    click([...el.querySelectorAll('button')].filter((b) => b.textContent === 'Confirm this match')[0])
    const text = el.querySelector('[data-testid=trace]')?.textContent ?? ''
    expect(text).toContain(`time: ${NOT_RECORDED}`)
    expect(text).not.toMatch(/\d+(\.\d)? (s|ms)\b/)
  })

  it('the summary line counts only what is stored', () => {
    expect(matchSummary({ ...named('nomad-pro2'), matches: null })).toBe('no matching run recorded')
    expect(matchSummary(named('welch-module'))).toBe('no match found')
    expect(matchSummary(named('nomad-pro2'))).toBe('3 possible matches to confirm')
  })
})
