// @vitest-environment jsdom
// Noctua: every state, priority, transient states, bubble once per session, SVG/CSS rules (tokens only, reduced motion),
// and the evidence rule: the mascot never appears in dossier, audit, artifact, PDF or API code or output.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { MascotOwl, NOCTUA_TITLE, mascotBubbleFirst, resetMascotBubble, useMascotBubble } from './MascotOwl'
import {
  CAPTIONS,
  FORBIDDEN_CAPTION,
  MASCOT_STATES,
  STATE_PRIORITY,
  TRANSIENT_MS,
  isTransient,
  resolveState,
  type MascotState,
} from './mascotStates'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const HERE = resolve(__dirname)
const WEB_SRC = resolve(HERE, '../..')
const REPO = resolve(WEB_SRC, '../..')
const css = readFileSync(join(HERE, 'mascot.css'), 'utf8')

let host: HTMLDivElement
let root: Root
beforeEach(() => {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  resetMascotBubble()
})
afterEach(() => {
  act(() => root.unmount())
  host.remove()
})

describe('states and priority', () => {
  it('has the seven core states', () => {
    expect([...MASCOT_STATES].sort()).toEqual(['alert', 'idle', 'listening', 'success', 'thinking', 'watching', 'withheld'])
  })
  it('resolves priority alert > listening > thinking > withheld > success > watching > idle', () => {
    expect(STATE_PRIORITY).toEqual(['alert', 'listening', 'thinking', 'withheld', 'success', 'watching', 'idle'])
    const all = Object.fromEntries(MASCOT_STATES.map((s) => [s, true]))
    expect(resolveState(all)).toBe('alert')
    expect(resolveState({ ...all, alert: false })).toBe('listening')
    expect(resolveState({ ...all, alert: false, listening: false })).toBe('thinking')
    expect(resolveState({ success: true, withheld: true, watching: true })).toBe('withheld')
    expect(resolveState({ success: true, watching: true })).toBe('success')
    expect(resolveState({ watching: true })).toBe('watching')
    expect(resolveState({})).toBe('idle')
  })
  it('success and withheld are transient (2-3 s); the others are not', () => {
    expect(TRANSIENT_MS).toBeGreaterThanOrEqual(2000)
    expect(TRANSIENT_MS).toBeLessThanOrEqual(3000)
    expect(MASCOT_STATES.filter(isTransient).sort()).toEqual(['success', 'withheld'])
    // A finished transient state falls back to the underlying one.
    expect(resolveState({ watching: true, success: false })).toBe('watching')
  })
  it.each(MASCOT_STATES)('renders the %s state class and is aria-hidden', (s: MascotState) => {
    act(() => root.render(<MascotOwl state={s} />))
    const svg = host.querySelector('svg') as SVGElement
    expect(svg.getAttribute('data-state')).toBe(s)
    expect(svg.getAttribute('aria-hidden')).toBe('true')
    expect(svg.getAttribute('viewBox')).toBe('0 0 64 64')
    expect(svg.querySelector('title')).toBeNull()
    expect(css).toContain(`.ms-noctua[data-state='${s}']`.replace("[data-state='idle']", "[data-state='idle']"))
  })
  it('defaults to idle', () => {
    act(() => root.render(<MascotOwl />))
    expect(host.querySelector('svg')?.getAttribute('data-state')).toBe('idle')
  })
})

