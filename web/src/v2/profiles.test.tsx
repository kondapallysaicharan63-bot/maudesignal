// @vitest-environment jsdom
// Simulated device lifecycle profiles: the data rules (dates in order, FDA review time, wording per pathway, fake
// numbers only, nothing in the future unless planned, the real fields equal to stored FDA data) and the rendering
// (every tab of every device carries the SIMULATED label; the real FDA box stays separate; the tiles count right).
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import company from '../../public/data/company.json'
import raw from '../../public/data/company_profiles.json'
import type { Company } from '../types'
import { DeviceProfilePage, DeviceTiles, PROFILE_TAB_LABELS, profileTitle } from './DeviceProfile'
import { DECISION_VERB, investigateHref, SIM_LABEL, summarize, type DecisionOutcome, type DeviceProfile, type ProfilesFile } from './profiles'
import { formatRoute, parseRoute, PROFILE_TABS, type ProfileTab } from './router'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

type Escalation = Extract<DecisionOutcome, { kind: 'escalation' }>
const C = company as unknown as Company
const F = raw as unknown as ProfilesFile
const P = Object.values(F.profiles)
const BANNED = /fda[- ]approved|\bvalidated\b|\bsafe\b|\bunsafe\b|draft capa|\bcompliant\b/i
const ORDER = ['design_start', 'design_freeze', 'vv_start', 'vv_end', 'presub', 'submission', 'ai_request', 'ai_response', 'decision', 'launch']
const NUMBER_RE: Record<string, RegExp> = { '510(k)': /^K-SIM-\d{4}$/, 'De Novo': /^DEN-SIM-\d{4}$/, PMA: /^P-SIM-\d{4}$/ }
const days = (a: string, b: string) => Math.round((Date.parse(b) - Date.parse(a)) / 86_400_000)
const ms = (p: DeviceProfile, key: string) => p.milestones.find((m) => m.key === key)

/** Every {date, planned} object, every other date-like string, with its path. */
function datesIn(o: unknown, path = ''): { path: string; date: string; planned: boolean | null }[] {
  const out: { path: string; date: string; planned: boolean | null }[] = []
  if (Array.isArray(o)) o.forEach((x, i) => out.push(...datesIn(x, `${path}[${i}]`)))
  else if (o && typeof o === 'object') {
    const r = o as Record<string, unknown>
    for (const [k, v] of Object.entries(r)) {
      if (k === 'due_date') continue // a deadline, not an event
      if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)) out.push({ path: `${path}.${k}`, date: v, planned: k === 'date' && typeof r.planned === 'boolean' ? (r.planned as boolean) : k === 'due' && typeof r.due_planned === 'boolean' ? (r.due_planned as boolean) : null })
      else if (typeof v === 'string' && k === 'month' && /^\d{4}-\d{2}$/.test(v)) out.push({ path: `${path}.${k}`, date: `${v}-01`, planned: null })
      else out.push(...datesIn(v, `${path}.${k}`))
    }
  }
  return out
}

function strings(o: unknown): string[] {
  if (typeof o === 'string') return [o]
  if (Array.isArray(o)) return o.flatMap(strings)
  if (o && typeof o === 'object') return Object.values(o).flatMap(strings)
  return []
}

