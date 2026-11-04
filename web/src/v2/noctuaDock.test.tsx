// @vitest-environment jsdom
// PRD-34 companion dock: shown bottom-right, silent and decorative; Hide works everywhere; hero walk once per session on
// Home only; frozen on decision pages, while a modal is open and while typing; ducks away from anything it would cover;
// never on Home together with Home's own calm owl; CSS keeps it inside its dock area and static under reduced motion.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { noctuaHidden, setNoctuaHidden } from '../components/mascot/MascotOwl'
import { FROZEN_PAGES, NoctuaDock, firstWalk, freeWalk, rectCollides, resetWalk, wouldCover } from './NoctuaDock'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const css = readFileSync(resolve(__dirname, '../components/mascot/mascot.css'), 'utf8')

let host: HTMLDivElement
let root: Root
beforeEach(() => {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  setNoctuaHidden(false)
  resetWalk()
})
afterEach(() => {
  act(() => root.unmount())
  host.remove()
})
const dock = () => host.querySelector('[data-testid=noctua-dock]') as HTMLElement | null

describe('dock', () => {
  it('renders a silent decorative owl with only a 44px Hide button as a control', () => {
    act(() => root.render(<NoctuaDock page="signals" modalOpen={false} homeCalmOwl={false} />))
    const d = dock()!
    expect(d.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true')
    expect(d.querySelectorAll('button')).toHaveLength(1)
    expect(d.querySelector('button')?.getAttribute('aria-label')).toBe('Hide Noctua')
    expect(d.querySelector('input,textarea,form,[aria-live],[role=status]')).toBeNull()
    expect(d.textContent?.replace('×', '').trim()).toBe('')
  })
  it('Hide hides it everywhere (the session flag), and it stays hidden', () => {
    act(() => root.render(<NoctuaDock page="board" modalOpen={false} homeCalmOwl={false} />))
    act(() => (host.querySelector('[data-testid=noctua-dock-hide]') as HTMLElement).click())
    expect(noctuaHidden()).toBe(true)
    expect(dock()).toBeNull()
    act(() => root.render(<NoctuaDock page="home" modalOpen={false} homeCalmOwl={false} />))
    expect(dock()).toBeNull()
  })
  it('is not shown on Home when Home shows its own calm owl (never two owls)', () => {
    act(() => root.render(<NoctuaDock page="home" modalOpen={false} homeCalmOwl />))
    expect(dock()).toBeNull()
  })
  it('is frozen on the decision pages, while a modal or popover is open and while typing', async () => {
    for (const p of FROZEN_PAGES) {
      act(() => root.render(<NoctuaDock page={p} modalOpen={false} homeCalmOwl={false} />))
      expect(dock()?.getAttribute('data-frozen')).toBe('true')
    }
    act(() => root.render(<NoctuaDock page="pms" modalOpen={false} homeCalmOwl={false} />))
    expect(dock()?.getAttribute('data-frozen')).toBe('false')
    act(() => root.render(<NoctuaDock page="pms" modalOpen homeCalmOwl={false} />))
    expect(dock()?.getAttribute('data-frozen')).toBe('true')
    act(() => root.render(<NoctuaDock page="pms" modalOpen={false} homeCalmOwl={false} />))
    const pop = document.createElement('div')
    pop.setAttribute('data-popover-open', '')
    act(() => void document.body.appendChild(pop))
    await act(async () => void (await Promise.resolve()))
    expect(dock()?.getAttribute('data-frozen')).toBe('true')
    act(() => pop.remove())
    await act(async () => void (await Promise.resolve()))
    expect(dock()?.getAttribute('data-frozen')).toBe('false')
    const input = document.createElement('input')
    document.body.appendChild(input)
    act(() => input.focus())
    expect(dock()?.getAttribute('data-frozen')).toBe('true')
    act(() => input.blur())
    expect(dock()?.getAttribute('data-frozen')).toBe('false')
    input.remove()
  })
  it('walks once per session, on Home only, and only as far as the free space', () => {
    vi.useFakeTimers()
    act(() => root.render(<NoctuaDock page="roi" modalOpen={false} homeCalmOwl={false} />))
    act(() => void vi.advanceTimersByTime(1000))
    expect(dock()?.classList.contains('is-walk')).toBe(false)
    act(() => root.render(<NoctuaDock page="home" modalOpen={false} homeCalmOwl={false} />))
    act(() => void vi.advanceTimersByTime(1000))
    // jsdom has no layout (elementsFromPoint absent): nothing collides, so the full 96 px walk runs once.
    expect(dock()?.classList.contains('is-walk')).toBe(true)
    expect(dock()?.style.getPropertyValue('--ms-walk')).toBe('-96px')
    expect(firstWalk()).toBe(false)
    act(() => void vi.advanceTimersByTime(3300))
    expect(dock()?.classList.contains('is-walk')).toBe(false)
    vi.useRealTimers()
  })
  it('the walk stops short of anything it would cover', () => {
    const btn = document.createElement('button')
    const fake = { elementsFromPoint: (x: number) => (x < 1300 ? [btn] : []), documentElement: document.documentElement, body: document.body } as unknown as Document
    expect(freeWalk({ left: 1352, top: 800, right: 1416, bottom: 864 }, null, fake)).toBe(48)
    expect(freeWalk({ left: 1352, top: 800, right: 1416, bottom: 864 }, null, { ...fake, elementsFromPoint: () => [btn] } as unknown as Document)).toBe(0)
  })
})

describe('never covering anything', () => {
  it('treats buttons, links, inputs, tables, figures and text as covered; empty layout boxes as free', () => {
    const b = document.createElement('button')
    const p = document.createElement('p')
    p.textContent = 'text'
    const div = document.createElement('div')
    const td = document.createElement('td')
    expect(wouldCover(b)).toBe(true)
    expect(wouldCover(p)).toBe(true)
    expect(wouldCover(td)).toBe(true)
    expect(wouldCover(div)).toBe(false)
  })
  it('collides when something it would cover is under the dock, and not when only empty space is', () => {
    const btn = document.createElement('button')
    const fake = (els: Element[]) => ({ elementsFromPoint: () => els, documentElement: document.documentElement, body: document.body }) as unknown as Document
    expect(rectCollides({ left: 0, top: 0, right: 64, bottom: 64 }, null, fake([btn]))).toBe(true)
    expect(rectCollides({ left: 0, top: 0, right: 64, bottom: 64 }, null, fake([document.createElement('div')]))).toBe(false)
  })
})

describe('motion rules in CSS', () => {
  it('the stylesheet has balanced braces (a stray brace breaks the production CSS build)', () => {
    const noComments = css.replace(/\/\*[\s\S]*?\*\//g, '')
    expect((noComments.match(/\{/g) ?? []).length).toBe((noComments.match(/\}/g) ?? []).length)
  })
  it('glides at most 12px, walks 96px in 3s (32px/s), pauses, and stops under reduced motion', () => {
    expect(css).toMatch(/@keyframes ms-noctua-glide[^}]*translateX\(0\)[^}]*\}[^}]*translateX\(-12px\)/)
    expect(css).toMatch(/ms-noctua-walk 3s linear 1/)
    expect(css).toMatch(/var\(--ms-walk, -96px\)/)
    expect(css).toMatch(/\.is-paused[^{]*\{[^}]*animation-play-state: paused/)
    const rm = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'))
    expect(rm).toMatch(/\.ms-noctua-dock-body[\s\S]*animation: none !important/)
    expect(css).toMatch(/\.ms-noctua-dock \{[^}]*position: fixed;[^}]*right: 24px;[^}]*bottom: 24px;[^}]*z-index: 25/)
    expect(css).not.toMatch(/mousemove|cursor/)
  })
})

