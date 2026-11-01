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
import { compute, EMPTY, parseMeasurements, recordedMeans, TASKS, type Measurement } from './roi'
import { formatRoute, parseRoute, routeName } from './router'
import { pageItems } from './SearchPalette'

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
const BANNED_WORDS = [/FDA-approved/i, /\bvalidated\b/i, /\bunsafe\b/i, /\bsafe\b/i, /draft CAPA/i, /connector approved/i, /MaudeSignal determined/i, /claims only what exists/i]

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
const fill = (v: Record<string, string>) => Object.entries(v).forEach(([k, x]) => type(`roi-in-${k}`, x))

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
  it('vercel.json rewrites both addresses, bare and with a path, to the app', () => {
    const v = JSON.parse(readFileSync(here('../../vercel.json'), 'utf8')) as { rewrites: { source: string; destination: string }[] }
    for (const s of ['/pms-workflow', '/pms-workflow/:path*', '/roi', '/roi/:path*']) expect(v.rewrites.some((r) => r.source === s && r.destination === '/index.html')).toBe(true)
  })
  it('both pages are in Ctrl K search', () => {
    const t = pageItems([]).map((x) => x.title)
    expect(t).toContain('How MaudeSignal fits your PMS workflow')
    expect(t).toContain('Time and cost: measured, not claimed')
  })
})

describe('Home', () => {
  it('shows the headline once, quietly, and links to both pages with a New chip', () => {
    const calls: string[] = []
    render(
      <HomeV2 data={DATA} onAlert={() => undefined} onViewAll={() => undefined} onDevices={() => undefined} onAudit={() => undefined} onPms={() => calls.push('pms')} onRoi={() => calls.push('roi')} />,
    )
    expect(host.querySelector('[data-testid="home-headline"]')!.textContent).toBe(HEADLINE)
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="home-pms-link"]')!.click())
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="home-roi-link"]')!.click())
    expect(calls).toEqual(['pms', 'roi'])
    expect(host.querySelectorAll('[data-testid="home-fit"] .ms2-tag')).toHaveLength(2)
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
    expect(STEPS.map((s) => s.title)).toEqual(['Complaint received', 'Investigation', 'FDA search', 'Trend review', 'PMS board', 'Decision', 'PSUR / PMSR', 'Audit'])
    for (const li of items) {
      const heads = [...li.querySelectorAll('h3')].map((h) => h.textContent)
      expect(heads).toEqual(['Manual today', 'What MaudeSignal does', 'What stays human', 'Related clauses'])
      for (const g of li.querySelectorAll('[role="group"]')) expect(g.getAttribute('aria-labelledby')).toBeTruthy()
      expect(li.querySelector('[data-testid^="pms-kind-"]')!.textContent).toMatch(/^(MaudeSignal helps|Stays human)$/)
      expect(li.querySelector('.ms2-step-f--human')!.textContent).toContain('You decide:')
    }
  })
  it('the summary counts are computed from the steps', () => {
    render(<PmsWorkflow />)
    const helped = STEPS.filter((s) => s.kind === 'assist').length
    expect(host.querySelector('[data-testid="pms-summary"]')!.textContent).toBe(`8 steps · ${helped} where MaudeSignal helps · ${8 - helped} stay human`)
  })
  it('the strip links to the step cards', () => {
    render(<PmsWorkflow />)
    const links = [...host.querySelectorAll('[data-testid="pms-overview"] a')]
    expect(links.map((a) => a.getAttribute('href'))).toEqual(STEPS.map((_, i) => `#step-${i + 1}`))
    for (let i = 1; i <= 8; i++) expect(host.querySelector(`#step-${i}`)).not.toBeNull()
    expect(host.querySelector('[data-testid="pms-overview"]')!.getAttribute('aria-label')).toBe('The eight steps')
  })
  it('marks new features as new, links the investigation, and says the decision stays human', () => {
    render(<PmsWorkflow onHome={() => undefined} />)
    const text = host.textContent ?? ''
    expect(text).toContain('Investigate a complaint (new)')
    expect(text).toContain('product code')
    expect(host.querySelector<HTMLAnchorElement>('[data-testid="pms-investigate-link"]')!.getAttribute('href')).toMatch(/\/investigate(\?|$)/)
    expect(host.querySelector('[data-testid="pms-tag-investigation"]')!.textContent).toBe('New')
    // "New, simulated" sits on the F22 sentence only, not on the card title
    expect(host.querySelector('[data-testid="pms-tag-decision"]')!.textContent).toBe('New, simulated')
    expect(host.querySelector('[data-testid="pms-step-decision"] .ms2-step-head [data-testid="pms-tag-decision"]')).toBeNull()
    expect(host.querySelector('[data-testid="pms-step-decision"]')!.textContent).toContain(HUMAN_ONLY)
    expect(text).toContain('proactive extra')
    expect(host.querySelector('[data-testid="crumb-home"]')).not.toBeNull()
  })
  it('lists the requested clauses', () => {
    render(<PmsWorkflow />)
    const t = host.textContent ?? ''
    for (const c of ['§8.2.1', '§8.2.2', '§8.2.3', '§8.5.2', '21 CFR 820', '21 CFR 803', '21 CFR 806', '21 CFR 7, Subpart C', 'ISO 14971']) expect(t).toContain(c)
    expect(host.querySelector('[data-testid="pms-step-search"]')!.textContent).not.toContain('21 CFR 803')
    expect(host.querySelector('[data-testid="pms-step-decision"]')!.textContent).toContain('21 CFR 803')
  })
  it('has none of the banned words and no figure beyond the computed counts', () => {
    render(<PmsWorkflow />)
    const t = (host.textContent ?? '').replace(host.querySelector('[data-testid="pms-summary"]')!.textContent ?? '', '')
    expect(t).not.toMatch(CLAIM)
    for (const re of BANNED_WORDS) expect(t).not.toMatch(re)
  })
})