describe('company_profiles.json: data rules', () => {
  it('has a profile for every simulated device, with its name, model, owner and product code unchanged', () => {
    expect(C.devices).toHaveLength(12)
    expect(Object.keys(F.profiles).sort()).toEqual(C.devices.map((d) => d.id).sort())
    for (const d of C.devices) {
      const p = F.profiles[d.id]
      expect([p.name, p.model, p.owner, p.product_code]).toEqual([d.name, d.model, d.owner, d.product_code])
      expect(p.simulated).toBe(true)
    }
    expect(F.simulated).toBe(true)
    expect(F.banner).toMatch(/^SIMULATED — sample data/)
  })

  it('takes the FDA name, class and regulation number from stored data only', () => {
    for (const d of C.devices) {
      const o = F.profiles[d.id].overview
      expect(o.fda_device_name).toBe(d.device_type.name)
      const f = resolve(__dirname, `../../../demo/company/evidence/${d.product_code}.json`)
      type Cl = { device_class?: string; regulation_number?: string }
      const read = (): Cl | null => {
        try {
          return (JSON.parse(readFileSync(f, 'utf8')) as { classification: Cl }).classification
        } catch {
          return null
        }
      }
      const stored = read()
      if (stored) {
        expect(o.device_class).toBe(stored.device_class || null)
        expect(o.regulation_number).toBe(stored.regulation_number || null)
      } else {
        expect(o.classification_source).toMatch(/stored MAUDE reports|not in stored data/)
      }
    }
    // OTE has no regulation number in the stored classification: it is null, never invented.
    expect(P.find((p) => p.product_code === 'OTE')?.overview.regulation_number).toBeNull()
  })

  it('orders dates design → V&V → Pre-Sub → submission → AI request → AI response → decision → launch', () => {
    for (const p of P) {
      const keys = p.milestones.map((m) => m.key)
      expect(keys).toEqual(ORDER.filter((k) => keys.includes(k)))
      for (let i = 1; i < p.milestones.length; i++) expect(p.milestones[i].date > p.milestones[i - 1].date, `${p.id} ${keys[i]}`).toBe(true)
      expect(keys.slice(0, 6)).toEqual(ORDER.slice(0, 6))
    }
  })

  it('510(k) decisions take about 90 FDA days plus hold time; De Novo and PMA take longer', () => {
    for (const p of P) {
      const r = p.regulatory
      const s = ms(p, 'submission'), a = ms(p, 'ai_request'), b = ms(p, 'ai_response'), d = ms(p, 'decision')
      if (!d) {
        expect(r.decision).toBeNull()
        expect(r.fda_days).toBeNull()
        continue
      }
      const hold = days(a!.date, b!.date)
      expect(r.hold_days).toBe(hold)
      expect(r.fda_days).toBe(days(s!.date, d.date) - hold)
      if (r.pathway === '510(k)') expect(r.fda_days!).toBeGreaterThanOrEqual(75), expect(r.fda_days!).toBeLessThanOrEqual(110)
      else expect(r.fda_days!).toBeGreaterThan(120)
    }
  })

  it('has a mix of statuses: in development, under FDA review, testing failed and redone', () => {
    const stages = P.map((p) => p.overview.stage)
    expect(stages).toContain('development')
    expect(stages).toContain('under_review')
    expect(stages.filter((s) => s === 'on_market' || s === 'post_market').length).toBeGreaterThanOrEqual(3)
    const redone = P.filter((p) => p.vv.problems.some((x) => x.retest_result === 'pass' && p.vv.protocols.some((t) => t.id === x.found_in && t.result === 'fail') && p.vv.protocols.some((t) => t.id === x.retest_id && t.result === 'pass')))
    expect(redone.length).toBeGreaterThanOrEqual(1)
  })

  it('uses "cleared" for 510(k), "granted" for De Novo and "approved" only for PMA', () => {
    const pathways = new Set(P.map((p) => p.overview.pathway))
    expect(pathways).toContain('510(k)')
    expect(pathways).toContain('PMA')
    for (const p of P) {
      const r = p.regulatory
      expect(r.decision_verb).toBe(DECISION_VERB[r.pathway])
      if (r.decision) expect(r.decision.outcome).toBe(DECISION_VERB[r.pathway])
      const fdaWords = strings([p.overview, p.regulatory, p.milestones]).join(' \n ')
      const wrong = (['cleared', 'granted', 'approved'] as const).filter((v) => v !== DECISION_VERB[r.pathway])
      for (const v of wrong) expect(fdaWords, `${p.id} says ${v}`).not.toMatch(new RegExp(`\\b${v}\\b`, 'i'))
      expect(r.submission.number).toMatch(NUMBER_RE[r.pathway])
      expect(r.presub.number).toMatch(/^Q-SIM-\d{4}$/)
    }
  })

  it('has no real K-number, UDI, banned wording, or real-looking numbers', () => {
    const all = strings(F)
    for (const s of all) {
      expect(s).not.toMatch(/\bK\d{6}\b/)
      expect(s).not.toMatch(/^K\d{6}$/)
      expect(s).not.toMatch(/\b\d{14}\b|\(01\)\d/)
      expect(s, s).not.toMatch(BANNED)
    }
    for (const p of P) expect(p.market.udi_di).toMatch(/^SIM-UDI-/)
  })

  it('has no date after the as-of date unless it is planned, and the as-of date is not in the future', () => {
    expect(F.as_of).toBe('2026-11-01')
    for (const p of P) {
      for (const x of datesIn(p)) {
        if (x.date > F.as_of) expect(x.planned, `${p.id}${x.path} ${x.date}`).toBe(true)
        if (x.planned === true) expect(x.date > F.as_of, `${p.id}${x.path} is planned but past`).toBe(true)
      }
      for (const e of p.activity) expect(e.date <= F.as_of).toBe(true)
      for (const c of p.postmarket.capas) {
        expect(c.opened <= F.as_of).toBe(true)
        if (c.closed) expect(c.closed > c.opened).toBe(true)
        expect(c.state).toBe(c.closed ? 'closed' : 'open')
      }
    }
  })

  it('names only simulated people, and the log covers every function', () => {
    const roles = new Set<string>()
    for (const p of P) {
      expect(p.activity.length).toBeGreaterThanOrEqual(10)
      for (const e of p.activity) {
        expect(e.person).toMatch(/\(simulated\)$/)
        roles.add(e.role)
      }
      for (const r of p.design.reviews) for (const a of r.attendees) expect(a.name).toMatch(/\(simulated\)$/)
      for (const c of p.postmarket.capas) expect(c.owner).toMatch(/\(simulated\)$/)
    }
    for (const f of ['Design Engineering', 'Quality Engineering', 'Regulatory Affairs', 'Clinical', 'Post-Market Surveillance', 'Management review']) expect(roles).toContain(f)
  })

  it('gives every AI device a simulated performance study whose numbers add up', () => {
    for (const p of P) {
      const s = p.vv.study
      if (!p.overview.ai) {
        expect(s).toBeNull()
        continue
      }
      expect(s).not.toBeNull()
      expect(s!.label).toMatch(/SIMULATED/)
      expect(s!.sensitivity).toBeCloseTo(s!.true_positives / s!.positives, 3)
      expect(s!.specificity).toBeCloseTo(s!.true_negatives / s!.negatives, 3)
    }
  })

  it('lists IEC 60601 for hardware, IEC 62304 for software and IEC 62366-1 for every device', () => {
    for (const p of P) {
      const stds = new Set(p.vv.protocols.map((t) => t.standard))
      expect(stds).toContain('IEC 62366-1')
      if (p.overview.software) expect(stds).toContain('IEC 62304')
      if (p.design.software) expect(['A', 'B', 'C']).toContain(p.design.software.iec62304_class)
    }
    expect(P.some((p) => p.vv.protocols.some((t) => t.standard === 'IEC 60601-1-2'))).toBe(true)
  })
})

