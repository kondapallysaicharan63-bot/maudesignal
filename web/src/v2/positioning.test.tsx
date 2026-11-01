// @vitest-environment jsdom
// F26 (PMS workflow map), F27 (time and cost) and the headline: render, labels, honesty rules, banned words.
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import alerts from '../../public/data/alerts.json'
import briefs from '../../public/data/briefs.json'
import company from '../../public/data/company.json'
import manifest from '../../public/data/manifest.json'
import measurementsFile from '../../public/data/measurements.json'
import sweep from '../../public/data/sweep.json'
import { parseAlerts } from '../alerts'
import { isV2Path, V2_SEGMENTS } from '../layoutFlag'
import { HEADLINE } from '../positioning'
import type { WorkspaceData } from '../types'
import { HomeV2 } from './HomeV2'
import { HUMAN_ONLY, PmsWorkflow, STEPS } from './PmsWorkflow'
import { RoiPage } from './RoiPage'
import { compute, parseMeasurements, TASKS, type Measurement } from './roi'
import { formatRoute, parseRoute, routeName } from './router'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const here = (p: string) => resolve(__dirname, p)
const DATA = { alerts: parseAlerts(alerts), briefs: briefs.briefs, company, sweep, manifest } as unknown as WorkspaceData

let host: HTMLDivElement
let root: Root
beforeEach(() => {
  try {
    localStorage.clear()
  } catch {
    // jsdom without storage
  }
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})
afterEach(() => {
  act(() => root.unmount())
  host.remove()
})
const render = (el: JSX.Element) => act(() => root.render(el))

/** A time, percentage or money claim: a number followed by a unit. ("12 months" and "4 weeks" are task names, not claims.) */
const CLAIM = /\d[\d.,]*\s*(%|x\b|h\b|hrs?\b|hours?\b|min\b|mins\b|minutes?\b|seconds?\b|usd\b)|[$€£]\s*\d/i
const BANNED_PHRASES = ['hours saved', '% faster', 'x faster', 'saves ', 'ROI of']
const BANNED_WORDS = [/FDA-approved/i, /\bvalidated\b/i, /\bunsafe\b/i, /\bsafe\b/i, /draft CAPA/i, /connector approved/i, /MaudeSignal determined/i]

const REC: Measurement = {
  id: 'm1',
  task: 'similar-events',
  who: 'Test person',
  when: '2026-01-02',
  how: 'Stopwatch on a sample complaint',
  manual_minutes: 40,
  maudesignal_minutes: 10,
  notes: '',
}

