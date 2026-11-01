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
import { demoRows, NO_NAME, realRows } from './AlertRows'
import { plainDate, plainModel } from '../components/artifacts/DossierVision'
import { NOT_SAVED_NOTE, SidebarV2 } from './SidebarV2'
import { ChatBoundary, questionsLeft } from './ChatScreen'
import { SubTabs } from './SubTabs'
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
        saved
        chatHref={(id) => `/chat/${id}`}
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
  it("the real list has only this week's sweep alerts (the demo brief and simulated devices are apart), more serious first", () => {
    const items = realAlertItems(DATA)
    expect(items.length).toBe(realDetails(DATA).filter((d) => d.source.kind === 'sweep').length)
    expect(items.every((a) => a.source === 'sweep')).toBe(true)
    const demo = demoRows(DATA)
    expect(demo.rows.map((r) => r.code)).toEqual(realDetails(DATA).filter((d) => d.source.kind === 'brief').map((d) => d.product_code))
    const rows = realRows(DATA).rows
    expect(rows.every((r) => r.name === null || r.name.length > 0)).toBe(true)
    const llz = demo.rows.find((r) => r.code === 'LLZ')
    if (llz) expect(llz.counts).toBe('33 that week (8.75 before)')
    expect(items.length).toBeGreaterThan(0)
    expect(items.every((a) => a.source !== 'company' && !a.id.startsWith('company:'))).toBe(true)
    expect(items[0].kind).toBe('severity_escalation')
    expect(devicesToReview(DATA)).toBe(company.devices.filter((d) => d.status?.label === 'Needs review').length)
  })
  it('Home: top 3 real alerts, "View all N", and a separate simulated card', () => {
    const onViewAll = vi.fn()
    act(() =>
      root.render(
        <HomeV2 data={DATA} onAlert={() => undefined} onViewAll={onViewAll} onDevices={() => undefined} onAudit={() => undefined} />,
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

describe('review fixes', () => {
  it('Recents rows are real links; a plain click opens here, a Ctrl click is left to the browser', () => {
    const f = renderSidebar()
    const a = qa('[data-testid=recent-chat]')[1] as HTMLAnchorElement
    expect(a.tagName).toBe('A')
    expect(a.getAttribute('href')).toBe('/chat/a')
    const ctrl = new MouseEvent('click', { bubbles: true, cancelable: true, ctrlKey: true })
    act(() => {
      a.dispatchEvent(ctrl)
    })
    expect(f.onChat).not.toHaveBeenCalled()
    click(a)
    expect(f.onChat).toHaveBeenCalledWith('a')
  })
  it('says so when the browser refused to save', () => {
    renderSidebar({ saved: false })
    expect(q('[data-testid=saved-note]')?.textContent).toBe(NOT_SAVED_NOTE)
  })
  it('questions left comes from the live count only, and only from 5 down', () => {
    expect(questionsLeft({ remaining: null })).toBeNull()
    expect(questionsLeft({ remaining: 29 })).toBeNull()
    expect(questionsLeft({ remaining: 5 })).toBe(5)
    expect(questionsLeft({ remaining: 0 })).toBe(0)
  })
  it('a chat that cannot be drawn shows Delete this chat and New chat instead of a blank page', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const onDelete = vi.fn()
    const onNewChat = vi.fn()
    function Boom(): JSX.Element {
      throw new Error('bad saved answer')
    }
    act(() =>
      root.render(
        <ChatBoundary resetKey="c1" onDelete={onDelete} onNewChat={onNewChat}>
          <Boom />
        </ChatBoundary>,
      ),
    )
    expect(q('[data-testid=chat-broken]')).not.toBeNull()
    click(q('[data-testid=broken-delete]'))
    click(q('[data-testid=broken-new]'))
    expect(onDelete).toHaveBeenCalled()
    expect(onNewChat).toHaveBeenCalled()
    act(() =>
      root.render(
        <ChatBoundary resetKey="c2" onDelete={null} onNewChat={onNewChat}>
          <p data-testid="fine">ok</p>
        </ChatBoundary>,
      ),
    )
    expect(q('[data-testid=fine]')).not.toBeNull()
  })
  it('subtabs: arrow keys report "key" (history replaced), the View menu reports "click"', () => {
    const onChange = vi.fn()
    act(() =>
      root.render(
        <SubTabs id="t" label="T" tabs={[{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }]} value="a" onChange={onChange}>
          <p>panel</p>
        </SubTabs>,
      ),
    )
    act(() => {
      q('[data-testid=tab-a]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    })
    expect(onChange).toHaveBeenLastCalledWith('b', 'key')
    const sel = q<HTMLSelectElement>('[data-testid=t-viewpick]') as HTMLSelectElement
    act(() => {
      sel.value = 'b'
      sel.dispatchEvent(new Event('change', { bubbles: true }))
    })
    expect(onChange).toHaveBeenLastCalledWith('b', 'click')
  })
})

describe('round 2', () => {
  it('rows without a stored device name say so, never a made-up name', () => {
    const rows = realRows(DATA).rows
    for (const r of rows.filter((x) => x.name === null)) expect(r.code).toMatch(/^[A-Z]{3}$/)
    act(() =>
      root.render(<HomeV2 data={DATA} onAlert={() => undefined} onViewAll={() => undefined} onDevices={() => undefined} onAudit={() => undefined} />),
    )
    const home = q('[data-testid=home-alerts]')!.textContent ?? ''
    for (const r of rows.slice(0, 3)) expect(home).toContain(r.name ?? NO_NAME)
    expect(home).not.toMatch(/demo/i)
    if (demoRows(DATA).rows.length) expect(q('[data-testid=home-demo]')?.textContent).toMatch(/Demo snapshot/)
  })
  it('plain model names and dates for "How this was made"', () => {
    expect(plainModel('muse-spark-1.3')).toBe('Muse Spark 1.3')
    expect(plainModel('muse-wonder-1.0')).toBe('Muse Wonder')
    expect(plainModel('other-model')).toBe('other-model')
    expect(plainDate('2026-10-31T03:30:21Z')).toBe('31 Oct 2026')
    expect(plainDate('soon')).toBe('soon')
  })
})