const text = (html: string) => html.replace(/<[^>]+>/g, ' ').replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/\s+/g, ' ')
const noop = () => {}
const page = (id: string, tab: ProfileTab) =>
  renderToStaticMarkup(<DeviceProfilePage file={F} company={C} id={id} tab={tab} onTab={noop} onBack={noop} onEvidence={noop} />)

describe('device profile page', () => {
  it.each(C.devices.map((d) => d.id))('%s: every tab renders with the SIMULATED label and no banned wording', (id) => {
    const p = F.profiles[id]
    for (const t of PROFILE_TABS) {
      const html = page(id, t)
      const tx = text(html)
      expect(html).toContain('data-testid="profile-banner"')
      expect(tx).toContain(SIM_LABEL)
      expect(tx).toContain(p.name)
      expect(html.match(/role="tabpanel"/g)).toHaveLength(1)
      expect(html.match(/aria-selected="true"/g)).toHaveLength(1)
      // The real FDA box (MAUDE pattern labels) is checked apart; the simulated text must never use these words.
      const simOnly = tx.split('Real FDA data · MAUDE')[0]
      expect(simOnly).not.toMatch(BANNED)
      expect(profileTitle(p, t)).toContain(SIM_LABEL)
    }
  })

  it('says the decision with the pathway word on Overview and Regulatory', () => {
    for (const p of P) {
      const tx = text(page(p.id, 'regulatory')) + text(page(p.id, 'overview'))
      for (const v of ['cleared', 'granted', 'approved'].filter((x) => x !== DECISION_VERB[p.overview.pathway])) expect(tx, `${p.id} ${v}`).not.toMatch(new RegExp(`\\b${v}\\b`, 'i'))
      if (p.regulatory.decision) expect(tx).toMatch(new RegExp(`\\b${DECISION_VERB[p.overview.pathway]}\\b`))
    }
  })

  it('shows the real FDA classification and real MAUDE patterns apart from the simulated data, with their source', () => {
    const p = P.find((x) => x.product_code === 'LLZ')!
    const ov = page(p.id, 'overview')
    expect(ov).toContain('data-testid="real-classification"')
    expect(text(ov)).toContain('System, Image Processing, Radiological')
    expect(text(ov)).toContain('21 CFR 892.2050')
    const pm = page(p.id, 'postmarket')
    expect(pm).toContain('data-testid="real-patterns"')
    expect(pm).toContain('data-testid="sim-postmarket"')
    expect(pm.indexOf('data-testid="sim-postmarket"')).toBeLessThan(pm.indexOf('data-testid="real-patterns"'))
    expect(text(pm)).toMatch(/Real FDA data · MAUDE · product code LLZ/)
    expect(pm).toContain('https://api.fda.gov/device/event.json')
    const ote = P.find((x) => x.product_code === 'OTE')!
    expect(text(page(ote.id, 'overview'))).toMatch(/Regulation number Not in stored data/)
  })

  it('draws the timeline, the complaints chart and the failed-and-redone test', () => {
    const post = P.find((p) => p.overview.stage === 'post_market' && p.vv.problems.length > 0)!
    expect(page(post.id, 'overview')).toContain('data-testid="timeline"')
    expect(page(post.id, 'postmarket')).toContain('data-testid="complaints-chart"')
    const vv = page(post.id, 'vv')
    expect(vv).toContain('data-result="fail"')
    expect(text(vv)).toMatch(/Retest .* Pass/)
  })

  it('says an unknown device has no profile', () => {
    const html = renderToStaticMarkup(<DeviceProfilePage file={F} company={C} id="NOPE" tab="overview" onTab={noop} onBack={noop} onEvidence={noop} />)
    expect(html).toContain('data-testid="profile-missing"')
    expect(text(html)).toContain(SIM_LABEL)
  })

  it('sets the document title with the SIMULATED label and restores it', () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    document.title = 'MaudeSignal workspace'
    const root = createRoot(host)
    act(() => root.render(<DeviceProfilePage file={F} company={C} id="DMC-03" tab="regulatory" onTab={noop} onBack={noop} onEvidence={noop} />))
    expect(document.title).toContain(SIM_LABEL)
    expect(document.title).toContain('Lumenar Renal Assist')
    act(() => root.unmount())
    expect(document.title).toBe('MaudeSignal workspace')
    host.remove()
  })

  it('has one label per tab and the tab ids of the router', () => {
    expect(PROFILE_TAB_LABELS.map((t) => t.id)).toEqual([...PROFILE_TABS])
  })
})

describe('Our devices tiles', () => {
  it('counts stages, open CAPAs and devices needing a decision from the data', () => {
    const s = summarize(F, C)
    expect(s.development + s.review + s.decided + s.market).toBe(12)
    expect(s.development).toBe(P.filter((p) => p.overview.stage === 'development').length)
    expect(s.review).toBe(P.filter((p) => p.overview.stage === 'under_review').length)
    expect(s.openCapas).toBe(P.flatMap((p) => p.postmarket.capas).filter((c) => c.state === 'open').length)
    expect(s.needDecision).toBe(C.devices.filter((d) => d.status?.label === 'Needs review').length)
    const html = renderToStaticMarkup(<DeviceTiles file={F} company={C} />)
    expect(text(html)).toContain('At a glance (simulated)')
    expect(html).toContain('data-testid="tile-capas"')
  })
})

