// @vitest-environment jsdom
// Make it yours in jsdom: the bar, the editor (product code, K-number, CSV, label match), export / import / clear, blocked
// storage, the simulated default, and the alert buddy (states, label, keyboard, reduced motion).
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { act, useMemo, type ReactElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import company from '../public/data/company.json'
import sweep from '../public/data/sweep.json'
import { AlertBuddy, BUBBLE_MS, buddyLabel, buddyText, resetBubbleSeen } from './components/AlertBuddy'
import { CompanyList } from './components/OurDevices'
import { LiveLabelResult } from './components/CameraPanel'
import { plainImportError } from './components/MakeItYours'
import { parseLabelResponse } from './live/api'
import { MINE_BANNER, MINE_KEY, MODE_KEY, buildMyCompany, flaggedCodes, knownCodes } from './myCompany'
import type { AlertItem } from './dashboard'
import type { Company, Sweep } from './types'
import { MineContext, useMineState, type MineApi } from './useMyCompany'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const C = company as unknown as Company
const S = sweep as unknown as Sweep
const HOT = [...flaggedCodes(S)][0]

let host: HTMLDivElement
let root: Root
beforeEach(() => {
  localStorage.clear()
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})
afterEach(() => {
  act(() => root.unmount())
  host.remove()
  vi.restoreAllMocks()
})

/** The Our devices list wired the way App wires it: the real hook, the real context, the real builder. */
function Harness({ apiBase = null }: { apiBase?: string | null }) {
  const my = useMineState()
  const company = useMemo(() => (my.mode === 'mine' ? buildMyCompany(my.mine, C, S) : C), [my.mode, my.mine])
  const api: MineApi = {
    mode: my.mode,
    setMode: my.setMode,
    mine: my.mine,
    persisted: my.persisted,
    known: knownCodes(S, [], C),
    flagged: flaggedCodes(S),
    apiBase,
    setCompany: my.setCompany,
    add: (i) => {
      my.setMode('mine')
      my.add(i, flaggedCodes(S))
    },
    move: my.move,
    remove: my.remove,
    replace: my.replace,
    clear: my.clear,
  }
  return (
    <MineContext.Provider value={api}>
      <CompanyList company={company} onDevice={() => undefined} />
    </MineContext.Provider>
  )
}
const show = (el: ReactElement) => act(() => root.render(el))
const q = (id: string) => host.querySelector<HTMLElement>(`[data-testid="${id}"]`)
const text = () => host.textContent ?? ''
const click = (el: Element | null) => {
  expect(el).not.toBeNull()
  act(() => (el as HTMLElement).click())
}
const type = (id: string, value: string) => {
  const el = q(id) as HTMLInputElement | HTMLTextAreaElement
  expect(el).not.toBeNull()
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  act(() => {
    Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(el, value)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
const submit = (testid: string) => click(q(testid))
const open = () => {
  click(q('make-it-yours'))
}
const stored = () => JSON.parse(localStorage.getItem(MINE_KEY) ?? 'null')

describe('the simulated company is the default', () => {
  it('a new visitor sees Demo MedTech Co. with its banner, and no Make it yours panel', () => {
    show(<Harness />)
    expect(text()).toContain('Our devices (simulated)')
    expect(q('company-banner')?.textContent).toBe(C.banner)
    expect(q('mode-demo')?.getAttribute('aria-pressed')).toBe('true')
    expect(q('make-it-yours-panel')).toBeNull()
    expect(localStorage.getItem(MINE_KEY)).toBeNull()
  })
})

describe('adding devices', () => {
  it('Make it yours switches to your company, labelled with the banner and no devices yet', () => {
    show(<Harness />)
    open()
    expect(text()).toContain('Our devices (your company)')
    expect(q('company-banner')?.textContent).toBe(MINE_BANNER)
    expect(q('no-devices')?.textContent).toMatch(/No devices yet/)
    expect(localStorage.getItem(MODE_KEY)).toBe('mine')
    expect(q('make-it-yours-panel')).not.toBeNull()
  })

  it('by product code: validates, accepts an unknown code with a note, stores it in localStorage only', () => {
    show(<Harness />)
    open()
    type('in-company', 'Acme Devices')
    type('in-code', 'a1b')
    expect((q('in-code') as HTMLInputElement).value).toBe('ab')
    submit('add-code')
    expect(q('code-error')?.textContent).toMatch(/exactly 3 letters/)
    expect(stored().devices).toHaveLength(0)
    type('in-code', 'zzz')
    type('in-code-name', 'Mystery Monitor')
    submit('add-code')
    expect(q('code-error')).toBeNull()
    expect(text()).toContain('Mystery Monitor')
    expect(text()).toContain('Acme Devices')
    const s = stored()
    expect(s.company).toBe('Acme Devices')
    expect(s.devices[0]).toMatchObject({ product_code: 'ZZZ', source: 'code', status: 'Monitoring — nothing open' })
    expect(s.devices[0].note).toMatch(/not one this site has stored data for/)
    expect(q('added-msg')?.textContent).toMatch(/Added with a note/)
  })

  it('a known flagged code starts in Needs review and shows in the Needs review count', () => {
    show(<Harness />)
    open()
    type('in-code', HOT)
    submit('add-code')
    expect(q('need-review-line')?.textContent).toMatch(/^1 device needs review/)
    expect(host.querySelector('[data-needs-review]')).not.toBeNull()
  })

  it('by K-number without an API: stored as "not checked yet"', async () => {
    show(<Harness />)
    open()
    click(q('method-k'))
    type('in-k', 'k123456')
    type('in-k-name', 'Imaging Thing')
    await act(async () => {
      submit('add-k')
    })
    expect(stored().devices[0]).toMatchObject({ k_number: 'K123456', k_check: 'not checked yet', source: 'k_number', product_code: null })
    expect(q('added-msg')?.textContent).toMatch(/not checked yet/)
  })

  it('by K-number: a bad K-number is refused', async () => {
    show(<Harness />)
    open()
    click(q('method-k'))
    type('in-k', 'K12')
    await act(async () => {
      submit('add-k')
    })
    expect(q('k-error')?.textContent).toMatch(/K and 6 digits/)
    expect(stored()).toBeNull()
  })

  it('by K-number with the API: looks up once with the demo key, only the K-number is sent', async () => {
    const calls: { url: string; headers: unknown; body: unknown }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url, headers: init?.headers, body: init?.body })
        if (url.endsWith('/v1/connect')) return new Response(JSON.stringify({ demo_key: 'k-demo', auth_header: 'X-API-Key', mcp_url: 'https://api.test/mcp' }))
        return new Response(JSON.stringify({ device: { device_name: 'Looked-up viewer', applicant: 'Acme', product_code: 'QIH' } }))
      }),
    )
    show(<Harness apiBase="https://api.test" />)
    open()
    type('in-company', 'Secret Co Name')
    click(q('method-k'))
    type('in-k', 'K123456')
    await act(async () => {
      submit('add-k')
    })
    const lookup = calls.find((c) => c.url.includes('lookup_device'))!
    expect(lookup.url).toBe('https://api.test/v1/tools/lookup_device?k_number=K123456')
    expect(lookup.headers).toEqual({ 'X-API-Key': 'k-demo' })
    for (const c of calls) {
      expect(c.url).not.toContain('Secret')
      expect(String(c.body ?? '')).not.toContain('Secret')
    }
    expect(stored().devices[0]).toMatchObject({ name: 'Looked-up viewer', product_code: 'QIH', k_number: 'K123456' })
    expect(stored().devices[0].k_check).toMatch(/^checked with the FDA 510\(k\) record K123456/)
    vi.unstubAllGlobals()
  })

  it('CSV: preview with errors first, nothing imported until Import, then the valid rows only', () => {
    show(<Harness />)
    open()
    click(q('method-csv'))
    type('in-csv-text', 'name,product_code,k_number\nAlpha,LLZ,K111111\nBeta,QIH,\nBad,12,\n,LLZ,')
    expect(q('csv-valid')?.textContent).toBe('2')
    expect(q('csv-bad')?.textContent).toBe('2')
    expect(q('csv-errors')?.textContent).toMatch(/Line 4/)
    expect(stored()).toBeNull()
    click(q('csv-import'))
    expect(stored().devices.map((d: { name: string }) => d.name)).toEqual(['Alpha', 'Beta'])
    expect(stored().devices[0]).toMatchObject({ source: 'csv', k_check: 'not checked yet' })
    expect(q('csv-preview')).toBeNull()
  })

  it('CSV with a missing header column shows an error and no Import button', () => {
    show(<Harness />)
    open()
    click(q('method-csv'))
    type('in-csv-text', 'foo,bar\n1,2')
    expect(q('csv-errors')?.textContent).toMatch(/"name" column/)
    expect((q('csv-import') as HTMLButtonElement).disabled).toBe(true)
  })

  it('label photo is off without an API address', () => {
    show(<Harness />)
    open()
    click(q('method-label'))
    expect(q('label-off')?.textContent).toMatch(/needs the live service/)
  })
})

