import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeAll, describe, expect, it } from 'vitest'
import audit from '../public/data/audit.json'
import briefs from '../public/data/briefs.json'
import dossier from '../public/data/dossier.json'
import evidence from '../public/data/evidence.json'
import investigations from '../public/data/investigations.json'
import manifest from '../public/data/manifest.json'
import protocol from '../public/data/protocol.json'
import schedules from '../public/data/schedules.json'
import sources from '../public/data/sources.json'
import sweep from '../public/data/sweep.json'
import threads from '../public/data/threads.json'
import vision from '../public/data/vision.json'
import { TABS } from './artifacts'
import { AlertBell, AlertList } from './components/AlertBell'
import { ArtifactsPane } from './components/ArtifactsPane'
import { ChatPane } from './components/ChatPane'
import { MetricsChart } from './components/MetricsChart'
import { MiniPane } from './components/MiniDashboard'
import { ExpandButton } from './components/PanelBar'
import { SweepFlagged, SweepRules } from './components/SweepCard'
import { alertItems, miniStats, runMetrics, sweepRowId, SWEEP_RULES, sweepRuleText, sweepStats, sweepStatsText } from './dashboard'
import { collapseOnEscape, toggleExpanded } from './layout'
import type { Brief, Sweep, Thread, WorkspaceData } from './types'

beforeAll(() => {
  ;(globalThis as unknown as { window: unknown }).window = { matchMedia: () => ({ matches: true }) }
})

const text = (html: string) =>
  html
    .replace(/<[^>]+>/g, ' ')
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')

const SW = sweep as unknown as Sweep
const BR = briefs.briefs as unknown as Brief[]
const TH = threads.threads as unknown as Thread[]
const data = {
  manifest,
  threads,
  briefs: BR,
  sources: sources.sources,
  schedules: schedules.schedules,
  investigations,
  evidence,
  audit,
  dossier,
  vision,
  sweep,
  protocol,
} as unknown as WorkspaceData

/** Reads one `NAME = <int>` constant out of the Python detector. */
const pyConst = (name: string): number => {
  const src = readFileSync(new URL('../../src/maudesignal/monitor/deterioration.py', import.meta.url), 'utf8')
  const m = new RegExp(`^${name}\\s*=\\s*(\\d+)\\s*$`, 'm').exec(src)
  if (!m) throw new Error(`${name} not found in deterioration.py`)
  return Number(m[1])
}

const chat = (view: 'new' | 'thread', expanded = false): ReactElement => (
  <ChatPane
    view={view === 'new' ? { kind: 'new' } : { kind: 'thread', id: TH[0].id }}
    data={data}
    withheld={null}
    onWorkflow={() => {}}
    onThread={() => {}}
    onRun={() => {}}
    onVision={() => {}}
    onBrief={() => {}}
    onAlert={() => {}}
    expanded={expanded}
    onToggleExpand={() => {}}
  />
)

const artifacts = (expanded: boolean): ReactElement => (
  <ArtifactsPane
    open
    data={data}
    tab="digest"
    onTab={() => {}}
    thread={null}
    produced={[]}
    briefDate={null}
    vision={null}
    onBriefDate={() => {}}
    onClose={() => {}}
    expanded={expanded}
    onToggleExpand={() => {}}
  />
)

describe('sweep rules', () => {
  it('thresholds equal the constants in src/maudesignal/monitor/deterioration.py', () => {
    expect(SWEEP_RULES.spikeMinReports).toBe(pyConst('SPIKE_MIN_REPORTS'))
    expect(SWEEP_RULES.spikeMultiplier).toBe(pyConst('SPIKE_MULTIPLIER'))
    expect(SWEEP_RULES.baselineWeeks).toBe(pyConst('BASELINE_WEEKS'))
    expect(SWEEP_RULES.severityPoints).toBe(pyConst('SEVERITY_ESCALATION_PP'))
  })

  it('states the rules in the agreed words', () => {
    const r = sweepRuleText()
    expect(r.spike).toBe('Reports suddenly increased needs at least 3 reports this week and at least 2x the 4-week weekly mean.')
    expect(r.serious).toBe('More serious than usual needs the injury/death share to rise 15 points or more.')
  })

  it('"N of M codes had fewer than 3 reports" is computed from the rows, not hardcoded', () => {
    const rows = sweep.rows
    const fewer = rows.filter((r) => r.current_count < 3).length
    const none = rows.filter((r) => r.current_count === 0).length
    const st = sweepStats(SW)
    expect(st).toEqual({ total: rows.length, fewer, none })
    expect(sweepStatsText(st)).toBe(`${fewer} of ${rows.length} codes had fewer than 3 reports this week (${none} had none).`)
    // a changed export changes the sentence
    const edited = { ...SW, rows: SW.rows.map((r) => ({ ...r, current_count: 9 })) }
    expect(sweepStats(edited)).toEqual({ total: rows.length, fewer: 0, none: 0 })
  })

  it('every spike row obeys the stated rule', () => {
    for (const r of SW.rows)
      if (r.classification === 'spike') {
        expect(r.current_count).toBeGreaterThanOrEqual(SWEEP_RULES.spikeMinReports)
        expect(r.current_count).toBeGreaterThanOrEqual(SWEEP_RULES.spikeMultiplier * r.baseline_weekly_mean)
      }
  })

  it('the sweep card shows the rules and the computed sentence', () => {
    const html = text(renderToStaticMarkup(<SweepRules sweep={SW} />))
    expect(html).toContain(sweepRuleText().spike)
    expect(html).toContain(sweepRuleText().serious)
    expect(html).toContain(sweepStatsText(sweepStats(SW)))
  })
})