describe('profile addresses', () => {
  it.each(PROFILE_TABS.map((t) => [t] as const))('/devices/DMC-01 %s round-trips', (t) => {
    const r = { page: 'profile', id: 'DMC-01', tab: t } as const
    expect(parseRoute(`/${formatRoute(r)}`)).toEqual(r)
  })
  it('opens Overview at /devices/<id>; the old device tabs keep their addresses', () => {
    expect(parseRoute('/devices/DMC-07')).toEqual({ page: 'profile', id: 'DMC-07', tab: 'overview' })
    expect(formatRoute({ page: 'profile', id: 'DMC-07', tab: 'overview' })).toBe('devices/DMC-07')
    expect(parseRoute('/devices/DMC-07/nope')).toEqual({ page: 'profile', id: 'DMC-07', tab: 'overview' })
    expect(parseRoute('/devices/apply/DMC-03')).toEqual({ page: 'devices', tab: 'apply', device: 'DMC-03' })
    expect(parseRoute('/devices/yours')).toEqual({ page: 'devices', tab: 'yours' })
    expect(parseRoute('/devices')).toEqual({ page: 'devices', tab: 'apply' })
  })
  it('is covered by the Vercel rewrites', () => {
    const v = JSON.parse(readFileSync(resolve(__dirname, '../../vercel.json'), 'utf8')) as { rewrites: { source: string }[] }
    expect(v.rewrites.map((r) => r.source)).toContain('/devices/:path*')
  })
})

// --- PMS decision paths (simulated) ---------------------------------------------------------------

const PATHS = P.flatMap((p) => p.decision.paths.map((x) => ({ p, x })))
const DEVICE = Object.fromEntries(C.devices.map((d) => [d.id, d]))
const outcomeOf = (x: (typeof PATHS)[number]['x']) => x.outcome?.kind ?? null
const RA_NAMES = ['Priya Natarajan', 'Gideon Mbeki-Hart', 'Colette Duval']
const compact = (s: string) => `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`