describe('label photo: only the confirmed match is added', () => {
  const body = {
    mode: 'live',
    trace: [],
    cost_usd: null,
    limits: null,
    reading: { legibility: 'clear', fields: { device_name: { value: 'Stub device', legibility: 'clear' } } },
    matches: {
      status: 'needs_person_to_confirm',
      candidates: [1, 2, 3].map((i) => ({
        k_number: `K00000${i}`,
        device_name: `Stub device ${i}`,
        applicant: `Stub Maker ${i}`,
        product_code: 'QIH',
        why_matched: ['name'],
        why_not_matched: [],
        links: [],
      })),
    },
    confirmed: null,
  }
  it('no add button before a confirmation; after confirming one, only that one is passed on, once', () => {
    const added: string[] = []
    const res = parseLabelResponse(body)!
    show(<LiveLabelResult res={res} onAdd={(c) => added.push(c.k_number)} addLabel="Add to your company" />)
    expect(q('add-confirmed')).toBeNull()
    const confirm = [...host.querySelectorAll('button')].filter((b) => b.textContent === 'Confirm this match')
    expect(confirm).toHaveLength(3)
    click(confirm[1])
    expect(host.querySelectorAll('[data-testid="add-confirmed"]')).toHaveLength(1)
    click(q('add-confirmed'))
    expect(q('add-confirmed')).toBeNull() // the button is gone once the match is added, so it cannot be added twice
    expect(added).toEqual(['K000002'])
    expect(q('added-note')?.textContent).toBe('Added to your company.')
  })
  it('a recorded run cannot be added', () => {
    const res = parseLabelResponse({ ...body, mode: 'recorded' })!
    show(<LiveLabelResult res={res} onAdd={() => undefined} />)
    click([...host.querySelectorAll('button')].find((b) => b.textContent === 'Confirm this match') ?? null)
    expect(q('add-confirmed')).toBeNull()
  })
})

