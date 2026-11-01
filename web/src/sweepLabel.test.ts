import { describe, expect, it } from 'vitest'
import sweep from '../public/data/sweep.json'
import { labelForWeek, monDay, sameWeek, sweepDetail, sweepLabel, sweepWeek, weekRange } from './sweepLabel'
import type { Sweep } from './types'

const SW = sweep as unknown as Sweep

describe('sweep label (from the stored sweep, never hardcoded)', () => {
  it('reads the run day and the openFDA week from public/data/sweep.json', () => {
    // generated_utc 2026-10-30T02:55:38Z; window 2026-09-24..2026-09-30 in the committed sweep.
    const run = monDay(SW.meta.generated_utc)
    const week = weekRange(SW.meta.window.current_start, SW.meta.window.current_end)
    expect(sweepLabel(SW)).toBe(`Latest sweep · ${run} (openFDA week ${week})`)
    expect(sweepLabel(SW)).toBe('Latest sweep · Oct 30 (openFDA week Sep 24–30)')
    expect(sweepWeek(SW)).toBe('openFDA week Sep 24–30')
  })

  it('follows a newer sweep file', () => {
    const next = { meta: { ...SW.meta, generated_utc: '2026-11-06T03:00:00Z', window: { ...SW.meta.window, current_start: '2026-09-28', current_end: '2026-10-04' } } }
    expect(sweepLabel(next)).toBe('Latest sweep · Nov 6 (openFDA week Sep 28–Oct 4)')
  })

  it('formats weeks across a month or a year, and compact dates', () => {
    expect(weekRange('20260924', '20260930')).toBe('Sep 24–30')
    expect(weekRange('2026-12-29', '2027-01-04')).toBe('Dec 29, 2026–Jan 4, 2027')
    expect(monDay('2026-10-30')).toBe('Oct 30')
  })

  it('is null when a field is missing, so nothing is made up', () => {
    expect(sweepLabel(null)).toBeNull()
    expect(sweepLabel({ meta: { ...SW.meta, generated_utc: '' } })).toBeNull()
    expect(monDay('not a date')).toBeNull()
  })

  it('item details carry the label', () => {
    expect(sweepDetail(1, 'Latest sweep · Oct 30 (openFDA week Sep 24–30)')).toBe('1 report · Latest sweep · Oct 30 (openFDA week Sep 24–30)')
    expect(sweepDetail(3, null)).toBe('3 reports in the stored week')
    expect(sweepDetail(3, null, 'Sep 17–23')).toBe('3 reports in the week Sep 17–23')
  })

  it('rejects anything that is not a real UTC date', () => {
    expect(monDay('2026-02-31')).toBeNull()
    expect(monDay('2026-0924')).toBeNull()
    expect(monDay('2026-10-30T02:55:38+02:00')).toBeNull()
    expect(monDay('2026-10-30T02:55:38Z')).toBe('Oct 30')
    expect(weekRange('2026-09-31', '2026-10-04')).toBeNull()
    expect(sweepLabel({ meta: { ...SW.meta, generated_utc: '2026-02-31T00:00:00Z' } })).toBeNull()
  })

  it("uses the sweep's label only for an alert of the sweep's own week", () => {
    const own = { from: SW.meta.window.current_start, to: SW.meta.window.current_end }
    expect(sameWeek(SW, own.from, own.to)).toBe(true)
    expect(labelForWeek(SW, own)).toBe(sweepLabel(SW))
    expect(labelForWeek(SW, { from: '2026-09-17', to: '2026-09-23' })).toBeNull()
    expect(labelForWeek(SW, undefined)).toBeNull()
  })
})