describe('decision paths: data rules', () => {
  it('has paths for devices with a signal and none for "Not applicable" or devices with nothing stored', () => {
    for (const p of P) {
      const d = DEVICE[p.id]
      if (d.status?.label === 'Not applicable to our device') {
        expect(p.decision.paths).toHaveLength(0)
        expect(p.decision.none_reason).toBeTruthy()
      } else if (d.patterns.length === 0 && d.status?.label !== 'Needs review') {
        expect(p.decision.paths).toHaveLength(0)
        expect(p.decision.none_reason).toBeTruthy()
      } else {
        expect(p.decision.paths.length, p.id).toBeGreaterThanOrEqual(1)
        expect(p.decision.none_reason).toBeNull()
        for (const pt of d.patterns) expect(p.decision.paths.map((x) => x.signal.pattern_id), `${p.id} ${pt.id}`).toContain(pt.id)
      }
      for (const x of p.decision.paths) if (x.signal.kind === 'pattern') expect(d.patterns.map((q) => q.id)).toContain(x.signal.pattern_id)
    }
  })

  it('says, for DMC-10, that "not applicable" covers only the display pattern and the wrong-result pattern stays unaddressed', () => {
    const r = F.profiles['DMC-10'].decision.none_reason!
    expect(r).toMatch(/display pattern/)
    expect(r).toMatch(/29/)
    expect(r).toMatch(/no decision path yet/)
    expect(DEVICE['DMC-10'].patterns.find((q) => q.id === 'DQK-wrong-result')?.count).toBe(29)
  })

  it('opens exactly one path per "Needs review" device, and none anywhere else', () => {
    const open = PATHS.filter(({ x }) => x.state === 'open')
    const need = C.devices.filter((d) => d.status?.label === 'Needs review').map((d) => d.id)
    expect(open.map(({ p }) => p.id).sort()).toEqual([...need].sort())
    for (const { x } of open) {
      expect(x.outcome).toBeNull()
      expect(x.risk).toBeNull()
    }
    for (const { x } of PATHS.filter(({ x }) => x.state === 'decided')) {
      expect(x.outcome).not.toBeNull()
      expect(x.risk).not.toBeNull()
    }
  })

  it('keeps the dates of a path in order and never past the as-of date unless planned', () => {
    for (const { p, x } of PATHS) {
      expect(x.triage.date <= x.board.date, `${x.id} triage<=board`).toBe(true)
      expect(x.board.held, x.id).toBe(x.board.date <= F.as_of)
      expect(x.board.planned).toBe(x.board.date > F.as_of)
      expect(x.triage.date <= F.as_of).toBe(true)
      if (x.outcome) {
        expect(x.board.held).toBe(true)
        expect(x.outcome.date >= x.board.date, `${x.id} board<=outcome`).toBe(true)
        expect(x.outcome.date <= F.as_of).toBe(true)
      }
      if (x.risk) expect(x.risk.risk_file.date >= x.outcome!.date, `${x.id} outcome<=risk file`).toBe(true)
      if (!x.board.held) expect(x.board.decision).toBeNull()
      expect(x.id.startsWith(`DP-${p.id}-`)).toBe(true)
    }
  })

  it('dates every path after its signal existed and after the device was registered', () => {
    for (const { p, x } of PATHS) {
      const d = DEVICE[p.id]
      const reg = d.history[0].date
      expect(x.triage.date >= reg, `${x.id} triage ${x.triage.date} before the registration ${reg}`).toBe(true)
      if (x.signal.kind === 'pattern') {
        const pt = d.patterns.find((q) => q.id === x.signal.pattern_id)!
        expect(pt.last_received).toBeTruthy()
        expect(x.triage.date >= compact(pt.last_received!), `${x.id} triage before the pattern's last report`).toBe(true)
        const run = /recorded run (\d{8})T/.exec(pt.basis)
        if (run) expect(x.triage.date >= compact(run[1]), `${x.id} triage before the investigator run`).toBe(true)
      } else {
        expect(x.triage.date >= compact(d.sweep!.as_of), `${x.id} triage before the sweep`).toBe(true)
      }
      if (x.outcome?.kind === 'escalation' && x.outcome.mdr.receipt_date) expect(x.outcome.mdr.receipt_date <= x.triage.date).toBe(true)
    }
  })

  it('tags every step with the clauses it serves, each with a reason', () => {
    for (const { x } of PATHS) {
      const sets = [x.triage.tags, x.board.tags, ...(x.outcome ? [x.outcome.tags] : []), ...(x.risk ? [x.risk.tags] : [])]
      for (const tags of sets) {
        expect(tags.length).toBeGreaterThanOrEqual(1)
        for (const t of tags) {
          expect(t.tag).toMatch(/^(21 CFR (820 \(QMSR\)|803|806|7)|ISO 13485 §8\.(2\.[123]|5\.2)|ISO 14971)$/)
          expect(t.why.length).toBeGreaterThan(30)
        }
      }
      const tag = (t: { tag: string }[]) => t.map((z) => z.tag)
      expect(tag(x.triage.tags)).toContain('ISO 13485 §8.2.2')
      if (x.outcome?.kind === 'capa') expect(tag(x.outcome.tags)).toContain('ISO 13485 §8.5.2')
      if (x.outcome?.kind === 'ntf') expect(tag(x.outcome.tags)).toContain('ISO 13485 §8.2.2')
      if (x.outcome?.kind === 'escalation') for (const c of ['21 CFR 803', '21 CFR 806', '21 CFR 7']) expect(tag(x.outcome.tags)).toContain(c)
      if (x.risk) expect(tag(x.risk.tags)).toEqual(['ISO 14971'])
    }
  })

  const esc = (): Escalation[] => {
    const out: Escalation[] = []
    for (const { x } of PATHS) if (x.outcome?.kind === 'escalation') out.push(x.outcome)
    return out
  }

  it('has the realistic mix: mostly notes to file, 2-3 CAPAs, exactly one MDR-reportable, exactly one recall ruled out', () => {
    const decided = PATHS.filter(({ x }) => x.state === 'decided')
    const kinds = decided.map(({ x }) => outcomeOf(x))
    expect(kinds.filter((k) => k === 'ntf').length).toBeGreaterThan(decided.length / 2)
    const capas = kinds.filter((k) => k === 'capa').length + esc().filter((o) => o.follow_up_capa).length
    expect(capas).toBeGreaterThanOrEqual(2)
    expect(capas).toBeLessThanOrEqual(3)
    expect(esc().filter((o) => o.mdr.result === 'reportable')).toHaveLength(1)
    expect(esc().filter((o) => o.recall.result === 'recall not warranted')).toHaveLength(1)
    const ruledOut = PATHS.find(({ x }) => x.outcome?.kind === 'escalation' && x.outcome.recall.result === 'recall not warranted')!
    expect(ruledOut.p.id).toBe('DMC-01')
    const mdr = PATHS.find(({ x }) => x.outcome?.kind === 'escalation' && x.outcome.mdr.result === 'reportable')!
    expect(mdr.p.id).toBe('DMC-06')
    for (const o of esc()) {
      expect(['reportable', 'not reportable']).toContain(o.mdr.result)
      expect(['reportable', 'not reportable']).toContain(o.correction_removal.result)
      expect(o.recall.result).toMatch(/^(recall not warranted|correction handled as a recall action; classification left to FDA)$/)
      for (const a of [o.mdr, o.correction_removal, o.recall]) expect(a.rationale.length).toBeGreaterThan(40)
      expect(o.assessed_by).toBe('the board')
    }
  })

  it('keeps the MDR path coherent: reportable event, reportable correction, recall not ruled out, a linked CAPA', () => {
    const o = esc().find((e) => e.mdr.result === 'reportable')!
    expect(o.correction_removal.result).toBe('reportable')
    expect(o.correction_removal.rationale).toMatch(/10 working days/)
    expect(o.recall.result).toMatch(/classification left to FDA/)
    expect(o.recall.rationale).not.toMatch(/ruled out as not warranted/)
    expect(o.follow_up_capa).not.toBeNull()
    const p = P.find((q) => q.id === 'DMC-06')!
    const c = p.postmarket.capas.find((q) => q.id === o.follow_up_capa!.capa_id)!
    expect(c.owner).toBe(o.follow_up_capa!.owner)
    expect(c.opened).toBe(o.date)
    expect(c.state).toBe('open')
  })

  it('never leaves a "not acceptable" starting risk with only a CAPA or a note to file', () => {
    for (const { x } of PATHS) {
      if (!x.risk || x.risk.before.zone !== 'not acceptable') continue
      expect(x.outcome?.kind, x.id).toBe('escalation')
      expect((x.outcome as Escalation).follow_up_capa).not.toBeNull()
    }
    for (const { x } of PATHS) if (x.outcome?.kind === 'capa') expect(x.risk!.before.score).toBeLessThanOrEqual(9)
  })

  it('explains the 30-day clock as running from the company receipt, inside the as-of date', () => {
    const mdr = esc().find((o) => o.mdr.result === 'reportable')!
    const m = mdr.mdr
    expect(m.clock_note).toMatch(/became aware/)
    expect(m.clock_note).toMatch(/receipt/)
    expect(m.clock_note).toMatch(/not\s+run from the date any report appears in FDA's database/)
    expect(days(m.receipt_date!, m.due_date!)).toBe(30)
    expect(m.submitted_date! <= m.due_date!).toBe(true)
    expect(m.submitted_date! >= m.receipt_date!).toBe(true)
    expect(m.day_of_30).toBe(days(m.receipt_date!, m.submitted_date!))
    expect(m.submitted_date! <= F.as_of).toBe(true)
    expect(m.receipt_date! <= mdr.date).toBe(true)
  })

  it('ties a CAPA outcome to a CAPA of the device', () => {
    for (const { p, x } of PATHS) {
      const o = x.outcome
      const link = o?.kind === 'capa' ? o : o?.kind === 'escalation' ? o.follow_up_capa : null
      if (!link) continue
      expect(link.capa_id).toMatch(/^CAPA-SIM-\d{4}$/)
      const c = p.postmarket.capas.find((q) => q.id === link.capa_id)
      expect(c, `${p.id} ${link.capa_id}`).toBeDefined()
      expect(c!.owner).toBe(link.owner)
      expect(c!.opened).toBe(o!.date)
    }
    for (const p of P) for (const c of p.postmarket.capas) expect(c.id).toMatch(/^CAPA-SIM-\d{4}$/)
  })

  it('closes a CAPA no sooner than 90 days after opening it', () => {
    for (const p of P) for (const c of p.postmarket.capas) if (c.closed) expect(days(c.opened, c.closed), c.id).toBeGreaterThanOrEqual(90)
  })

  it('signs an escalation by Regulatory Affairs and a note to file by Quality Engineering', () => {
    for (const { x } of PATHS) {
      const o = x.outcome
      if (o?.kind === 'escalation') {
        expect(o.signed_role).toBe('Regulatory Affairs')
        expect(RA_NAMES).toContain(o.signed_by.replace(' (simulated)', ''))
      }
      if (o?.kind === 'ntf') expect(o.signed_role).toBe('Quality Engineering')
    }
  })

  it('uses "board decided / assessed / documented / signed" wording and never has the tool decide', () => {
    const all = strings(P.map((p) => p.decision)).join('\n')
    expect(all).not.toMatch(/maudesignal (determined|decided)/i)
    expect(all).not.toMatch(/\btool (determined|decided)\b/i)
    expect(all).not.toMatch(/\b(fda[- ]approved|validated|unsafe|draft capa)\b/i)
    expect(all).not.toMatch(/\bsafe\b/i)
    for (const { x } of PATHS) {
      if (x.outcome?.kind === 'ntf') expect(x.outcome.signed_by).toMatch(/\(simulated\)$/)
      for (const a of x.board.attendees) {
        expect(a.name).toMatch(/\(simulated\)$/)
        expect(a.role.length).toBeGreaterThan(3)
      }
      expect(x.triage.owner).toMatch(/\(simulated\)$/)
    }
  })

  it('does not state an unreviewed keyword pattern as fact', () => {
    for (const { p, x } of PATHS) {
      if (x.signal.kind !== 'pattern') continue
      const pt = DEVICE[p.id].patterns.find((q) => q.id === x.signal.pattern_id)!
      if (pt.kind !== 'keyword') continue
      expect(x.board.summary, x.id).toMatch(/keyword[- ]match/i)
    }
  })

  it('draws the risk cell before and after on the 5x5 scale, with one severity scale everywhere', () => {
    const scale = ['Negligible', 'Minor', 'Serious', 'Critical', 'Catastrophic']
    for (const { x } of PATHS) {
      if (!x.risk) continue
      for (const c of [x.risk.before, x.risk.after]) {
        expect(c.severity).toBeGreaterThanOrEqual(1)
        expect(c.severity).toBeLessThanOrEqual(5)
        expect(c.probability).toBeGreaterThanOrEqual(1)
        expect(c.probability).toBeLessThanOrEqual(5)
        expect(c.score).toBe(c.severity * c.probability)
        expect(scale[c.severity - 1]).toBe(c.severity_label)
      }
    }
    for (const p of P) for (const h of p.design.hazards) expect(scale, `${p.id} ${h.id} ${h.severity}`).toContain(h.severity)
  })

  it('does not give the no-alarm monitor alarm inputs, tests or hazards', () => {
    const p = F.profiles['DMC-12']
    const text = JSON.stringify([p.design.inputs, p.design.outputs, p.design.hazards, p.vv.protocols, p.postmarket.categories, p.overview.intended_use])
    expect(text).not.toMatch(/alarm/i.test(p.overview.intended_use) ? /IEC 60601-1-8|Alarm system|Alarm not raised|Alarm behaviour/ : /IEC 60601-1-8|Alarm system|Alarm not raised|Alarm behaviour|with alarms/)
    expect(text).not.toMatch(/60601-1-8/)
    expect(p.overview.intended_use).toMatch(/no alarms/)
    // devices that do have alarms keep them
    expect(JSON.stringify(F.profiles['DMC-08'].vv.protocols)).toMatch(/60601-1-8/)
  })

  it('gives the DMC-06 software class C (it can contribute to serious injury) and the X-ray device a radiation-dose hazard', () => {
    expect(F.profiles['DMC-06'].design.software?.iec62304_class).toBe('C')
    const ote = F.profiles['DMC-07']
    expect(ote.design.hazards.map((h) => h.hazard).join(' ')).toMatch(/radiation dose/)
    expect(JSON.stringify(ote.design.hazards)).not.toMatch(/burn|tissue heating/i)
  })

  it('uses a major-deficiency letter for PMA and an Additional Information request for the other pathways', () => {
    for (const p of P) {
      const labels = p.milestones.filter((m) => m.key === 'ai_request' || m.key === 'ai_response').map((m) => m.label).join(' | ')
      if (p.overview.pathway === 'PMA') {
        expect(labels).toMatch(/major deficiency letter/)
        expect(labels).not.toMatch(/Additional Information/)
        expect(p.activity.map((a) => a.action).join(' ')).not.toMatch(/Additional Information|AI request/)
      } else if (p.milestones.some((m) => m.key === 'ai_request')) expect(labels).toMatch(/Additional Information/)
    }
  })

  it('makes DMC-05 a 510(k) and keeps "granted" out of any 510(k) device', () => {
    expect(F.profiles['DMC-05'].overview.pathway).toBe('510(k)')
    for (const p of P) if (p.overview.pathway !== 'De Novo') expect(JSON.stringify([p.overview, p.regulatory, p.milestones])).not.toMatch(/\bgranted\b/i)
  })
})

describe('decision paths: rendering', () => {
  const pageOf = (id: string, tab: ProfileTab = 'postmarket') => page(id, tab)

  it('shows every path of every device with four steps, one summary line each, real FDA evidence apart', () => {
    for (const p of P) {
      const html = pageOf(p.id)
      if (p.decision.paths.length === 0) {
        expect(html).toContain('data-testid="no-decision-path"')
        continue
      }
      expect(html).toContain('data-testid="decision-paths"')
      expect(html.match(/data-testid="decision-path"/g)).toHaveLength(p.decision.paths.length)
      expect(html.match(/data-testid="dp-step"/g)).toHaveLength(p.decision.paths.length * 4)
      expect(html.match(/data-testid="step-summary"/g)).toHaveLength(p.decision.paths.length * 4)
      expect(html.match(/data-testid="dp-real"/g)).toHaveLength(p.decision.paths.length)
      expect(text(html)).toContain('Real FDA data · openFDA · product code ' + p.product_code)
      expect(text(html)).toContain('Company side')
      expect(html.indexOf('data-testid="sim-postmarket"')).toBeLessThan(html.indexOf('data-testid="decision-paths"'))
      expect(html.indexOf('data-testid="decision-paths"')).toBeLessThan(html.indexOf('data-testid="real-patterns"'))
      expect(html).toContain('data-testid="clause-chip"')
      expect(html).toContain('data-testid="open-decision-path"')
      expect(html).toContain('Show details')
    }
  })

  it('expands only the open path; the decided ones are one line', () => {
    const html = pageOf('DMC-06')
    const cards = html.split('data-testid="decision-path"').slice(1)
    expect(cards).toHaveLength(3)
    // the attribute order is: class, id, open, ...; the opening tag of each card is before the testid
    const tags = html.match(/<details class="ms2-dp"[^>]*>/g)!
    expect(tags.filter((t) => / open=""/.test(t))).toHaveLength(1)
    expect(tags.find((t) => / open=""/.test(t))).toContain('data-state="open"')
  })

  it('puts the chips in the board\'s words: "Board assessed: reportable", "Board: recall not warranted", "Decision due"', () => {
    expect(text(pageOf('DMC-06'))).toMatch(/Board assessed: reportable/)
    expect(text(pageOf('DMC-01'))).toMatch(/Board: recall not warranted/)
    expect(text(pageOf('DMC-06'))).toMatch(/Decision due/)
  })

  it('shows the stored openFDA link of the pattern on the board step, and keeps "keyword match" in the heading', () => {
    const html = pageOf('DMC-01')
    expect(html).toContain('https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfmaude/detail.cfm?mdrfoi__id=')
    expect(text(html)).toMatch(/MAUDE reports, received/)
    const k = text(pageOf('DMC-06'))
    expect(k).toMatch(/\(keyword match\)/)
    expect(text(pageOf('DMC-09'))).toMatch(/\(keyword match\)/)
  })

  it('says exactly what the sweep numbers are', () => {
    const tx = text(pageOf('DMC-08'))
    expect(tx).toMatch(/Weekly AI-device sweep/)
    expect(tx).toMatch(/reports in the 7 days to that date, and 29 in the 28 days before \(about 7 a week\)/)
    expect(text(pageOf('DMC-08'))).toMatch(/Decision due/)
  })

  it('writes the board assessments in words for the MDR path', () => {
    const html = pageOf('DMC-06')
    const tx = text(html)
    expect(tx).toMatch(/MDR reportability 21 CFR 803 Assessed by the board: reportable/)
    expect(tx).toMatch(/Correction or removal 21 CFR 806 Assessed by the board: reportable/)
    expect(tx).toMatch(/Recall consideration 21 CFR 7 Assessed by the board: correction handled as a recall action; classification left to FDA/)
    expect(tx).toMatch(/The 30-day clock\./)
    expect(tx).toMatch(/CAPA opened: CAPA-SIM-0602/)
    expect(html).toContain('data-testid="risk-grid"')
    expect(tx).toMatch(/Simulated risk file records: \(not acceptable\)/)
    expect(tx).toMatch(/Low \(1–4\): acceptable/)
  })

  it('has the quiet investigate link with the code and the device, keeping ?r= and the layout', () => {
    const html = page('DMC-06', 'overview')
    expect(html).toContain('data-testid="investigate-link"')
    expect(text(html)).toContain('Investigate a complaint on this device')
    const loc = { pathname: '/devices/DMC-06', search: '?layout=v2&r=TEST1' }
    const href = investigateHref('IYN', 'DMC-06', loc, undefined)
    const u = new URL(href, 'https://x.test')
    expect(u.pathname).toBe('/investigate')
    expect(u.searchParams.get('code')).toBe('IYN')
    expect(u.searchParams.get('device')).toBe('DMC-06')
    expect(u.searchParams.get('r')).toBe('TEST1')
    expect(u.searchParams.get('layout')).toBe('v2')
    expect(href.startsWith('/investigate?code=IYN&device=DMC-06')).toBe(true)
    expect(new URL(investigateHref('IYN', 'DMC-06', { pathname: '/devices/DMC-06', search: '' }, undefined), 'https://x.test').searchParams.get('layout')).toBe('v2')
    expect(investigateHref('IYN', 'DMC-06', { pathname: '/app/devices/DMC-06/vv', search: '' }, 'v2').startsWith('/app/investigate?')).toBe(true)
  })

  it('rewrites /investigate and /investigate/<path> to the app in vercel.json', () => {
    const v = JSON.parse(readFileSync(resolve(__dirname, '../../vercel.json'), 'utf8')) as { rewrites: { source: string; destination: string }[] }
    for (const s of ['/investigate', '/investigate/:path*']) expect(v.rewrites.find((r) => r.source === s)?.destination).toBe('/index.html')
  })

  it('counts "Decisions due" from the open decision paths and says how many devices', () => {
    const s = summarize(F, C)
    expect(s.needDecision).toBe(PATHS.filter(({ x }) => x.state === 'open').length)
    expect(s.needDecision).toBe(C.devices.filter((d) => d.status?.label === 'Needs review').length)
    const tx = text(renderToStaticMarkup(<DeviceTiles file={F} company={C} />))
    expect(tx).toContain('Decisions due')
    expect(tx).not.toContain('open decision paths')
    expect(tx).toContain(`on ${s.needDecisionDevices} devices`)
    expect(tx).toContain('Open CAPAs')
  })

  it('draws the complaints chart as a labelled list with every month, readable as text', () => {
    const html = pageOf('DMC-06')
    expect(html.match(/data-testid="complaints-row"/g)).toHaveLength(F.profiles['DMC-06'].postmarket.complaints_by_month.length)
    expect(html).toMatch(/aria-label="Complaints per month, Nov 2025 to Oct 2026: Nov 2025 \d+, Dec 2025/)
    expect(html).not.toContain('<svg viewBox="0 0 600')
  })

  it('shows the failure, the fix and the retest as one story under the failed test', () => {
    const html = pageOf('DMC-06', 'vv')
    expect(html.match(/data-testid="problem-story"/g)).toHaveLength(1)
    const tx = text(html)
    expect(tx).toMatch(/Problem found .*What changed: .*Retest after change DC-21: TP-221R .* Pass/)
    expect(html.match(/data-testid="protocol"/g)).toHaveLength(F.profiles['DMC-06'].vv.protocols.length - 1)
  })
})

describe('wording on sign-offs', () => {
  it('uses "approved" only for the PMA device, and "design validation" only as a test name', () => {
    for (const p of P) {
      const t = JSON.stringify(p)
      if (p.overview.pathway !== 'PMA') expect(t, p.id).not.toMatch(/approv/i)
      const without = JSON.stringify({ ...p, vv: { ...p.vv, protocols: p.vv.protocols.map((x) => ({ ...x, title: '' })) } })
      expect(without, p.id).not.toMatch(/design validation/i)
    }
    const pma = P.filter((p) => p.overview.pathway === 'PMA')
    expect(pma.length).toBeGreaterThanOrEqual(1)
    const reviews = P.flatMap((p) => p.design.reviews.map((r) => r.outcome))
    expect(new Set(reviews)).toEqual(new Set(['Accepted, actions closed', 'Planned']))
  })

  it('puts "(simulated)" in the title of every card that holds simulated data', () => {
    for (const tab of ['design', 'vv', 'regulatory', 'market'] as ProfileTab[]) {
      const html = page('DMC-06', tab)
      const titles = [...html.matchAll(/<section class="ms2-card[^"]*" aria-label="([^"]+)"/g)].map((m) => m[1])
      expect(titles.length).toBeGreaterThan(0)
      for (const t of titles) if (!/^Real FDA data/.test(t)) expect(t, `${tab}: ${t}`).toMatch(/\(simulated\)/)
    }
    expect(page('DMC-06', 'overview')).toContain('data-testid="sim-chip"')
  })

  it('shows the risk grid in every decided path without opening "Show details"', () => {
    const html = page('DMC-01', 'postmarket')
    const grids = html.match(/data-testid="risk-grid"/g) ?? []
    expect(grids).toHaveLength(F.profiles['DMC-01'].decision.paths.filter((x) => x.risk).length)
    const step4 = html.split('data-step="risk"')[1]
    expect(step4.indexOf('data-testid="risk-grid"')).toBeLessThan(step4.indexOf('Show details'))
  })
})