describe('your data: export, import, clear', () => {
  const seed = () => {
    show(<Harness />)
    open()
    type('in-company', 'Acme')
    type('in-code', HOT)
    submit('add-code')
  }
  const file = (name: string, content: string) => {
    const f = new File([content], name, { type: 'application/json' })
    // jsdom 26 has no Blob.text(); the page calls it, so give the file one.
    Object.defineProperty(f, 'text', { value: async () => content })
    return f
  }
  const pick = async (f: File) => {
    const input = q('import-json-file') as HTMLInputElement
    Object.defineProperty(input, 'files', { value: [f], configurable: true })
    await act(async () => {
      input.dispatchEvent(new Event('change', { bubbles: true }))
    })
  }

  it('Export JSON downloads the company as a file; clearing and importing that file brings the same device back', async () => {
    seed()
    let blob: Blob | null = null
    ;(URL as unknown as { createObjectURL: (b: Blob) => string }).createObjectURL = (b) => ((blob = b), 'blob:x')
    ;(URL as unknown as { revokeObjectURL: () => void }).revokeObjectURL = () => undefined
    const clicked: string[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this.download)
    })
    click(q('export-json'))
    expect(clicked).toEqual(['maudesignal-my-company.json'])
    expect(q('data-ok')?.textContent).toMatch(/Exported 1 devices/)
    const json = await new Promise<string>((res) => {
      const r = new FileReader()
      r.onload = () => res(String(r.result))
      r.readAsText(blob as unknown as Blob)
    })
    expect(JSON.parse(json)).toMatchObject({ app: 'maudesignal-my-company', version: 1, company: 'Acme' })
    const before = stored()
    click(q('clear-company'))
    click(q('clear-yes'))
    expect(stored()).toBeNull()
    await pick(file('maudesignal-my-company.json', json))
    expect(stored()).toEqual(before)
  })

  it('Import JSON: bad files give clear errors and change nothing', async () => {
    seed()
    await pick(file('x.json', 'not json'))
    expect(q('import-errors')?.textContent).toMatch(/not valid JSON/)
    await pick(file('x.json', JSON.stringify({ app: 'other', version: 9, devices: [] })))
    expect(q('import-errors')?.textContent).toMatch(/Not a MaudeSignal company export/)
    expect(q('import-errors-heading')?.textContent).toMatch(/This file could not be imported, \d+ problems?/)
    expect(q('import-errors')?.querySelectorAll('li').length).toBeGreaterThan(0)
    expect(stored().devices).toHaveLength(1)
  })

  it('Import JSON: a valid file replaces the company after a confirm; the confirm can be cancelled', async () => {
    seed()
    const doc = { app: 'maudesignal-my-company', version: 1, company: 'Imported Co', devices: [{ ...stored().devices[0], id: 'MY-07', name: 'From file' }] }
    await pick(file('c.json', JSON.stringify(doc)))
    expect(q('import-confirm')?.textContent).toMatch(/Replace your 1 devices with the 1 in the file/)
    click(q('import-confirm')!.querySelectorAll('button')[1])
    expect(q('import-confirm')).toBeNull()
    expect(stored().company).toBe('Acme')
    await pick(file('c.json', JSON.stringify(doc)))
    click(q('import-yes'))
    expect(stored().company).toBe('Imported Co')
    expect(stored().devices[0].name).toBe('From file')
    expect(text()).toContain('From file')
  })

  it('Import JSON into an empty company needs no confirm', async () => {
    show(<Harness />)
    open()
    const doc = { app: 'maudesignal-my-company', version: 1, company: 'Z', devices: [{ id: 'MY-01', name: 'Solo', product_code: 'LLZ', k_number: null, added: '2026-10-31', source: 'json', note: null, k_check: 'not checked yet', status: 'Monitoring — nothing open', history: [{ seq: 1, date: '2026-10-31', from: null, to: 'Monitoring — nothing open' }] }] }
    await pick(file('c.json', JSON.stringify(doc)))
    expect(q('import-confirm')).toBeNull()
    expect(text()).toContain('Solo')
  })

  it('Clear asks first; keeping it changes nothing; confirming removes the stored company', () => {
    seed()
    click(q('clear-company'))
    expect(q('clear-confirm')?.textContent).toMatch(/cannot be undone/)
    click(q('clear-keep'))
    expect(stored().devices).toHaveLength(1)
    click(q('clear-company'))
    click(q('clear-yes'))
    expect(stored()).toBeNull()
    expect(q('no-devices')).not.toBeNull()
  })
})

