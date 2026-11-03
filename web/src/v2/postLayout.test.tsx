// @vitest-environment jsdom
// Post-P0 layout pieces that P0 does not have: the known-effects note (PRD-30), the Board badge rule in the sidebar, and
// the "Why matched" tags with the problem-term filter (PRD-29, display only).
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import example from '../fixtures/investigateExample.json'
import { InvestigatePage } from '../investigate/InvestigatePage'
import { KnownEffects } from '../investigate/KnownEffects'
import { eventCounts, knownEffectsText } from '../investigate/KnownEffects'
import { parseInvestigation, type Investigation } from '../investigate/api'
import { SidebarV2 } from './SidebarV2'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const answer = (): Investigation => parseInvestigation((example as { answer?: unknown }).answer ?? example)!
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
})

describe('known-effects note', () => {
  it('is a button that only shows a draft sentence for a person to review', () => {
    const a = answer()
    act(() => root.render(<KnownEffects a={a} />))
    expect(host.querySelector('[data-testid=inv-known-text]')).toBeNull()
    act(() => (host.querySelector('[data-testid=inv-known-btn]') as HTMLElement).click())
    const t = host.querySelector('[data-testid=inv-known-text]')?.textContent ?? ''
    expect(t).toContain('Consider adding [')
    expect(t).toContain(`to the known-effects record for ${a.product_code} - human reviews and approves.`)
    expect(t).toContain('Nothing was added to any record.')
    expect(knownEffectsText(a)).toBe(t.split(' This is a draft')[0])
    expect(typeof eventCounts(a)).toBe('string')
  })
})

describe('Investigate: Why matched and the problem-term filter', () => {
  it('shows the tags from the data, and the filter is on by default', () => {
    act(() => root.render(<InvestigatePage apiBase={null} />))
    const tags = host.querySelectorAll('[data-testid=inv-why-matched]')
    expect(tags.length).toBeGreaterThan(0)
    expect(host.querySelector('[data-testid=inv-problem-filter]')?.getAttribute('aria-pressed')).toBe('true')
    for (const t of Array.from(tags)) expect(t.textContent).not.toContain('not in this data')
  })
})

describe('sidebar Board badge', () => {
  const props = {
    open: false, collapsed: false, active: 'home', activeChat: null, chats: [], saved: true, chatHref: () => '#', devicesLabel: 'Our devices (simulated)',
    devicesToReview: 2, theme: 'light', onTheme: () => undefined, onNewChat: () => undefined, onSearch: () => undefined, onNav: () => undefined,
    onChat: () => undefined, onRename: () => undefined, onDelete: () => undefined, onSchedules: () => undefined, onClose: () => undefined,
  } as unknown as Parameters<typeof SidebarV2>[0]
  it('shows the count only when rows are New or Under review', () => {
    act(() => root.render(<SidebarV2 {...props} boardCount={0} />))
    expect(host.querySelector('[data-testid=badge-board]')).toBeNull()
    act(() => root.render(<SidebarV2 {...props} boardCount={3} />))
    expect(host.querySelector('[data-testid=badge-board]')?.textContent).toContain('3')
  })
})