function type(testid: string, value: string) {
  const el = host.querySelector<HTMLInputElement>(`[data-testid="${testid}"]`)!
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  act(() => {
    set.call(el, value)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

describe('routes', () => {
  it('both pages round-trip and are v2-only addresses', () => {
    expect(formatRoute({ page: 'pms' })).toBe('pms-workflow')
    expect(formatRoute({ page: 'roi' })).toBe('roi')
    expect(parseRoute('/pms-workflow')).toEqual({ page: 'pms' })
    expect(parseRoute('/app/roi')).toEqual({ page: 'roi' })
    expect(routeName({ page: 'pms' })).toBe('pms-workflow')
    expect(isV2Path('/pms-workflow')).toBe(true)
    expect(isV2Path('/roi')).toBe(true)
    expect(V2_SEGMENTS).toContain('pms-workflow')
  })
  it('vercel.json rewrites both addresses to the app', () => {
    const v = JSON.parse(readFileSync(here('../../vercel.json'), 'utf8')) as { rewrites: { source: string; destination: string }[] }
    for (const s of ['/pms-workflow', '/roi']) expect(v.rewrites.some((r) => r.source === s && r.destination === '/index.html')).toBe(true)
  })
})

describe('Home', () => {
  it('shows the headline once, quietly, and links to both pages', () => {
    const calls: string[] = []
    render(
      <HomeV2 data={DATA} onAlert={() => undefined} onViewAll={() => undefined} onDevices={() => undefined} onAudit={() => undefined} onPms={() => calls.push('pms')} onRoi={() => calls.push('roi')} />,
    )
    expect(host.querySelector('[data-testid="home-headline"]')!.textContent).toBe(HEADLINE)
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="home-pms-link"]')!.click())
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="home-roi-link"]')!.click())
    expect(calls).toEqual(['pms', 'roi'])
    expect(host.textContent).toContain('How MaudeSignal fits your PMS workflow')
    expect(host.textContent).toContain('Time and cost: measured, not claimed')
  })
})

describe('PMS workflow map', () => {
  it('has the eight steps in order, each with the four labelled fields', () => {
    render(<PmsWorkflow />)
    expect(host.querySelector('h1')!.textContent).toBe('How MaudeSignal fits your PMS workflow')
    const items = [...host.querySelectorAll('[data-testid="pms-steps"] > li')]
    expect(items).toHaveLength(8)
    expect(STEPS.map((s) => s.title)).toEqual([
      'Complaint received',
      'Investigation',
      'Manual MAUDE / recall / 510(k) search',
      'Trend review',
      'PMS board',
      'Decision: note to file / CAPA / escalation',
      'PSUR / PMSR, management review',
      'Audit',
    ])
    for (const li of items) {
      const heads = [...li.querySelectorAll('h3')].map((h) => h.textContent)
      expect(heads).toEqual(['Manual today', 'What MaudeSignal does', 'What stays human', 'Clauses it serves'])
      for (const g of li.querySelectorAll('[role="group"]')) expect(g.getAttribute('aria-labelledby')).toBeTruthy()
    }
  })
  it('marks new features as new and says the decision stays human', () => {
    render(<PmsWorkflow />)
    const text = host.textContent ?? ''
    expect(text).toContain('Investigate a complaint (F25)')
    expect(host.querySelector('[data-testid="pms-tag-investigation"]')!.textContent).toBe('New')
    expect(host.querySelector('[data-testid="pms-tag-decision"]')!.textContent).toBe('New, simulated')
    expect(host.querySelector('[data-testid="pms-step-decision"]')!.textContent).toContain(HUMAN_ONLY)
    expect(text).toContain('proactive extra')
  })
  it('lists the requested clauses', () => {
    render(<PmsWorkflow />)
    const t = host.textContent ?? ''
    for (const c of ['§8.2.1', '§8.2.2', '§8.2.3', '§8.5.2', '21 CFR 820', '21 CFR 803', '21 CFR 806', '21 CFR 7 ', 'ISO 14971']) expect(t).toContain(c)
  })
  it('has no figures and none of the banned words', () => {
    render(<PmsWorkflow />)
    const t = host.textContent ?? ''
    expect(t).not.toMatch(CLAIM)
    for (const re of BANNED_WORDS) expect(t).not.toMatch(re)
  })
  it('the overview strip is labelled for screen readers', () => {
    render(<PmsWorkflow />)
    expect(host.querySelector('svg')!.getAttribute('aria-label')).toMatch(/eight steps/)
  })
})

describe('Time and cost (empty measurements)', () => {
  it('shows "Measurement pending" for each of the three tasks and no time or cost claim', () => {
    render(<RoiPage measurements={[]} />)
    for (const t of TASKS) expect(host.querySelector(`[data-testid="roi-pending-${t.id}"]`)!.textContent).toBe('Measurement pending')
    const text = host.textContent ?? ''
    expect(text).not.toMatch(CLAIM)
    expect(text).toContain('Your assumptions — not a claim')
    expect(text).toContain('Timing tests by whoever runs them, to be recorded')
    for (const re of BANNED_WORDS) expect(text).not.toMatch(re)
    expect(host.querySelector('[data-testid="roi-result-label"]')).toBeNull()
  })
  it('inputs are empty, labelled, say "enter yours", and the recorded button is disabled', () => {
    render(<RoiPage measurements={[]} />)
    const inputs = [...host.querySelectorAll<HTMLInputElement>('input')]
    expect(inputs).toHaveLength(5)
    for (const i of inputs) {
      expect(i.value).toBe('')
      expect(i.placeholder).toBe('enter yours')
      expect(i.closest('label')!.textContent!.trim().length).toBeGreaterThan(3)
    }
    expect(host.querySelector<HTMLButtonElement>('[data-testid="roi-use-recorded"]')!.disabled).toBe(true)
  })
  it('the shipped measurements.json is empty and parses to nothing', () => {
    expect(measurementsFile).toEqual({ schema: 1, measurements: [] })
    expect(parseMeasurements(measurementsFile)).toEqual([])
  })
  it('the page source has none of the banned phrases', () => {
    for (const f of ['RoiPage.tsx', 'roi.ts', 'PmsWorkflow.tsx', 'HomeV2.tsx', '../positioning.ts']) {
      const src = readFileSync(here(f), 'utf8')
      for (const p of BANNED_PHRASES) expect(src.includes(p), `${f} contains "${p}"`).toBe(false)
    }
  })
})

describe('Time and cost (calculator)', () => {
  it('results appear only from typed values and are labelled as the person’s assumptions', () => {
    render(<RoiPage measurements={[]} />)
    type('roi-in-complaints', '10')
    type('roi-in-manual', '60')
    expect(host.querySelector('[data-testid="roi-result-label"]')).toBeNull()
    type('roi-in-tool', '30')
    expect(host.querySelector('[data-testid="roi-result-label"]')!.textContent).toBe('from your assumptions')
    expect(host.querySelector('[data-testid="roi-result"]')!.textContent).toContain('Difference, hours per month')
    expect(host.querySelector('[data-testid="roi-result"]')!.textContent).not.toContain('cost per month')
    type('roi-in-hourly', '50')
    expect(host.querySelector('[data-testid="roi-result"]')!.textContent).toContain('cost per month')
  })
  it('keeps the inputs in localStorage only, and survives a storage that throws', () => {
    render(<RoiPage measurements={[]} />)
    type('roi-in-complaints', '7')
    expect(localStorage.getItem('ms-roi-assumptions')).toContain('"complaints":"7"')
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(() => type('roi-in-trends', '2')).not.toThrow()
    spy.mockRestore()
  })
  it('compute needs minutes for both and one monthly count', () => {
    expect(compute({ complaints: '', trends: '', hourly: '', manual: '', tool: '' })).toBeNull()
    expect(compute({ complaints: '1', trends: '', hourly: '', manual: '60', tool: '' })).toBeNull()
    expect(compute({ complaints: '2', trends: '', hourly: '', manual: '60', tool: '30' })!.hoursDiff).toBe(1)
    expect(compute({ complaints: '2', trends: '', hourly: '10', manual: '60', tool: '30' })!.cost).toBe(10)
  })
})

describe('Time and cost (with a recorded measurement)', () => {
  it('shows the minutes with who, when and how, and the button fills the calculator', () => {
    render(<RoiPage measurements={[REC]} />)
    const card = host.querySelector('[data-testid="roi-task-similar-events"]')!
    expect(card.textContent).toContain('Test person')
    expect(card.textContent).toContain('2026-01-02')
    expect(card.textContent).toContain('Stopwatch on a sample complaint')
    expect(card.textContent).toContain('40')
    expect(host.querySelector('[data-testid="roi-pending-similar-events"]')).toBeNull()
    expect(host.querySelector('[data-testid="roi-pending-weekly-trend"]')).not.toBeNull()
    const btn = host.querySelector<HTMLButtonElement>('[data-testid="roi-use-recorded"]')!
    expect(btn.disabled).toBe(false)
    act(() => btn.click())
    expect(host.querySelector<HTMLInputElement>('[data-testid="roi-in-manual"]')!.value).toBe('40')
    expect(host.querySelector<HTMLInputElement>('[data-testid="roi-in-tool"]')!.value).toBe('10')
  })
  it('drops an entry without who, when or how', () => {
    expect(parseMeasurements({ schema: 1, measurements: [{ ...REC, who: '' }, { ...REC, how: ' ' }, { ...REC, when: '' }, { ...REC, manual_minutes: 'x' }] })).toEqual([])
    expect(parseMeasurements({ schema: 1, measurements: [REC] })).toHaveLength(1)
  })
})
