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
import { DECISION_VERB, SIM_LABEL, summarize, type DeviceProfile, type ProfilesFile } from './profiles'
import { formatRoute, parseRoute, PROFILE_TABS, type ProfileTab } from './router'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const C = company as unknown as Company
const F = raw as unknown as ProfilesFile
const P = Object.values(F.profiles)
const TODAY = new Date().toISOString().slice(0, 10)
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
      if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)) out.push({ path: `${path}.${k}`, date: v, planned: k === 'date' && typeof r.planned === 'boolean' ? (r.planned as boolean) : null })
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
        expect(o.classification_source).toMatch(/MAUDE reports stored in data\/demo\/maudesignal_demo\.db|not in stored data/)
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
    expect(new Set(P.map((p) => p.overview.pathway))).toEqual(new Set(['510(k)', 'De Novo', 'PMA']))
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
    expect(F.as_of <= TODAY).toBe(true)
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
      expect(html).toContain('data-testid="sim-tab-label"')
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
    expect(text(html)).toContain(SIM_LABEL)
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
