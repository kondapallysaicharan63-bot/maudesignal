// @vitest-environment jsdom
// v2 sidebar, Home and the real-alert list in jsdom: order of entries, Recents (open, rename inline, delete with
// confirm), labels that never wrap, and the simulated devices kept out of every real-alert list.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import alerts from '../../public/data/alerts.json'
import briefs from '../../public/data/briefs.json'
import company from '../../public/data/company.json'
import manifest from '../../public/data/manifest.json'
import sweep from '../../public/data/sweep.json'
import { parseAlerts } from '../alerts'
import { flaggedRows } from '../artifacts'
import type { WorkspaceData } from '../types'
import type { SavedChat } from './chatStore'
import { HomeV2 } from './HomeV2'
import { devicesToReview, realAlertItems, realDetails } from './realAlerts'
import { SidebarV2 } from './SidebarV2'
import { tabMove } from './SubTabs'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const DATA = {
  alerts: parseAlerts(alerts),
  briefs: briefs.briefs,
  company,
  sweep,
  manifest,
} as unknown as WorkspaceData

let host: HTMLDivElement
let root: Root
beforeEach(() => {
  window.matchMedia = ((q: string) => ({ matches: false, media: q, addEventListener: () => undefined, removeEventListener: () => undefined })) as never
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})
afterEach(() => {
  act(() => root.unmount())
  host.remove()
  vi.restoreAllMocks()
})

const chat = (id: string, title: string): SavedChat => ({
  id,
  title,
  createdAt: 1,
  updatedAt: 1,
  turns: [{ id: 1, via: 'text', question: title, status: 'done' }],
})

function renderSidebar(over: Partial<Parameters<typeof SidebarV2>[0]> = {}) {
  const fns = {
    onTheme: vi.fn(),
    onNewChat: vi.fn(),
    onSearch: vi.fn(),
    onNav: vi.fn(),
    onChat: vi.fn(),
    onRename: vi.fn(),
    onDelete: vi.fn(),
    onSchedules: vi.fn(),
    onClose: vi.fn(),
  }
  act(() =>
    root.render(
      <SidebarV2
        open={false}
        collapsed={false}
        active="home"
        activeChat="b"
        chats={[chat('b', 'A very long chat title that goes on and on beyond the sidebar'), chat('a', 'Older chat')]}
        devicesLabel="Our devices (simulated)"
        devicesToReview={6}
        theme="system"
        {...fns}
        {...over}
      />,
    ),
  )
  return fns
}

const q = <T extends Element = HTMLElement>(sel: string) => host.querySelector<T & HTMLElement>(sel)
const qa = (sel: string) => Array.from(host.querySelectorAll<HTMLElement>(sel))
const click = (el: Element | null) => act(() => (el as HTMLElement).click())

