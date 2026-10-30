import { renderToStaticMarkup } from 'react-dom/server'
import { beforeAll, describe, expect, it } from 'vitest'
import briefs from '../public/data/briefs.json'
import company from '../public/data/company.json'
import sweep from '../public/data/sweep.json'
import { AlertList } from './components/AlertBell'
import { MiniStats } from './components/MiniDashboard'
import { CompanyDeviceView, CompanyList, OurDevices, StatusBars } from './components/OurDevices'
import { alertItems, devicesPerStatus, miniStats } from './dashboard'
import { WORKFLOWS } from './data'
import type { Company, CompanyDevice, WorkspaceData } from './types'

const C = company as unknown as Company
const BANNER = 'Simulated company — sample data. Problem evidence is real FDA data.'
const BANNED = /\b(safe|unsafe|compliant)\b|fda[- ]approved|part 11 compliant|worsening signals?|citation-checked|complaint data/i

beforeAll(() => {
  ;(globalThis as unknown as { window: unknown }).window = {
    matchMedia: () => ({ matches: true }),
  }
})

const text = (html: string) =>
  html
    .replace(/<[^>]+>/g, ' ')
    .replace(/&quot;/g, '"')
    .replace(/\s+/g, ' ')
const noop = () => {}
const view = (d: CompanyDevice) => renderToStaticMarkup(<CompanyDeviceView company={C} device={d} onBack={noop} />)
const withEvidence = C.devices.find((d) => d.evidence.available && d.patterns.some((p) => p.quotes.length > 0))!
const withoutEvidence = C.devices.find((d) => !d.evidence.available)!
const asData = { company: C } as unknown as WorkspaceData

describe('Our devices (simulated)', () => {
  it('is a workflow in the sidebar list', () => {
    expect(WORKFLOWS.find((w) => w.id === 'our-devices')?.title).toBe('Our devices (simulated)')
  })

  it('the stored banner is the contract string and shows on the table and on every device', () => {
    expect(C.banner).toBe(BANNER)
    expect(text(renderToStaticMarkup(<CompanyList company={C} onDevice={noop} />))).toContain(BANNER)
    for (const d of C.devices) expect(text(view(d))).toContain(BANNER)
    expect(text(renderToStaticMarkup(<OurDevices company={C} deviceId="NOPE" onDevice={noop} onBack={noop} />))).toContain(BANNER)
  })

  it('the mini-dashboard counts devices per status and the counts add up', () => {
    const per = devicesPerStatus(C)
    expect(per.map((x) => x.label)).toEqual(C.statuses.map((s) => s.label))
    expect(per.reduce((n, x) => n + x.count, 0)).toBe(C.devices.length)
    const html = text(renderToStaticMarkup(<MiniStats workflow="our-devices" data={asData} />))
    for (const x of per) expect(html).toContain(x.label)
    expect(miniStats('our-devices', asData)[0]).toEqual({
      label: 'Devices (simulated)',
      value: `${C.devices.length}`,
    })
    expect(text(renderToStaticMarkup(<StatusBars company={C} />))).toContain('Devices per status')
  })

  it('the table lists every device with its status chip', () => {
    const html = renderToStaticMarkup(<CompanyList company={C} onDevice={noop} />)
    expect((html.match(/data-testid="status-chip"/g) ?? []).length).toBe(C.devices.length)
    for (const d of C.devices) expect(text(html)).toContain(d.name)
  })

  it('the alert bell counts the Needs review devices', () => {
    const needs = C.devices.filter((d) => d.status?.label === 'Needs review')
    expect(needs.length).toBeGreaterThan(0)
    const base = alertItems(sweep as never, briefs.briefs as never)
    const all = alertItems(sweep as never, briefs.briefs as never, C)
    const mine = all.filter((a) => a.source === 'company')
    expect(mine.map((a) => a.deviceId)).toEqual(needs.map((d) => d.id))
    expect(all.length - base.length).toBe(needs.length)
    const html = text(renderToStaticMarkup(<AlertList items={mine} onOpen={noop} />))
    expect(html).toContain('Needs review')
    expect(html).toContain('Our devices (simulated)')
  })

  it('a device with no stored evidence says "evidence not fetched yet" and shows no number', () => {
    const html = view(withoutEvidence)
    expect(text(html)).toContain('evidence not fetched yet')
    expect(html).not.toContain('data-testid="report-count"')
    expect(html).not.toContain('data-testid="pattern"')
  })

  it('a device with evidence shows patterns, verbatim quotes, evidence links and the status history', () => {
    const html = view(withEvidence)
    const t = text(html)
    expect(html).toContain('data-testid="report-count"')
    expect(t).toContain(String(withEvidence.evidence.report_count!.value))
    for (const p of withEvidence.patterns) {
      expect(t).toContain(p.display_label)
      for (const q of p.quotes) {
        expect(t).toContain(`“${q.text}”`)
        expect(html).toContain(q.url)
      }
      for (const l of p.links) expect(html).toContain(l.url)
    }
    expect(t).toContain('Keyword groups are deterministic keyword matches')
    expect(t).toContain('Status history')
    expect(t).toContain('Chain ok')
    for (const h of withEvidence.history) expect(t).toContain(`entry ${h.seq}`)
  })

  it('a broken chain is stated, not hidden', () => {
    const broken = {
      ...C,
      audit: { ...C.audit, chain_ok: false, first_bad_seq: 4 },
    }
    const t = text(renderToStaticMarkup(<CompanyDeviceView company={broken} device={withEvidence} onBack={noop} />))
    expect(t).toContain('Chain broken at entry 4')
    expect(t).not.toContain('Chain ok')
  })

  it('statuses are set by a named simulated person and history only moves forward', () => {
    const rank = new Map(C.statuses.map((s) => [s.label, s.rank]))
    for (const d of C.devices) {
      expect(d.status?.set_by.endsWith('(simulated)')).toBe(true)
      d.history.forEach((h, i) => {
        expect(h.actor.endsWith('(simulated)')).toBe(true)
        if (i > 0) expect(rank.get(h.to_status)!).toBeGreaterThan(rank.get(d.history[i - 1].to_status)!)
      })
    }
  })

  it('no screen prints a banned word', () => {
    const pages = [renderToStaticMarkup(<CompanyList company={C} onDevice={noop} />), ...C.devices.map(view)]
    for (const html of pages) expect(text(html)).not.toMatch(BANNED)
  })
})