describe('storage blocked', () => {
  it('everything still works in memory, with a note', () => {
    const boom = () => {
      throw new Error('blocked')
    }
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(boom)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(boom)
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(boom)
    show(<Harness />)
    expect(q('memory-note')).toBeNull() // simulated company: nothing to warn about
    open()
    expect(q('memory-note')?.textContent).toMatch(/kept in memory only/)
    type('in-code', 'LLZ')
    submit('add-code')
    expect(text()).toContain('Product code LLZ')
    expect(q('memory-note')).not.toBeNull()
  })
})

describe('device page: forward-only status, local only', () => {
  it('lists only later statuses and records the move', async () => {
    const { CompanyDeviceView } = await import('./components/OurDevices')
    function Page() {
      const my = useMineState()
      const built = useMemo(() => buildMyCompany(my.mine, C, S), [my.mine])
      const d = built.devices[0]
      const api: MineApi = { mode: 'mine', setMode: my.setMode, mine: my.mine, persisted: my.persisted, known: new Set(), flagged: new Set([HOT]), apiBase: null, setCompany: my.setCompany, add: (i) => my.add(i, new Set([HOT])), move: my.move, remove: my.remove, replace: my.replace, clear: my.clear }
      return (
        <MineContext.Provider value={api}>
          {d ? <CompanyDeviceView company={built} device={d} onBack={() => undefined} /> : <button data-testid="seed" onClick={() => api.add([{ name: 'Dev', product_code: HOT, k_number: 'K123456', source: 'code' }])}>seed</button>}
        </MineContext.Provider>
      )
    }
    show(<Page />)
    click(q('seed'))
    const moves = () => [...host.querySelectorAll('[data-testid="move-status"]')].map((b) => b.textContent)
    expect(moves()).toEqual(['Move to Testing in progress', 'Move to Already covered', 'Move to Not applicable to our device', 'Move to Monitoring — nothing open'])
    expect(q('k-check')?.textContent).toMatch(/not checked yet/)
    click([...host.querySelectorAll('[data-testid="move-status"]')][0])
    expect(moves()).not.toContain('Move to Testing in progress')
    expect(moves().some((m) => /Needs review/.test(m ?? ''))).toBe(false)
    expect(stored().devices[0].status).toBe('Testing in progress')
    expect(q('history')?.textContent).toMatch(/Needs review → Testing in progress/)
    expect(text()).toContain('kept only in this browser')
  })
})