import { dockCaption, dockLabel } from './NoctuaDock'

describe('interactive dock (safe)', () => {
  it('a click opens the PMS board; the only words are the fixed "N to review" caption; no speech, no input, no network', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    const speak = (globalThis as { speechSynthesis?: unknown }).speechSynthesis
    const onOpen = vi.fn()
    act(() => root.render(<NoctuaDock page="home" modalOpen={false} homeCalmOwl={false} count={7} onOpen={onOpen} />))
    const d = dock()!
    const open = d.querySelector('[data-testid=noctua-dock-open]') as HTMLButtonElement
    expect(open.getAttribute('aria-label')).toBe(dockLabel(7))
    expect(d.querySelector('[data-testid=noctua-dock-caption]')?.textContent).toBe(dockCaption(7))
    expect(d.textContent?.replace('×', '').trim()).toBe('7 to review')
    expect(d.querySelector('input,textarea,form,[aria-live],[role=status]')).toBeNull()
    act(() => open.click())
    expect(onOpen).toHaveBeenCalledTimes(1)
    expect(fetchSpy).not.toHaveBeenCalled()
    expect((globalThis as { speechSynthesis?: unknown }).speechSynthesis).toBe(speak)
    fetchSpy.mockRestore()
  })
  it('hover or focus makes the owl look around, except on a frozen page; no caption when nothing is to review', () => {
    act(() => root.render(<NoctuaDock page="home" modalOpen={false} homeCalmOwl={false} count={0} onOpen={() => undefined} />))
    const open = dock()!.querySelector('[data-testid=noctua-dock-open]') as HTMLButtonElement
    expect(dock()!.querySelector('[data-testid=noctua-dock-caption]')).toBeNull()
    act(() => open.dispatchEvent(new FocusEvent('focus')))
    act(() => open.focus())
    expect(dock()!.querySelector('svg')?.getAttribute('data-state')).toBe('watching')
    act(() => root.render(<NoctuaDock page="board" modalOpen={false} homeCalmOwl={false} count={3} onOpen={() => undefined} />))
    const o2 = dock()!.querySelector('[data-testid=noctua-dock-open]') as HTMLButtonElement
    act(() => o2.focus())
    expect(dock()!.getAttribute('data-frozen')).toBe('true')
    expect(dock()!.querySelector('svg')?.getAttribute('data-state')).toBe('idle')
  })
  it('the owl colours are --noctua-* design tokens and the tufted head path is unchanged', () => {
    expect(css).toMatch(/\.ms-noctua-body \{\s*fill: var\(--noctua-body\)/)
    expect(css).toMatch(/\.ms-noctua-eye \{\s*fill: var\(--noctua-eye\)/)
    expect(css).toMatch(/\.ms-noctua-belly \{\s*fill: var\(--noctua-belly\)/)
    const owl = readFileSync(resolve(__dirname, '../components/mascot/MascotOwl.tsx'), 'utf8')
    expect(owl).toContain('d="M11 17 12 6l11 4h18l11-4 1 11v23q0 12-21 14Q11 52 11 40Z"')
  })
})