describe('alert bell', () => {
  const risky = (c: string) => c === 'new_signal' || c === 'severity_escalation'

  it('counts risky sweep rows and risky signals of the newest brief, nothing else', () => {
    const fromSweep = sweep.rows.filter((r) => risky(r.classification)).length
    const fromBrief = BR[0].signals.filter((s) => risky(s.classification)).length
    const items = alertItems(SW, BR)
    expect(items.length).toBe(fromSweep + fromBrief)
    expect(items.every((a) => risky(a.kind))).toBe(true)
    // "reports suddenly increased" is not risky
    expect(items.some((a) => a.productCode === 'LLZ' && a.source === 'brief')).toBe(false)
  })

  it('the list rows are links with a chevron, 17px text and a 44px target; the label is "Alerts"', () => {
    const items = alertItems(SW, BR)
    const html = renderToStaticMarkup(<AlertList items={items} onOpen={() => {}} />)
    expect(html).toContain('aria-label="Alerts"')
    expect(html).toContain('min-h-11')
    expect(html).toContain('text-[17px]')
    expect(html).toContain('<svg')
    expect(html).toContain('whitespace-nowrap')
  })

  it('shows the count in a red badge and in the aria-label', () => {
    const items = alertItems(SW, BR)
    const raw = renderToStaticMarkup(<AlertBell items={items} onOpen={() => {}} />)
    expect(raw).toContain(`aria-label="Alerts: ${items.length} risky ${items.length === 1 ? 'item' : 'items'}"`)
    expect(raw).toContain('data-testid="alert-badge"')
    expect(raw).toContain('bg-critical')
  })

  it('has no badge when nothing is risky', () => {
    const raw = renderToStaticMarkup(<AlertBell items={[]} onOpen={() => {}} />)
    expect(raw).toContain('Alerts: no risky items')
    expect(raw).not.toContain('alert-badge')
  })
})

describe('expand and collapse', () => {
  it('toggles one panel at a time; Esc collapses', () => {
    expect(toggleExpanded(null, 'main')).toBe('main')
    expect(toggleExpanded('main', 'main')).toBeNull()
    expect(toggleExpanded('main', 'mini')).toBe('mini')
    expect(collapseOnEscape('artifacts', 'Escape')).toBeNull()
    expect(collapseOnEscape('artifacts', 'a')).toBe('artifacts')
  })

  it('the button says what it will do', () => {
    const open = renderToStaticMarkup(<ExpandButton panel="artifacts" expanded={false} onToggle={() => {}} />)
    expect(open).toContain('aria-label="Expand artifacts to full screen"')
    expect(open).toContain('aria-pressed="false"')
    const shut = renderToStaticMarkup(<ExpandButton panel="artifacts" expanded onToggle={() => {}} />)
    expect(shut).toContain('aria-label="Back: collapse artifacts (Esc)"')
    expect(shut).toContain('aria-pressed="true"')
  })

  it('an expanded panel is lifted over the page, a collapsed one is not', () => {
    const mini = (expanded: boolean) =>
      renderToStaticMarkup(<MiniPane workflow="ai-sweep" data={data} expanded={expanded} onToggleExpand={() => {}} />)
    expect(mini(true)).toContain('fixed inset-0')
    expect(mini(false)).not.toContain('fixed inset-0')
    expect(renderToStaticMarkup(artifacts(true))).toContain('fixed inset-0')
    expect(renderToStaticMarkup(artifacts(false))).not.toContain('fixed inset-0')
    expect(renderToStaticMarkup(chat('new', true))).toContain('fixed inset-0')
    expect(renderToStaticMarkup(chat('new', false))).not.toContain('fixed inset-0')
  })

  it('the artifacts tabs wrap (no sideways scroll), are 44px high with 17px text and short labels', () => {
    const html = renderToStaticMarkup(artifacts(false))
    const strip = /<div role="tablist"[^>]*class="([^"]*)"/.exec(html) ?? /class="([^"]*)"[^>]*role="tablist"/.exec(html)
    expect(strip?.[1]).toContain('ws-tabstrip')
    expect(strip?.[1]).not.toContain('overflow')
    expect(readFileSync(join(__dirname, 'index.css'), 'utf8')).toMatch(/\.ws-tabstrip\s*\{[^}]*flex-wrap:\s*wrap[^}]*overflow:\s*visible/)
    expect(Math.max(...TABS.map((t) => t.label.length))).toBeLessThanOrEqual(10)
    expect(html).toContain('h-11 shrink-0')
    expect(html).toContain('text-[17px]')
    expect(TABS.length).toBe(7)
  })

  it('an expanded panel offers a labelled Back button and a trail to Home', () => {
    const html = text(renderToStaticMarkup(artifacts(true)))
    expect(html).toContain('Back')
    expect(html).toContain('Home')
    expect(html).toContain('Artifacts')
    const btn = renderToStaticMarkup(<ExpandButton panel="mini" expanded onToggle={() => {}} />)
    expect(btn).toContain('min-h-11')
  })
})

