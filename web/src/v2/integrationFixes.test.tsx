// @vitest-environment jsdom
// Integration-review fixes: index.html route lists, prototype-safe profile lookups, the profile error boundary,
// Investigate in the sidebar and search, device profiles in search, and in-app links.
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import company from '../../public/data/company.json'
import raw from '../../public/data/company_profiles.json'
import { V2_SEGMENTS } from '../layoutFlag'
import type { Company } from '../types'
import { DeviceProfilePage, ProfileBoundary } from './DeviceProfile'
import { PmsWorkflow } from './PmsWorkflow'
import { profileDevices, profileOf, type ProfilesFile } from './profiles'
import { parseRoute } from './router'
import { navOf } from './AppV2'
import { pageItems, searchAll } from './SearchPalette'

const F = raw as unknown as ProfilesFile
const C = company as unknown as Company
const html = readFileSync(resolve(__dirname, '../../index.html'), 'utf8')
const PROTO_IDS = ['constructor', 'toString', '__proto__', 'hasOwnProperty', 'valueOf']

describe('index.html route lists', () => {
  it('lists every v2 segment in the <base> regex and the first-paint theme regex', () => {
    const regexes = [...html.matchAll(/\(([a-z|-]+)\)\(\\\/\|\$\)/g)].map((m) => m[1].split('|'))
    expect(regexes).toHaveLength(2)
    for (const segs of regexes) for (const s of V2_SEGMENTS) expect(segs).toContain(s)
  })
  it('the base regex resolves /roi/ and /investigate/x to the app folder', () => {
    const m = /(\/[^"']*?\(chat\|[^)]*\)\(\\\/\|\$\))/.exec(html)
    expect(m).not.toBeNull()
    const re = /^(.*?\/)(chat|signals|devices|evidence|connect|workflow|thread|run|capture|pms-workflow|roi|investigate)(\/|$)/
    expect(re.exec('/app/roi/')?.[1]).toBe('/app/')
    expect(re.exec('/investigate/x')?.[1]).toBe('/')
  })
})

describe('prototype-safe profile lookup', () => {
  it('finds stored ids and nothing on Object.prototype', () => {
    expect(profileOf(F, 'DMC-01')?.id).toBe('DMC-01')
    for (const id of PROTO_IDS) expect(profileOf(F, id)).toBeUndefined()
    expect(profileOf(undefined, 'DMC-01')).toBeUndefined()
    expect(profileDevices(F)).toHaveLength(12)
  })
  it('unknown ids show the existing "no stored profile" text, without throwing', () => {
    for (const id of PROTO_IDS) {
      const out = renderToStaticMarkup(
        <DeviceProfilePage file={F} company={C} id={id} tab="overview" onTab={() => {}} onBack={() => {}} onEvidence={() => {}} />,
      )
      expect(out).toContain('There is no stored profile')
    }
  })
  it('the route parser keeps such ids as profile ids', () => {
    expect(parseRoute('/devices/constructor')).toMatchObject({ page: 'profile', id: 'constructor' })
  })
})

describe('profile error boundary and links', () => {
  let host: HTMLDivElement
  let root: Root
  beforeEach(() => {
    host = document.createElement('div')
    document.body.appendChild(host)
    root = createRoot(host)
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })
  afterEach(() => {
    act(() => root.unmount())
    host.remove()
    vi.restoreAllMocks()
  })
  it('a profile that cannot be drawn shows a message and a way back to Our devices', () => {
    const onBack = vi.fn()
    function Boom(): JSX.Element {
      throw new Error('bad profile')
    }
    act(() =>
      root.render(
        <ProfileBoundary resetKey="a" onBack={onBack}>
          <Boom />
        </ProfileBoundary>,
      ),
    )
    expect(host.querySelector('[data-testid=profile-broken]')?.textContent).toContain('could not be shown')
    const b = host.querySelector<HTMLButtonElement>('[data-testid=profile-broken-back]')!
    expect(b.textContent).toBe('Back to Our devices')
    act(() => b.click())
    expect(onBack).toHaveBeenCalled()
  })
  it('a malformed stored profile is caught by the page boundary', () => {
    const bad = { ...F, profiles: { 'DMC-01': { id: 'DMC-01' } } } as unknown as ProfilesFile
    act(() =>
      root.render(
        <DeviceProfilePage file={bad} company={C} id="DMC-01" tab="overview" onTab={() => {}} onBack={() => {}} onEvidence={() => {}} />,
      ),
    )
    expect(host.querySelector('[data-testid=profile-broken]')).not.toBeNull()
  })
  it('Investigate links move inside the app on a plain click and keep the real address otherwise', () => {
    const onInvestigate = vi.fn()
    act(() => root.render(<PmsWorkflow onInvestigate={onInvestigate} />))
    const a = host.querySelector<HTMLAnchorElement>('[data-testid=pms-investigate-link]')!
    expect(a.getAttribute('href')).toContain('investigate')
    const plain = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 })
    act(() => a.dispatchEvent(plain))
    expect(plain.defaultPrevented).toBe(true)
    expect(onInvestigate).toHaveBeenCalledTimes(1)
    const ctrl = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0, ctrlKey: true })
    let seen: boolean | null = null
    const swallow = (e: Event) => {
      seen = e.defaultPrevented // after React's handler; then stop jsdom from navigating
      e.preventDefault()
    }
    document.addEventListener('click', swallow)
    act(() => a.dispatchEvent(ctrl))
    document.removeEventListener('click', swallow)
    expect(seen).toBe(false)
    expect(onInvestigate).toHaveBeenCalledTimes(1)
  })
  it('the profile page link passes the product code and device id', () => {
    const onInvestigate = vi.fn()
    act(() =>
      root.render(
        <DeviceProfilePage file={F} company={C} id="DMC-01" tab="overview" onTab={() => {}} onBack={() => {}} onEvidence={() => {}} onInvestigate={onInvestigate} />,
      ),
    )
    const a = host.querySelector<HTMLAnchorElement>('[data-testid=investigate-link]')!
    act(() => a.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 })))
    expect(onInvestigate).toHaveBeenCalledWith(F.profiles['DMC-01'].product_code, 'DMC-01')
  })
})

describe('sidebar and search', () => {
  it('Investigate has an active sidebar entry (Home)', () => {
    expect(navOf({ page: 'investigate' })).toBe('home')
    expect(navOf({ page: 'investigate', code: 'QIH', device: 'DMC-01' })).toBe('home')
  })
  it('device profiles are searchable as "<name> · simulated device"', () => {
    const items = pageItems([], 'Our devices (simulated)', profileDevices(F))
    const dev = items.filter((i) => i.title.endsWith(' · simulated device'))
    expect(dev).toHaveLength(12)
    const first = Object.values(F.profiles)[0]
    const hit = searchAll(first.name.toLowerCase(), [], items).find((i) => i.kind === 'page' && i.route.page === 'profile')
    expect(hit?.kind === 'page' && hit.route.page === 'profile' && hit.route.id).toBe(first.id)
    expect(hit?.title).toBe(`${first.name} · simulated device`)
  })
})
