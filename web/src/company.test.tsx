import { renderToStaticMarkup } from 'react-dom/server'
import { beforeAll, describe, expect, it } from 'vitest'
import briefs from '../public/data/briefs.json'
import company from '../public/data/company.json'
import sweep from '../public/data/sweep.json'
import { AlertGroup, AlertList } from './components/AlertBell'
import { MiniStats } from './components/MiniDashboard'
import { chipName, CompanyDeviceView, CompanyList, OurDevices, shortPatternLabel, StatusBars, StatusFilterList } from './components/OurDevices'
import { alertItems, devicesPerStatus, groupAlerts, miniStats, sortedDevices, statusesByPriority } from './dashboard'
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
const withEvidence = C.devices.find((d) => d.evidence.available && d.patterns.some((p) => p.kind === 'keyword' && p.quotes.length > 0))!
const llz = C.devices.find((d) => d.product_code === 'LLZ')!
// No code in the shipped file is missing (the demo database or a fetched file backs all of them), so the
// missing state is tested on a real device whose evidence is emptied the way the exporter writes it.
const withoutEvidence: CompanyDevice = {
  ...C.devices[0],
  evidence: { origin: 'missing', available: false, note: 'evidence not fetched yet', report_count: null, window: null, queries: [], recalls: null },
  patterns: [],
}
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

  it('every origin the contract names is served: the demo-database codes are demo_db, never missing', () => {
    const inDemoDb = C.notes.find((n) => /are in the demo database/.test(n)) ?? ''
    const codes = ['LLZ', 'QIH', 'MYN', 'POK']
    for (const c of codes) expect(inDemoDb).toContain(c)
    for (const d of C.devices.filter((x) => codes.includes(x.product_code))) {
      expect(d.evidence.origin).toBe('demo_db')
      expect(d.evidence.available).toBe(true)
      expect(d.evidence.report_count?.gate).toBe('pass')
      expect(d.evidence.recalls?.matched_total).toBeNull()
    }
    expect(C.devices.filter((d) => !d.evidence.available)).toHaveLength(0)
  })

  it('the expanded devices-per-status view, the bell group and the missing state each carry the banner', () => {
    expect(text(renderToStaticMarkup(<StatusBars company={C} />))).toContain(BANNER)
    const mine = alertItems(sweep as never, briefs.briefs as never, C).filter((a) => a.source === 'company')
    const group = renderToStaticMarkup(
      <AlertGroup title="Our devices (simulated)" items={mine} onOpen={noop} onViewAll={noop} viewAllLabel="View all" seen={[]} banner={C.banner} />,
    )
    expect(text(group)).toContain(BANNER)
    expect(text(view(withoutEvidence))).toContain(BANNER)
  })

  it('the missing-evidence reason does not say a demo-database code has nothing stored', () => {
    const t = text(view(withoutEvidence))
    expect(t).toContain('no rows in the demo database and no fetched evidence file')
    expect(t).not.toContain('is in the exported file')
  })

  it('a truncated recall excerpt is shown with an ellipsis, a whole one without', () => {
    const base = C.devices.find((d) => d.evidence.recalls && d.evidence.recalls.latest.some((r) => r.excerpt))!
    const r0 = base.evidence.recalls!.latest.find((r) => r.excerpt)!
    const mk = (cut: boolean): CompanyDevice => ({
      ...base,
      evidence: { ...base.evidence, recalls: { ...base.evidence.recalls!, latest: [{ ...r0, excerpt_truncated: cut }] } },
    })
    expect(text(view(mk(true)))).toContain(`“${r0.excerpt}…”`)
    expect(text(view(mk(false)))).toContain(`“${r0.excerpt}”`)
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
    expect(mine.map((a) => a.deviceId).sort()).toEqual(needs.map((d) => d.id).sort())
    expect(mine.every((a) => a.deviceName)).toBe(true)
    const g = groupAlerts(all)
    expect(g.devices.length).toBe(needs.length)
    expect(g.signals.length).toBe(base.length)
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
      expect(t).toContain(shortPatternLabel(p))
      expect(shortPatternLabel(p)).not.toMatch(/^Keyword match/)
      if (p.kind === 'keyword') expect(t).toContain('Unreviewed')
      for (const q of p.quotes) {
        expect(t).toContain(`“${q.text}”`)
        expect(html).toContain(q.url)
      }
      for (const l of p.links) expect(html).toContain(l.url)
    }
    if (withEvidence.patterns.some((p) => p.kind === 'keyword')) expect(t).toContain('Keyword groups are deterministic keyword matches')
    expect(t).toContain('Status history')
    expect(t).toContain('Chain ok')
    for (const h of withEvidence.history) expect(t).toContain(`entry ${h.seq}`)
  })

  it('the LLZ device shows the recorded investigator groups, not keyword groups, with its stored recalls', () => {
    expect(llz.evidence.origin).toBe('demo_db')
    expect(llz.patterns.length).toBeGreaterThan(0)
    expect(llz.patterns.every((p) => p.kind === 'investigator')).toBe(true)
    const t = text(view(llz))
    expect(t).not.toContain('Evidence not fetched')
    expect(t).not.toContain('evidence not fetched yet')
    expect(t).toContain(String(llz.evidence.report_count!.value))
    expect(t).toContain(String(llz.evidence.recalls!.stored))
    expect(t).not.toContain('Unreviewed')
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

  it('the table is sorted by status priority (Needs review first), then by newest status date', () => {
    const rows = sortedDevices(C)
    const order = ['Needs review', 'Testing in progress', 'Monitoring — nothing open', 'Already covered', 'Not applicable to our device']
    const idx = rows.map((d) => order.indexOf(d.status!.label))
    expect(idx).toEqual([...idx].sort((a, b) => a - b))
    const need = C.devices.filter((d) => d.status?.label === 'Needs review').length
    expect(rows.slice(0, need).every((d) => d.status?.label === 'Needs review')).toBe(true)
    const dates = rows.slice(0, need).map((d) => d.status!.date)
    expect(dates).toEqual([...dates].sort().reverse())
    expect(sortedDevices(C, 'Needs review')).toHaveLength(need)
    expect(statusesByPriority(C)[0].label).toBe('Needs review')
    const html = renderToStaticMarkup(<CompanyList company={C} onDevice={noop} />)
    expect(html.indexOf(rows[0].name)).toBeLessThan(html.indexOf(rows[rows.length - 1].name))
    expect(html).toContain('data-needs-review')
  })

  it('filter chips show a count per status and the filter narrows the table', () => {
    const html = renderToStaticMarkup(<CompanyList company={C} onDevice={noop} filter="Needs review" />)
    const chips = html.slice(html.indexOf('data-testid="filter-chips"'), html.indexOf('<table'))
    for (const x of devicesPerStatus(C)) expect(text(chips)).toContain(`${chipName(x.label)} ${x.count}`)
    expect((html.match(/data-testid="status-chip"/g) ?? []).length).toBe(sortedDevices(C, 'Needs review').length)
  })

  it('the left column is a compact status filter list and shows the banner nowhere (the page shows it once)', () => {
    const t = text(renderToStaticMarkup(<StatusFilterList company={C} filter={null} onFilter={noop} />))
    expect(t).toContain('All devices')
    for (const x of devicesPerStatus(C)) expect(t).toContain(x.label)
    expect(t).not.toContain('Simulated company')
  })

  it('a device page has jump links, sorts patterns by report count, and the missing-evidence state has an action', () => {
    const t = view(withEvidence)
    expect(t).toContain('data-testid="jump-nav"')
    const counts = [...t.matchAll(/data-testid="pattern"/g)].length
    expect(counts).toBe(withEvidence.patterns.length)
    const html = text(view(withEvidence))
    const nums = withEvidence.patterns.map((p) => p.count).sort((a, b) => b - a)
    let at = 0
    for (const n of nums) {
      const i = html.indexOf(`${n} reports`, at)
      expect(i).toBeGreaterThanOrEqual(at)
      at = i
    }
    const m = view(withoutEvidence)
    expect(m).toContain('Fetch evidence')
    expect(text(m)).toContain('Reason:')
  })
})