describe('sidebar', () => {
  it('lists New chat, Search, Home, Signals, Our devices, Evidence, Connect, then Recents', () => {
    renderSidebar()
    const labels = qa('.ms2-navitem').map((b) => b.textContent?.replace(/\s+/g, ' ').trim())
    expect(labels.slice(0, 7)).toEqual(['New chat', 'SearchCtrl K', 'Home', 'Signals', 'Our devices (simulated)6 to review', 'Evidence', 'Connect'])
    const text = host.textContent ?? ''
    expect(text.indexOf('Connect')).toBeLessThan(text.indexOf('Recents'))
    expect(text).toContain('Saved on this device only')
    expect(text).toContain('Schedules and sources')
    expect(text).not.toMatch(/Daily briefs|Workflows/)
  })
  it('marks the current page and chat, and gives every truncated label its full text as a title', () => {
    renderSidebar()
    expect(q('[data-testid=nav-home]')?.getAttribute('aria-current')).toBe('page')
    const recents = qa('[data-testid=recent-chat]')
    expect(recents[0].getAttribute('aria-current')).toBe('page')
    expect(recents[0].getAttribute('title')).toBe('A very long chat title that goes on and on beyond the sidebar')
    expect(q('[data-testid=nav-devices]')?.getAttribute('title')).toBe('Our devices (simulated) · 6 to review')
  })
  it('opens a chat from Recents', () => {
    const f = renderSidebar()
    click(qa('[data-testid=recent-chat]')[1])
    expect(f.onChat).toHaveBeenCalledWith('a')
  })
  it('renames inline: Enter saves, Escape cancels', () => {
    const f = renderSidebar()
    click(qa('[data-testid=recent-more]')[1])
    click(q('[data-testid=recent-rename]'))
    const input = q<HTMLInputElement>('[data-testid=rename-input]') as HTMLInputElement
    expect(input.value).toBe('Older chat')
    act(() => {
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
      set.call(input, 'Renamed')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    act(() => {
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    })
    expect(f.onRename).toHaveBeenCalledWith('a', 'Renamed')
    expect(f.onRename).toHaveBeenCalledTimes(1)
    click(qa('[data-testid=recent-more]')[1])
    click(q('[data-testid=recent-rename]'))
    const again = q<HTMLInputElement>('[data-testid=rename-input]') as HTMLInputElement
    act(() => {
      again.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    })
    expect(f.onRename).toHaveBeenCalledTimes(1)
    expect(q('[data-testid=rename-input]')).toBeNull()
  })
  it('deletes only after a confirm; Cancel keeps the chat', () => {
    const f = renderSidebar()
    click(qa('[data-testid=recent-more]')[0])
    click(q('[data-testid=recent-delete]'))
    expect(q('[data-testid=delete-confirm]')?.textContent).toContain('A very long chat title')
    click(q('[data-testid=delete-no]'))
    expect(f.onDelete).not.toHaveBeenCalled()
    click(qa('[data-testid=recent-more]')[0])
    click(q('[data-testid=recent-delete]'))
    click(q('[data-testid=delete-yes]'))
    expect(f.onDelete).toHaveBeenCalledWith('b')
  })
  it('New chat and Search call through', () => {
    const f = renderSidebar()
    click(q('[data-testid=new-chat]'))
    click(q('[data-testid=side-search]'))
    expect(f.onNewChat).toHaveBeenCalled()
    expect(f.onSearch).toHaveBeenCalled()
  })
  it('says so when nothing is saved', () => {
    renderSidebar({ chats: [] })
    expect(host.textContent).toContain('No saved chats yet.')
  })
})

describe('real alerts are never mixed with simulated devices', () => {
  it('the real list has only sweep and brief alerts, ranked more serious first', () => {
    const items = realAlertItems(DATA)
    expect(items.length).toBe(realDetails(DATA).length)
    expect(items.length).toBeGreaterThan(0)
    expect(items.every((a) => a.source !== 'company' && !a.id.startsWith('company:'))).toBe(true)
    expect(items[0].kind).toBe('severity_escalation')
    expect(devicesToReview(DATA)).toBe(company.devices.filter((d) => d.status?.label === 'Needs review').length)
  })
  it('Home: top 3 real alerts, "View all N", and a separate simulated card', () => {
    const onViewAll = vi.fn()
    act(() =>
      root.render(
        <HomeV2 data={DATA} onAlert={() => undefined} onViewAll={onViewAll} onDevices={() => undefined} onSweep={() => undefined} onAudit={() => undefined} />,
      ),
    )
    const list = q('[data-testid=home-alerts]')!
    expect(list.querySelectorAll('li').length).toBe(3)
    expect(list.textContent).not.toMatch(/simulated|Needs review/i)
    const n = realAlertItems(DATA).length
    expect(q('[data-testid=home-view-all]')?.textContent?.replace(/\s/g, ' ')).toContain(`View all ${n}`)
    click(q('[data-testid=home-view-all]'))
    expect(onViewAll).toHaveBeenCalled()
    expect(q('[data-testid=home-devices]')?.textContent).toContain(`${devicesToReview(DATA)} to review`)
    expect(q('[data-testid=home-sweep]')?.textContent).toContain(`${flaggedRows(DATA.sweep).length} flagged of ${DATA.sweep.meta.codes_on_list}`)
    expect(q('[data-testid=home-sweep-label]')?.textContent).toContain('Stored')
    expect(q('[data-testid=trust-claims]')?.textContent).toBe(String(manifest.header.claims_verified))
    expect(q('[data-testid=trust-withheld]')?.textContent).toBe(String(manifest.header.sentences_withheld))
  })
})

it('tab keys move round the row', () => {
  expect(tabMove('ArrowRight', 0, 4)).toBe(1)
  expect(tabMove('ArrowRight', 3, 4)).toBe(0)
  expect(tabMove('ArrowLeft', 0, 4)).toBe(3)
  expect(tabMove('Home', 2, 4)).toBe(0)
  expect(tabMove('End', 0, 4)).toBe(3)
  expect(tabMove('a', 0, 4)).toBeNull()
})
