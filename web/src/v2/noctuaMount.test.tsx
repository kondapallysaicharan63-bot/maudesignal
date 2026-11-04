// @vitest-environment jsdom
// Where Noctua is mounted: the top bar (a 44 x 44 button while real alerts exist) and Home's calm state (decorative), never
// both; "Hide Noctua" / "Show Noctua"; the caption is paired with a real count; it never replaces the bell.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MascotOwl, noctuaHidden, resetMascotBubble, setNoctuaHidden } from '../components/mascot/MascotOwl'
import { alertCaption } from '../components/mascot/mascotStates'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type { AlertItem } from '../dashboard'
import { ThemeMenu } from './ThemeMenu'
import { TopBarV2, noctuaLabel } from './TopBarV2'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const item = (id: string): AlertItem => ({ id, productCode: 'LLZ', title: 'LLZ', text: 'x', detail: 'y', tone: 'bad', rule: 'new kind of problem' }) as unknown as AlertItem
let host: HTMLDivElement
let root: Root
beforeEach(() => {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  resetMascotBubble()
  setNoctuaHidden(false)
})
afterEach(() => {
  act(() => root.unmount())
  host.remove()
})
const bar = (alerts: AlertItem[], onAlert = vi.fn()) =>
  act(() =>
    root.render(
      <TopBarV2
        desktop
        homeHref="/"
        sidebarOpen
        onToggleSidebar={() => undefined}
        onHome={() => undefined}
        onSearch={() => undefined}
        alerts={alerts}
        onAlert={onAlert}
        onViewAll={() => undefined}
        devicesLabel="Our devices (simulated)"
        devicesToReview={2}
        onDevices={() => undefined}
        onFeedback={() => undefined}
      />,
    ),
  )

describe('top bar mark', () => {
  it('is a button with a spoken label while real alerts exist; clicking opens the first alert; the owl itself is aria-hidden', () => {
    const onAlert = vi.fn()
    bar([item('a'), item('b')], onAlert)
    const b = host.querySelector('[data-testid=noctua-top]') as HTMLButtonElement
    expect(b.getAttribute('aria-label')).toBe(noctuaLabel(2))
    expect(b.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true')
    expect(b.querySelector('svg')?.getAttribute('width')).toBe('32')
    act(() => b.click())
    expect(onAlert).toHaveBeenCalledWith(expect.objectContaining({ id: 'a' }))
    expect(host.querySelector('[data-testid=noctua-bubble]')?.textContent).toBe(alertCaption(2))
  })
  it('the bubble opens once per session, and the bell and Feedback are still there', () => {
    bar([item('a')])
    expect(host.querySelector('[data-testid=noctua-bubble]')).not.toBeNull()
    act(() => root.render(<div />))
    bar([item('a')])
    expect(host.querySelector('[data-testid=noctua-bubble]')).toBeNull()
    expect(host.querySelector('[data-testid=top-feedback]')).not.toBeNull()
  })
  it('shows nothing when there are no real alerts, and when hidden', () => {
    bar([])
    expect(host.querySelector('[data-testid=noctua-top]')).toBeNull()
    setNoctuaHidden(true)
    bar([item('a')])
    expect(host.querySelector('[data-testid=noctua-top]')).toBeNull()
    expect(noctuaHidden()).toBe(true)
  })
  it('the top bar carries no data banner, version or simulated badge', () => {
    bar([item('a')])
    expect(host.textContent).not.toMatch(/Data as of|version|Simulated badge/i)
  })
})

describe('Hide / Show Noctua in the Theme menu', () => {
  it('toggles the session flag', () => {
    act(() => root.render(<ThemeMenu theme="light" onTheme={() => undefined} placement="up" testid="t" showLabel />))
    act(() => (host.querySelector('[data-testid=t]') as HTMLElement).click())
    const t = host.querySelector('[data-testid=noctua-toggle]') as HTMLElement
    expect(t.textContent).toContain('Hide Noctua')
    act(() => t.click())
    expect(noctuaHidden()).toBe(true)
    act(() => (host.querySelector('[data-testid=t]') as HTMLElement).click())
    expect((host.querySelector('[data-testid=noctua-toggle]') as HTMLElement).textContent).toContain('Show Noctua')
  })
})

describe('no chat, no speech', () => {
  it('Noctua has no input, no form, no live region and no handler of its own that answers anything', () => {
    act(() => root.render(<MascotOwl state="alert" />))
    expect(host.querySelector('input,textarea,form,[role=status],[aria-live]')).toBeNull()
    const src = readFileSync(resolve(__dirname, '../components/mascot/MascotOwl.tsx'), 'utf8')
    expect(src).not.toMatch(/fetch\(|XMLHttpRequest|speechSynthesis|new Audio|mousemove|pointermove/)
  })
})

describe('tab order', () => {
  it('the skip link comes before the Noctua dock in the v2 shell, so it stays the first Tab stop', () => {
    const src = readFileSync(resolve(__dirname, './AppV2.tsx'), 'utf8')
    const skip = src.indexOf('data-testid="skip-link"')
    const dock = src.indexOf('<NoctuaDock')
    expect(skip).toBeGreaterThan(-1)
    expect(dock).toBeGreaterThan(skip)
  })
})