describe('alert buddy', () => {
  const items: AlertItem[] = [
    { id: 'sweep:AAA', kind: 'severity_escalation', productCode: 'AAA', label: 'More serious than usual', source: 'sweep', date: '2026-10-30', detail: '5 reports this week' },
    { id: 'sweep:BBB', kind: 'new_signal', productCode: 'BBB', label: 'New kind of problem', source: 'sweep', date: '2026-10-30', detail: '3 reports this week' },
  ]
  beforeEach(() => resetBubbleSeen())
  it('is calm with nothing to look at: a picture with a label, not a control, no bubble', () => {
    show(<AlertBuddy items={[]} count={0} onOpen={() => undefined} />)
    const b = q('alert-buddy')!
    expect(b.getAttribute('data-state')).toBe('calm')
    expect(b.getAttribute('role')).toBe('img')
    expect(b.getAttribute('aria-label')).toBe(buddyLabel(0))
    expect(b.tagName).toBe('SPAN')
    expect(q('buddy-bubble')).toBeNull()
    expect(q('buddy-svg')?.getAttribute('class')).not.toContain('alert')
  })
  it('with alerts it is a button with the count in its label (no second badge next to the bell) and a speech bubble', () => {
    show(<AlertBuddy items={items} count={2} onOpen={() => undefined} />)
    const b = q('alert-buddy')!
    expect(b.tagName).toBe('BUTTON')
    expect(b.getAttribute('data-state')).toBe('alert')
    expect(b.getAttribute('aria-label')).toBe('Alert buddy: 2 alerts need a look. Open the first one.')
    expect(q('buddy-bubble')?.textContent).toBe('2 alerts need a look')
    expect(q('buddy-badge')).toBeNull()
    expect(q('buddy-svg')?.getAttribute('class')).toContain('ms-buddy-svg--alert')
  })
  it('the speech bubble goes away after a few seconds and comes back on hover; the state stays in the label and badge', () => {
    vi.useFakeTimers()
    try {
      show(<AlertBuddy items={items} count={2} onOpen={() => undefined} />)
      expect(q('buddy-bubble')).not.toBeNull()
      act(() => {
        vi.advanceTimersByTime(BUBBLE_MS + 10)
      })
      expect(q('buddy-bubble')).toBeNull()
      expect(q('alert-buddy')!.getAttribute('aria-label')).toMatch(/2 alerts need a look/)
      act(() => {
        q('alert-buddy')!.parentElement!.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))
        q('alert-buddy')!.parentElement!.dispatchEvent(new MouseEvent('mouseenter'))
      })
      act(() => q('alert-buddy')!.focus())
      expect(q('buddy-bubble')).not.toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })
  it('the bubble opens once per session: a second mount shows none until hover', () => {
    show(<AlertBuddy items={items} count={2} onOpen={() => undefined} />)
    expect(q('buddy-bubble')).not.toBeNull()
    show(<span />)
    show(<AlertBuddy items={items} count={3} onOpen={() => undefined} />)
    expect(q('buddy-bubble')).toBeNull()
  })
  it('says "1 alert needs a look" for one', () => {
    expect(buddyText(1)).toBe('1 alert needs a look')
    expect(buddyText(3)).toBe('3 alerts need a look')
  })
  it('click opens the first alert panel; Enter on the focused button does too (a button activates on Enter)', () => {
    const opened: string[] = []
    show(<AlertBuddy items={items} count={2} onOpen={(a) => opened.push(a.id)} />)
    click(q('alert-buddy'))
    expect(opened).toEqual(['sweep:AAA'])
    expect(q('alert-buddy')!.getAttribute('type')).toBe('button')
    expect((q('alert-buddy') as HTMLButtonElement).disabled).toBe(false)
  })
  it('reduced motion: the stylesheet turns the animation off and the colour and badge do not depend on it', () => {
    const css = readFileSync(join(__dirname, 'buddy.css'), 'utf8')
    const reduced = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'))
    expect(reduced).toMatch(/\.ms-buddy-svg[\s\S]*animation: none/)
    // The danger colour comes from a token, outside any animation rule.
    expect(css).toMatch(/\.ms-buddy-svg--alert \.ms-buddy-body \{\s*fill: var\(--critical\)/)
    // Tokens only: no literal colours in the buddy stylesheet.
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(/)
  })
})

