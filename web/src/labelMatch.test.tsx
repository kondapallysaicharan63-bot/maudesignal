// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import vision from '../public/data/vision.json'
import { labelName } from './components/VisionWorkflow'
import { LabelMatches } from './components/artifacts/LabelMatches'
import { buildMatchTrace, fieldRows, fmtNumbers, fmtUtc, groupSearches, keyStats, legibilityBanner, matchSummary, rankMatches, weekChangeDates, weekChangeRules } from './labelMatch'
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
    expect(el.querySelector('[data-testid=confirmed-block]')?.textContent).toContain('You confirmed this match.')
    const facts = el.querySelector('[data-testid=match-facts]')
    expect(facts?.textContent).toContain(rankMatches(rec.matches)[0].product_code)
    expect(facts?.querySelector('a[href^="https://api.fda.gov/"]')).not.toBeNull()
    expect(el.querySelector('[data-testid=trace]')).not.toBeNull()
    expect(el.querySelector('[data-testid=match-card][data-confirmed=true] [data-testid=match-rank]')?.textContent).toContain('Confirmed')
    expect(rec.confirmed).toBeNull()
  })

  it('Undo clears the confirmation and hides the facts again', () => {
    const rec = withMatches().matches as LabelMatchRecord
    const el = mount(rec)
    click([...el.querySelectorAll('button')].filter((b) => b.textContent === 'Confirm this match')[0])
    click(el.querySelector('[data-testid=undo-confirm]') as Element)
    expect(el.querySelector('[data-testid=confirmed-note]')).toBeNull()
    expect(el.querySelector('[data-testid=match-facts]')).toBeNull()
  })

  it('"None of these" is offered and picks nothing', () => {
    const rec = withMatches().matches as LabelMatchRecord
    const el = mount(rec)
    const b = [...el.querySelectorAll('button')].find((x) => x.textContent === 'None of these') as Element
    click(b)
    expect(el.querySelector('[data-testid=none-note]')?.textContent).toContain('none of these')
    expect(el.querySelector('[data-testid=match-facts]')).toBeNull()
  })

  it('sorts cards by score and shows rank with the score out of 100', () => {
    const rec = withMatches().matches as LabelMatchRecord
    const ranked = rankMatches(rec.matches)
    for (let i = 1; i < ranked.length; i++) expect(ranked[i - 1].score).toBeGreaterThanOrEqual(ranked[i].score)
    const el = mount(rec)
    const heads = [...el.querySelectorAll('[data-testid=match-rank]')].map((x) => x.textContent ?? '')
    expect(heads[0]).toContain(`1 of ${ranked.length} · score ${ranked[0].score} of 100`)
    const shuffled = rankMatches([
      { ...ranked[0], score: 10 },
      { ...ranked[0], score: 70 },
      { ...ranked[0], score: 40 },
    ])
    expect(shuffled.map((m) => m.score)).toEqual([70, 40, 10])
  })

  it('shows the key figures with separators', () => {
    const rec = withMatches().matches as LabelMatchRecord
    const el = mount(rec)
    click([...el.querySelectorAll('button')].filter((b) => b.textContent === 'Confirm this match')[0])
    const stats = el.querySelector('[data-testid=key-stats]')?.textContent ?? ''
    expect(stats).toMatch(/Reports[\d,]+/)
    expect(stats).toContain('This week')
    expect(fmtNumbers('MAUDE holds 432413 reports; K260687 on 2026-09-30, Z-1545-2026')).toBe(
      'MAUDE holds 432,413 reports; K260687 on 2026-09-30, Z-1545-2026',
    )
    const view = Object.values(rec.device_type_views)[0]
    expect(keyStats(view).every((k) => k.value.length > 0)).toBe(true)
  })

  it('folds the openFDA searches in the trace and keeps the full step count in the toggle', () => {
    const rec = withMatches().matches as LabelMatchRecord
    const full = buildMatchTrace(rec)
    const grouped = groupSearches(full)
    expect(grouped.steps.length).toBeLessThan(full.steps.length)
    expect(grouped.steps.some((x) => x.grouped && /searches/.test(x.title))).toBe(true)
    const el = mount(rec)
    click([...el.querySelectorAll('button')].filter((b) => b.textContent === 'Confirm this match')[0])
    expect(el.querySelector('[data-testid=trace]')?.hasAttribute('open')).toBe(false)
    expect(el.querySelector('[data-testid=trace-toggle]')?.textContent).toBe(`Show ${full.steps.length} steps`)
  })

  it('formats the recording time as UTC text, never raw ISO', () => {
    expect(fmtUtc('2026-10-30T01:34:26Z')).toBe('Oct 30, 2026, 01:34 UTC')
    const el = mount(withMatches().matches)
    expect(el.querySelector('[data-testid=match-recorded-note]')?.textContent).not.toMatch(/T\d\d:\d\d:\d\dZ/)
  })

  it('shows "No match found" plainly and no confirm button', () => {
    const none = labels.find((x) => x.matches && x.matches.matches.length === 0)
    expect(none).toBeDefined()
    const el = mount(none?.matches)
    expect(el.querySelector('[data-testid=no-match]')?.textContent).toContain('No match found')
    expect(el.querySelector('[data-testid=no-match-next]')?.textContent).toContain('clearer photo')
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

describe('one status per field on an illegible label', () => {
  it('shows a single "Not legible" chip per row and no repeated mono tag', async () => {
    const { VisionTab } = await import('./components/artifacts/DossierVision')
    const idx = labels.findIndex((x) => x.image.includes('welch-module'))
    host = document.createElement('div')
    document.body.appendChild(host)
    const root = createRoot(host)
    act(() => root.render(<VisionTab vision={vision as never} initial={{ mode: 'labels', index: idx }} />))
    const rows = [...host.querySelectorAll('[data-testid=label-fields] > div')]
    expect(rows.length).toBeGreaterThan(0)
    for (const r of rows) {
      expect(r.querySelectorAll('[data-testid=field-status]').length).toBe(1)
      expect(r.textContent).toContain('Not legible')
      expect(r.querySelector('.ms-code')).toBeNull()
    }
    expect(host.textContent).not.toContain('hidden: not legible')
  })
})

describe('fix round', () => {
  it('labelName never carries a field value from an illegible reading', () => {
    const l = named('welch-module')
    expect(l.matches?.label.overall_legibility).toBe('illegible')
    const name = labelName(l)
    expect(name).toContain('(not legible)')
    const values = [...Object.values(l.fields), ...Object.values(l.matches?.label.fields ?? {})].map((f) => f.value).filter(Boolean) as string[]
    for (const v of values) expect(name).not.toContain(v)
  })

  it('labelName reads the matching run when there is one, and a clear value otherwise', () => {
    const l = named('nomad-pro2')
    const v = fieldRows(l).rows.find((r) => r.key === 'device_name')?.value
    expect(labelName(l)).toBe(v || fieldRows(l).rows.find((r) => r.key === 'model_number')?.value || 'nomad-pro2')
  })

  it('dates the this-week tile and the weekly change, and shows the stored rules', () => {
    const rec = withMatches().matches as LabelMatchRecord
    const view = Object.values(rec.device_type_views)[0]
    expect(keyStats(view).find((k) => k.label === 'This week')?.note).toMatch(/\d{4}-\d\d-\d\d to \d{4}-\d\d-\d\d/)
    expect(weekChangeDates(view)).toMatch(/Week of \d{4}-\d\d-\d\d to \d{4}-\d\d-\d\d/)
    expect(weekChangeRules(view).length).toBeGreaterThan(0)
    const el = mount(rec)
    click([...el.querySelectorAll('button')].filter((b) => b.textContent === 'Confirm this match')[0])
    expect(el.querySelector('[data-testid=week-rules]')?.textContent).toContain(weekChangeRules(view)[0])
  })

  it('formats search counts with separators', () => {
    const mk = (n: number) => ({ id: 'x', kind: 'tool', title: 'openFDA: a', detail: '', args: null, result: `${n.toLocaleString('en-US')} records`, lines: [], model: null, time: { text: '', recorded: false }, tokens: { text: '', recorded: false }, cost: { text: '', recorded: false } })
    const t = groupSearches({ steps: [mk(0), mk(432413)], beforeGate: 2, usage: { time: { text: '', recorded: false }, tokens: { text: '', recorded: false }, cost: { text: '', recorded: false } } } as never)
    expect(t.steps[0].result).toBe('0 to 432,413 records each')
  })
})

describe('current recording (02:52Z rerun) reaches the screen', () => {
  it('the illegible welch-module record carries no hidden reading and no search', () => {
    const json = JSON.stringify(named('welch-module'))
    expect(json).not.toContain('AORTIC')
    const rec = named('welch-module').matches as LabelMatchRecord
    expect((rec as unknown as { search_basis: string }).search_basis).toBe('none')
    expect(rec.note).toBe('Label not legible enough to read; nothing was searched.')
    expect(rec.trace.some((s) => s.model === 'openFDA')).toBe(false)
  })

  it('a step that ran several queries lists each query with its own count and link, never one total', () => {
    const rec = withMatches().matches as LabelMatchRecord
    const multi = rec.trace.find((s) => (s.queries?.length ?? 0) > 1)
    expect(multi).toBeTruthy()
    expect(multi?.count).toBeNull()
    const step = buildMatchTrace(rec).steps[rec.trace.indexOf(multi as NonNullable<typeof multi>)]
    expect(step.result).toMatch(/queries, each with its own count/)
    expect(step.result).not.toMatch(/^[\d,]+ records?/)
    expect(step.lines.length).toBe(multi?.queries?.length)
    expect(step.lines.some((l) => /\(sum of the groups returned\)/.test(l))).toBe(true)
    expect(step.lineUrls?.every((u) => u?.startsWith('https://api.fda.gov/'))).toBe(true)
  })

  it('folded searches keep every per-query line and link, and invent no combined count', () => {
    const rec = withMatches().matches as LabelMatchRecord
    const grouped = groupSearches(buildMatchTrace(rec))
    const g = grouped.steps.find((s) => s.grouped)
    expect(g).toBeTruthy()
    expect(g?.lines.some((l) => /sum of the groups returned/.test(l))).toBe(true)
    expect(g?.lineUrls?.length).toBe(g?.lines.length)
    expect(g?.lines.join('\n')).not.toMatch(/432,413/)
  })

  it('a hand-made step with count null and queries[] using groups_sum', () => {
    const rec = withMatches().matches as LabelMatchRecord
    const t = buildMatchTrace({
      ...rec,
      trace: [
        {
          step: 'openFDA search: MAUDE counts for ZZZ',
          model: 'openFDA',
          elapsed_ms: 100,
          timing: 'measured',
          count: null,
          url: null,
          queries: [
            { query: 'This week, by event type', url: 'https://api.fda.gov/a', count: null, groups_sum: 196 },
            { query: 'Everything before this week', url: 'https://api.fda.gov/b', count: 432217 },
          ],
        },
      ],
    })
    expect(t.steps[0].lines).toEqual([
      'This week, by event type: 196 (sum of the groups returned)',
      'Everything before this week: 432,217 records',
    ])
    expect(t.steps[0].lineUrls).toEqual(['https://api.fda.gov/a', 'https://api.fda.gov/b'])
  })
})

describe('carried-over timings keep their label', () => {
  it('shows the stored timing label when the time was not measured in this run', () => {
    const t = buildMatchTrace({
      ...(withMatches().matches as LabelMatchRecord),
      trace: [
        { step: 'SAM 3.1 crop', model: 'SAM 3.1', elapsed_ms: 832.2, timing: 'recorded 2026-10-30', note: 'x' },
        { step: 'openFDA search: a', model: 'openFDA', elapsed_ms: 340.6, timing: 'measured', count: 3 },
      ],
    })
    expect(t.steps[0].time.text).toBe('832 ms, recorded 2026-10-30')
    expect(t.steps[1].time.text).toBe('341 ms')
  })
})