describe('markup', () => {
  it('the logo gets the title and role img; nothing else does', () => {
    act(() => root.render(<MascotOwl logo />))
    const svg = host.querySelector('svg') as SVGElement
    expect(svg.getAttribute('role')).toBe('img')
    expect(svg.querySelector('title')?.textContent).toBe(NOCTUA_TITLE)
    expect(svg.getAttribute('aria-hidden')).toBeNull()
  })
  it('hideMascot renders nothing', () => {
    act(() => root.render(<MascotOwl hideMascot />))
    expect(host.innerHTML).toBe('')
  })
  it('has two equal eyes, a beak, two wings; wings drop at 24px and below', () => {
    act(() => root.render(<MascotOwl size={24} />))
    expect(host.querySelectorAll('.ms-noctua-eye')).toHaveLength(2)
    expect(host.querySelectorAll('.ms-noctua-wing')).toHaveLength(2)
    expect(host.querySelectorAll('.ms-noctua-beak')).toHaveLength(1)
    const [a, b] = Array.from(host.querySelectorAll('.ms-noctua-eye'))
    expect(a?.getAttribute('r')).toBe(b?.getAttribute('r'))
    expect(host.querySelector('svg')?.classList.contains('ms-noctua--tiny')).toBe(true)
    act(() => root.render(<MascotOwl size={32} />))
    expect(host.querySelector('svg')?.classList.contains('ms-noctua--tiny')).toBe(false)
  })
  it('is small, with no hard-coded colour in the markup', () => {
    act(() => root.render(<MascotOwl />))
    const html = host.innerHTML
    expect(html.length).toBeLessThan(5000)
    expect(html).not.toMatch(/#[0-9a-f]{3,8}\b/i)
    expect(html).not.toMatch(/\b(fill|stroke)="/)
    expect(html).not.toMatch(/<(image|foreignObject)/i)
  })
})

describe('CSS rules', () => {
  it('uses design tokens only: no hex, no rgb', () => {
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
    expect(css).not.toMatch(/\brgba?\(/)
  })
  it('turns every animation off under prefers-reduced-motion', () => {
    const block = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'))
    expect(block).toContain('animation: none !important')
    expect(block).toContain('.ms-noctua-lid')
  })
  it('never turns the body red and never flashes', () => {
    expect(css).not.toMatch(/ms-noctua-body\s*\{[^}]*(critical|warning|success)/)
    expect(css).not.toMatch(/--critical|--warning|--success/)
    // No animation faster than the 1.2 s alert/dot cycles, except the one-shot 0.8 s nod and the 120/80/160 ms blink inside 5 s.
    const durations = [...css.matchAll(/animation:\s*ms-noctua-[a-z-]+\s+([\d.]+)s[^;]*infinite/g)].map((m) => Number(m[1]))
    expect(durations.length).toBeGreaterThan(0)
    expect(Math.min(...durations)).toBeGreaterThanOrEqual(1.2)
  })
  it('high contrast has a black owl with no accent', () => {
    expect(css).toMatch(/\[data-theme='contrast'\] \.ms-noctua-pupil/)
  })
})

describe('captions', () => {
  it('are the three fixed captions and none says anything the owl must never say', () => {
    for (const c of Object.values(CAPTIONS)) expect(c).not.toMatch(FORBIDDEN_CAPTION)
    expect(CAPTIONS.alert).toBe('3 codes flagged this week. Here are the links.')
    expect(CAPTIONS.withheld).toBe('This sentence was withheld - it did not match a stored record.')
    expect(CAPTIONS.listening).toBe('Listening. I will transcribe, then check every sentence.')
  })
})

describe('bubble: once per session', () => {
  function Probe({ active }: { active: boolean }) {
    const [b] = useMascotBubble(active)
    return <span data-testid="b">{String(b)}</span>
  }
  it('opens by itself once, then only on request', () => {
    expect(mascotBubbleFirst()).toBe(true)
    expect(mascotBubbleFirst()).toBe(false)
    resetMascotBubble()
    act(() => root.render(<Probe active />))
    expect(host.textContent).toBe('auto')
    act(() => root.render(<Probe active={false} />))
    act(() => root.render(<Probe active />))
    expect(sessionStorage.getItem('ms-noctua-bubble-seen-v1')).toBe('1')
  })
  it('does not open when not active', () => {
    act(() => root.render(<Probe active={false} />))
    expect(host.textContent).toBe('false')
  })
})

/** Every .ts/.tsx/.py/.json file under dir, relative to the repo. */
function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === 'node_modules' || name === '__pycache__' || name.startsWith('.')) continue
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.(tsx?|py|css|json|html)$/.test(name)) out.push(p)
  }
  return out
}

describe('evidence rule: the mascot is branding only', () => {
  const EVIDENCE = /dossier|artifact|pdf|audit|connector|camera|vision|capture|trace/i
  it('no dossier, artifact, PDF, audit, connector, camera or trace file in the web app mentions the mascot', () => {
    const offenders = walk(WEB_SRC)
      .filter((p) => !p.includes(`${join('components', 'mascot')}`))
      .filter((p) => !/\.test\.tsx?$/.test(p))
      .filter((p) => EVIDENCE.test(relative(WEB_SRC, p)))
      .filter((p) => /mascot|noctua|MascotOwl/i.test(readFileSync(p, 'utf8')))
    expect(offenders.map((p) => relative(REPO, p))).toEqual([])
  })
  it('the Python dossier, audit export, copilot, gate and API code never mention the mascot', () => {
    const dirs = ['dossier', 'copilot', 'gate', 'monitor', 'connector', 'dashboard'].map((d) => join(REPO, 'src/maudesignal', d))
    const offenders = dirs.flatMap((d) => {
      try {
        return walk(d)
      } catch {
        return []
      }
    }).filter((p) => /data-mascot|ms-noctua|MascotOwl|\bNoctua\b/.test(readFileSync(p, 'utf8')))
    expect(offenders.map((p) => relative(REPO, p))).toEqual([])
  })
  it('the stored data and artifact files carry no mascot markup', () => {
    const data = join(REPO, 'web/public/data')
    const offenders = walk(data).filter((p) => /data-mascot|ms-noctua|MascotOwl/.test(readFileSync(p, 'utf8')))
    expect(offenders.map((p) => relative(REPO, p))).toEqual([])
  })
  it('only the TopBar and Home may import the mascot (allow-list)', () => {
    const allowed = new Set(['v2/TopBarV2.tsx', 'v2/HomeV2.tsx', 'v2/ThemeMenu.tsx', 'v2/NoctuaDock.tsx'])
    const importers = walk(WEB_SRC)
      .filter((p) => !p.includes(`${join('components', 'mascot')}`))
      .filter((p) => !/\.test\.tsx?$/.test(p))
      .filter((p) => /from\s+['"][^'"]*mascot\/(MascotOwl|mascotStates)['"]/.test(readFileSync(p, 'utf8')))
      .map((p) => relative(WEB_SRC, p).split('\\').join('/'))
    for (const f of importers) expect(allowed.has(f), `${f} may not import the mascot`).toBe(true)
  })
})