describe('UI fix round', () => {
  it('plain-language import errors drop developer paths', () => {
    expect(plainImportError('devices[0].name must be text of 1 to 120 characters.')).toBe('Row 1: name must be text of 1 to 120 characters.')
    expect(plainImportError('devices[2] is not an object.')).toBe('Row 3: is not an object.')
    expect(plainImportError('devices must be a list.')).toBe('devices must be a list.')
  })
  it('your company gets its own banner style (not the amber of the simulated one), with the stays-in-browser note by the add buttons', () => {
    show(<Harness />)
    expect(q('company-banner')?.className).toContain('ms-banner--warn')
    open()
    expect(q('company-banner')?.className).toContain('ms-banner--mine')
    expect(q('company-banner')?.className).not.toContain('ms-banner--warn')
    expect(q('stays-note')?.textContent).toMatch(/Stays in this browser/)
    click(q('method-csv'))
    expect(q('stays-note')).toBeNull() // shown with the CSV import button once there is a preview
    type('in-csv-text', 'name,product_code\nA,LLZ\n')
    expect(q('stays-note')).not.toBeNull()
  })
  it('the clear confirm puts the safe choice first and focused, offers Export first, and uses the danger colour for the destructive one', () => {
    show(<Harness />)
    open()
    type('in-company', 'Acme')
    type('in-code', HOT)
    submit('add-code')
    click(q('clear-company'))
    const buttons = Array.from(q('clear-confirm')!.querySelectorAll('button'))
    expect(buttons.map((b) => b.textContent)).toEqual(['Keep it', 'Export first', 'Yes, clear it'])
    expect(q('clear-keep')).toBe(document.activeElement)
    expect(q('clear-yes')!.getAttribute('style')).toContain('var(--critical)')
    expect(q('clear-yes')!.className).not.toContain('ws-btn-primary')
  })
  it('the buddy stylesheet hides the bubble on phones and the wide-screen buddy is 32 px or more', () => {
    const css = readFileSync(join(__dirname, 'buddy.css'), 'utf8')
    expect(css).toMatch(/max-width: 639px\)\s*\{\s*\.ms-buddy-bubble\s*\{\s*display: none/)
    expect(css).toMatch(/min-width: 768px\)[^@]*width: 36px/)
  })
})