describe('Time and cost (empty measurements)', () => {
  it('shows one Pending chip and "Measurement pending" for each of the three tasks, with no time or cost claim', () => {
    render(<RoiPage measurements={[]} />)
    expect(host.querySelectorAll('[data-testid="roi-pending-chip"]')).toHaveLength(1)
    expect(host.querySelectorAll('table')).toHaveLength(0)
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
    expect(inputs).toHaveLength(7)
    for (const i of inputs) {
      expect(i.value).toBe('')
      expect(i.placeholder).toBe('enter yours')
      expect(i.maxLength).toBe(12)
      expect(i.closest('label')!.textContent!.trim().length).toBeGreaterThan(3)
    }
    const b = host.querySelector<HTMLButtonElement>('[data-testid="roi-use-recorded"]')!
    expect(b.disabled).toBe(true)
    expect(b.getAttribute('aria-disabled')).toBe('true')
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
    fill({ complaints: '10', complaintManual: '60' })
    expect(host.querySelector('[data-testid="roi-result-label"]')).toBeNull()
    fill({ complaintTool: '30' })
    expect(host.querySelector('[data-testid="roi-result-label"]')!.textContent).toBe('from your assumptions')
    expect(host.querySelector('[data-testid="roi-result"]')!.textContent).toContain('Difference, hours per month')
    expect(host.querySelector('[data-testid="roi-result"]')!.textContent).not.toContain('cost per month')
    fill({ hourly: '50' })
    expect(host.querySelector('[data-testid="roi-result"]')!.textContent).toContain('cost per month')
  })
  it('when MaudeSignal was slower the label says manual minus MaudeSignal and a line says so', () => {
    render(<RoiPage measurements={[]} />)
    fill({ complaints: '2', complaintManual: '10', complaintTool: '30' })
    expect(host.querySelector('[data-testid="roi-result"]')!.textContent).toContain('Manual minus MaudeSignal (hours per month)')
    expect(host.querySelector('[data-testid="roi-result-slower"]')).not.toBeNull()
  })
  it('accepts digits with one decimal part only; "Infinity" and "1e999" give no result', () => {
    render(<RoiPage measurements={[]} />)
    fill({ complaints: 'Infinity', complaintManual: '1e999', complaintTool: '5' })
    expect(host.querySelector('[data-testid="roi-result-label"]')).toBeNull()
    expect(host.querySelector('[data-testid="roi-in-complaints"]')!.getAttribute('aria-invalid')).toBe('true')
    expect(compute({ ...EMPTY, complaints: '1', complaintManual: '-5', complaintTool: '1' })).toBeNull()
    expect(compute({ ...EMPTY, complaints: '1', complaintManual: '5.', complaintTool: '1' })).toBeNull()
    expect(compute({ ...EMPTY, complaints: '9'.repeat(400), complaintManual: '9', complaintTool: '1' })).toBeNull()
  })
  it('keeps the inputs in localStorage only, and survives a storage that throws', () => {
    render(<RoiPage measurements={[]} />)
    fill({ complaints: '7' })
    expect(localStorage.getItem('ms-roi-assumptions')).toContain('"complaints":"7"')
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(() => fill({ trends: '2' })).not.toThrow()
    spy.mockRestore()
  })
  it('compute needs one task with its count and both minutes', () => {
    expect(compute(EMPTY)).toBeNull()
    expect(compute({ ...EMPTY, complaints: '1', complaintManual: '60' })).toBeNull()
    expect(compute({ ...EMPTY, complaints: '2', complaintManual: '60', complaintTool: '30' })!.hoursDiff).toBe(1)
    expect(compute({ ...EMPTY, complaints: '2', complaintManual: '60', complaintTool: '30', hourly: '10' })!.cost).toBe(10)
    expect(compute({ ...EMPTY, trends: '2', trendManual: '60', trendTool: '30', complaints: '2', complaintManual: '60', complaintTool: '30' })!.hoursDiff).toBe(2)
  })
})

