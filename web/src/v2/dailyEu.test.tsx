// @vitest-environment jsdom
// Morning brief (/daily) and EU MDR workflow relevance (/eu): real stored data only, every number linked to openFDA,
// no model call, the disclaimer and banners present; the EU page claims no EU data.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import alertsFile from '../../public/data/alerts.json'
import briefsFile from '../../public/data/briefs.json'
import manifest from '../../public/data/manifest.json'
import sweep from '../../public/data/sweep.json'
import { parseAlerts } from '../alerts'
import { storedAsOf } from '../pms/DataAsOf'
import type { Manifest, WorkspaceData } from '../types'
import { briefDate, DAILY_DISCLAIMER, DailyBrief } from './DailyBrief'
import { EU_LABEL, EU_ROWS, EuWorkflow } from './EuWorkflow'
import { formatRoute, parseRoute } from './router'

const ALERTS = parseAlerts(alertsFile)!
const DATA = {
  alerts: ALERTS,
  briefs: (briefsFile as unknown as { briefs: unknown[] }).briefs,
  manifest: manifest as unknown as Manifest,
  sweep,
} as unknown as WorkspaceData

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
  vi.restoreAllMocks()
})
const q = (id: string) => host.querySelector(`[data-testid="${id}"]`)

describe('Morning brief', () => {
  it('routes /daily and /eu', () => {
    expect(parseRoute('/daily')).toEqual({ page: 'daily' })
    expect(parseRoute('/eu')).toEqual({ page: 'eu' })
    expect(formatRoute({ page: 'daily' })).toBe('daily')
    expect(formatRoute({ page: 'eu' })).toBe('eu')
  })

  it('is dated by its data, lists every real stored flag with each number linked to openFDA, and makes no network call', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    const onInv = vi.fn()
    act(() => root.render(<DailyBrief data={DATA} onInvestigate={onInv} onBoard={() => undefined} />))
    expect(q('daily-date')?.textContent).toBe(briefDate(DATA))
    expect(q('daily-date')?.textContent).toBe('2026-09-30')
    expect(q('daily-asof')?.textContent).toContain('Data as of:')
    expect(q('daily-disclaimer')?.textContent).toContain(DAILY_DISCLAIMER)
    const real = ALERTS.alerts.filter((a) => a.source.kind !== 'company')
    const cards = Array.from(host.querySelectorAll('[data-testid="daily-flag"]'))
    expect(cards.map((c) => c.getAttribute('data-code')).sort()).toEqual(real.map((a) => a.product_code).sort())
    // Never a simulated company device.
    expect(host.textContent).not.toContain('Simulated company')
    // Every number shown is a link to its openFDA query, and the values are the stored ones.
    for (const a of real) {
      const list = q(`daily-numbers-${a.product_code}`)!
      const links = Array.from(list.querySelectorAll('a'))
      expect(links.length).toBe(a.numbers.length)
      links.forEach((l, i) => {
        expect(l.getAttribute('href')).toBe(a.numbers[i].openfda_url)
        expect(l.getAttribute('href')).toMatch(/^https:\/\/api\.fda\.gov\//)
        expect(l.textContent).toBe(String(a.numbers[i].value))
      })
      expect(q(`daily-recalls-${a.product_code}`)?.textContent).toContain(`Recalls stored for this code: ${a.recalls_total}`)
    }
    // LLZ stored-brief figures unchanged.
    expect(q('daily-numbers-LLZ')?.textContent).toContain('33')
    expect(q('daily-numbers-LLZ')?.textContent).toContain('8.75')
    expect(host.textContent).not.toMatch(/recall (is )?needed|time saved|FDA[- ](validated|approved)/i)
    act(() => (q('daily-investigate-LLZ') as HTMLButtonElement).click())
    expect(onInv).toHaveBeenCalledWith('LLZ')
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})

describe('EU MDR workflow relevance', () => {
  it('says FDA-only, no EUDAMED data, and claims no EU data coverage', () => {
    act(() => root.render(<EuWorkflow asOf={storedAsOf(DATA.manifest)} />))
    expect(q('eu-label')?.textContent).toContain(EU_LABEL)
    expect(q('eu-label')?.textContent).toContain('EUDAMED is not a public adverse-event database like MAUDE')
    expect(host.querySelectorAll('[data-testid="eu-row"]').length).toBe(EU_ROWS.length)
    expect(q('eu-asof')).not.toBeNull()
    expect(host.textContent).toContain('No EU MDR data coverage is claimed.')
    expect(host.textContent).not.toMatch(/Health Canada|TGA|EUDAMED data (is|are) (included|shown)|compliant|satisf(y|ies) Article/i)
  })
})

import kwFile from '../../public/data/keyword_measurement.json'
import { KeywordMeasurementCard, KNOWN_LIMITS, NOT_VALIDATED, type KeywordMeasurement } from '../pms/ValidationPage'

describe('Validation: keyword measurement and honest limits', () => {
  it('shows the stored measurement as recorded (no number typed in the page) and the recall warning', () => {
    const km = kwFile as unknown as KeywordMeasurement
    act(() => root.render(<KeywordMeasurementCard km={km} />))
    const s = q('validation-keyword-summary')?.textContent ?? ''
    expect(s).toContain(`${km.same_problem} of ${km.matched} (${km.pct_same_problem}%)`)
    expect(s).toContain('Claude (AI), not a person')
    expect(q('validation-keyword-recalls')?.textContent).toContain(`${km.recalls.mention_image_any_field} of ${km.recalls.stored} stored LLZ recall records`)
    expect(host.querySelectorAll('[data-testid="validation-keyword-rows"] tbody tr').length).toBe(km.matched)
  })
  it('says "measurement not shown" when the file is missing, never a number', () => {
    act(() => root.render(<KeywordMeasurementCard km="error" />))
    expect(q('validation-keyword-missing')?.textContent).toContain('Measurement not shown')
    expect(host.textContent).not.toMatch(/\d+%/)
  })
  it('keeps the limits: not validated first, Muse Wonder not a human reviewer, live path, own devices, counts not rates', () => {
    expect(NOT_VALIDATED.startsWith('This build is not validated.')).toBe(true)
    expect(NOT_VALIDATED).not.toMatch(/trial/i)
    const all = KNOWN_LIMITS.join(' ')
    expect(all).toContain('not a human reviewer')
    expect(all).toContain('MAUDE counts are not rates')
    expect(all).toContain('Own-company separation is not possible from MAUDE alone')
    expect(all).toContain('not refreshed by a scraper')
  })
})