describe('home dashboard and mini-dashboards', () => {
  it('home shows the sweep, the flags (labelled demo snapshot), alerts and the run charts', () => {
    const html = text(renderToStaticMarkup(chat('new')))
    expect(html).toContain('How a code is flagged')
    expect(html).toContain("This week's flags")
    expect(html).toContain('Demo snapshot')
    expect(html).toContain(BR[0].date)
    expect(html).toContain(`Alerts · ${alertItems(SW, BR).length}`)
    for (const t of ['Sentences shown per run', 'Gate pass rate', 'Cost per run']) expect(html).toContain(t)
    expect(html).toContain('Speed per run: Not recorded')
  })

  it('speed says "not recorded" because no stored run has a duration', () => {
    expect(runMetrics(TH).every((r) => r.durationS === null)).toBe(true)
    const html = text(renderToStaticMarkup(<MetricsChart threads={TH} />))
    expect(html).toContain('Not recorded: the stored runs do not include how long each took.')
    // no empty Speed card: it is one line of text, not a chart card
    expect(html).not.toContain('Speed per run, scale')
    expect(renderToStaticMarkup(<MetricsChart threads={TH} />)).not.toContain('<figcaption class="text-[17px] font-semibold">Speed per run')
  })

  it('run metrics are the stored numbers', () => {
    const m = runMetrics(TH)
    expect(m.length).toBe(TH.length)
    const cost = m.reduce((a, r) => a + (r.costUsd ?? 0), 0)
    const direct = TH.reduce((a, t) => a + (t.usage?.cost_usd ?? 0), 0)
    expect(cost).toBeCloseTo(direct, 9)
    const trap = m.find((r) => r.id === '06-trap')
    expect(trap?.firstPass).toBeCloseTo(3 / 4, 9)
    expect(trap?.finalPass).toBeCloseTo(3 / 4, 9)
  })

  it('every workflow has its own key numbers', () => {
    for (const w of ['ai-sweep', 'check-device', 'weekly-signals', 'ask-copilot', 'capa-need-evidence', 'vision'] as const)
      expect(miniStats(w, data).length).toBeGreaterThan(0)
    const s = miniStats('ai-sweep', data)
    expect(s.find((x) => x.label === 'Fewer than 3 reports')?.value).toBe(`${sweepStats(SW).fewer}`)
  })

  it('uses none of the dropped words', () => {
    const html = text(renderToStaticMarkup(chat('new'))).toLowerCase()
    const banned = ['fda-approved', 'part 11', 'validated', 'overnight', 'worsening', 'citation-checked', 'complaint data', 'unsafe', 'compliant']
    for (const b of banned) expect(html).not.toContain(b)
    expect(html).not.toMatch(/\bsafe\b/)
  })

  it('an alert for a sweep code links to the row of that code, which is marked when focused', () => {
    const sw = SW
    const alert = alertItems(sw, []).find((a) => a.source === 'sweep')
    if (!alert) return // no risky sweep item in the stored data
    const html = renderToStaticMarkup(<SweepFlagged sweep={sw} focusCode={alert.productCode} />)
    expect(html).toContain(`id="${sweepRowId(alert.productCode)}"`)
    const row = new RegExp(`<li[^>]*id="${sweepRowId(alert.productCode)}"[^>]*>`).exec(html)?.[0] ?? ''
    expect(row).toContain('data-focused="true"')
    expect(renderToStaticMarkup(<SweepFlagged sweep={sw} />)).not.toContain('data-focused')
  })

  it('"Claims in shown sentences" counts only claims inside shown sentences', () => {
    const d = data as WorkspaceData
    const stats = miniStats('ask-copilot', d)
    const stat = stats.find((s) => s.label === 'Claims in shown sentences')
    expect(stat).toBeDefined()
    const ts = d.threads.threads.filter((t) => d.threads.workflows.find((w) => w.id === 'ask-copilot')?.thread_ids.includes(t.id))
    const expected = ts
      .filter((t) => t.tool_steps.length > 0 || t.sentences.some((s) => s.claims.length > 0))
      .flatMap((t) => t.sentences.filter((s) => s.status === 'pass').flatMap((s) => s.claims))
      .filter((c) => c.status === 'pass').length
    expect(stat?.value).toBe(`${expected}`)
  })
})