describe('Time and cost (with recorded measurements)', () => {
  const REC2: Measurement = { ...REC, id: 'm2', task: 'weekly-trend', manual_minutes: 20, maudesignal_minutes: 30 }
  it('shows who, when, how and the minutes as stacked label-value pairs, and flags a slower recording', () => {
    render(<RoiPage measurements={[REC, REC2]} />)
    const card = host.querySelector('[data-testid="roi-task-similar-events"]')!
    for (const t of ['Test person', '2026-01-02', 'Stopwatch on a sample complaint', '40']) expect(card.textContent).toContain(t)
    expect(host.querySelector('[data-testid="roi-pending-similar-events"]')).toBeNull()
    expect(host.querySelector('[data-testid="roi-pending-evidence-section"]')).not.toBeNull()
    expect(host.querySelector('[data-testid="roi-pending-chip"]')).toBeNull()
    expect(card.querySelector('[data-testid="roi-slower"]')).toBeNull()
    expect(host.querySelector('[data-testid="roi-task-weekly-trend"] [data-testid="roi-slower"]')).not.toBeNull()
  })
  it('the button fills each task’s own minutes and the source survives a reload', () => {
    render(<RoiPage measurements={[REC, REC2]} />)
    const btn = host.querySelector<HTMLButtonElement>('[data-testid="roi-use-recorded"]')!
    expect(btn.disabled).toBe(false)
    act(() => btn.click())
    const v = (k: string) => host.querySelector<HTMLInputElement>(`[data-testid="roi-in-${k}"]`)!.value
    expect([v('complaintManual'), v('complaintTool'), v('trendManual'), v('trendTool')]).toEqual(['40', '10', '20', '30'])
    fill({ complaints: '3', trends: '1' })
    act(() => host.querySelector<HTMLButtonElement>('[data-testid="roi-use-recorded"]')!.click())
    expect(host.querySelector('[data-testid="roi-result-label"]')!.textContent).toMatch(/^Minutes from recorded measurements/)
    act(() => root.unmount())
    root = createRoot(host)
    render(<RoiPage measurements={[REC, REC2]} />)
    expect(host.querySelector('[data-testid="roi-result-label"]')!.textContent).toMatch(/^Minutes from recorded measurements/)
  })
  it('an entry for another task ("psur", or the evidence section) does not enable the button', () => {
    const psur: Measurement = { ...REC, id: 'p', task: 'psur' }
    expect(recordedMeans([psur])).toBeNull()
    expect(recordedMeans([{ ...REC, id: 'e', task: 'evidence-section' }])).toBeNull()
    render(<RoiPage measurements={[psur]} />)
    expect(host.querySelector<HTMLButtonElement>('[data-testid="roi-use-recorded"]')!.disabled).toBe(true)
  })
  it('drops an entry without who, when or how, or with minutes outside 0 to 10000', () => {
    const bad = [{ ...REC, who: '' }, { ...REC, how: ' ' }, { ...REC, when: '' }, { ...REC, manual_minutes: 'x' }, { ...REC, manual_minutes: 0 }, { ...REC, maudesignal_minutes: 10001 }]
    expect(parseMeasurements({ schema: 1, measurements: bad })).toEqual([])
    expect(parseMeasurements({ schema: 1, measurements: [REC] })).toHaveLength(1)
  })
})
