// Make it yours: storage (including blocked storage), CSV, import validation, export round-trip, clear, forward-only
// statuses, the simulated default, the K-number look-up and the company the views show. No DOM, no network.
import { describe, expect, it } from 'vitest'
import company from '../public/data/company.json'
import sweep from '../public/data/sweep.json'
import briefs from '../public/data/briefs.json'
import { alertItems } from './dashboard'
import {
  MINE_BANNER,
  MINE_KEY,
  MODE_KEY,
  NOT_CHECKED,
  UNKNOWN_CODE_NOTE,
  addDevices,
  buildMyCompany,
  canMove,
  checkCode,
  clearMine,
  emptyMine,
  exportJson,
  flaggedCodes,
  isKNumber,
  knownCodes,
  loadMine,
  loadMode,
  lookupKNumber,
  nextStatuses,
  parseCsv,
  parseLookup,
  removeDevice,
  saveMine,
  saveMode,
  setCompanyName,
  setDeviceStatus,
  validateImport,
  type NewDevice,
  type Store,
} from './myCompany'
import type { Brief, Company, Sweep } from './types'

const C = company as unknown as Company
const S = sweep as unknown as Sweep
const B = briefs.briefs as unknown as Brief[]

const memoryStore = (): Store & { data: Map<string, string> } => {
  const data = new Map<string, string>()
  return { data, get: (k) => data.get(k) ?? null, set: (k, v) => void data.set(k, v), remove: (k) => void data.delete(k) }
}
const blocked: Store = {
  get: () => {
    throw new Error('blocked')
  },
  set: () => {
    throw new Error('blocked')
  },
  remove: () => {
    throw new Error('blocked')
  },
}
const flagged = flaggedCodes(S)
const dev = (o: Partial<NewDevice> = {}): NewDevice => ({ name: 'Scanner', product_code: 'LLZ', k_number: null, source: 'code', ...o })

describe('codes and K-numbers', () => {
  it('accepts 3 letters, upper-cases them and rejects anything else', () => {
    expect(checkCode(' llz ', new Set(['LLZ']))).toMatchObject({ ok: true, code: 'LLZ', note: null })
    for (const bad of ['', 'LL', 'LLZZ', 'L1Z', '123', 'L Z']) expect(checkCode(bad, new Set()).ok).toBe(false)
  })
  it('accepts a code the site does not know, with a note', () => {
    expect(checkCode('ZZZ', new Set(['LLZ']))).toMatchObject({ ok: true, note: UNKNOWN_CODE_NOTE })
  })
  it('knows the codes from the sweep, the briefs and the simulated company', () => {
    const k = knownCodes(S, B, C)
    expect(k.has('LLZ')).toBe(true)
    for (const r of S.rows.slice(0, 5)) expect(k.has(r.product_code)).toBe(true)
  })
  it('a K-number is K and 6 digits', () => {
    expect(isKNumber('K123456')).toBe(true)
    for (const bad of ['k123456', 'K12345', 'K1234567', 'DEN123456', '']) expect(isKNumber(bad)).toBe(false)
  })
})

describe('storage', () => {
  it('starts empty and persisted when storage works', () => {
    const st = memoryStore()
    expect(loadMine(st)).toEqual({ value: emptyMine(), persisted: true })
  })
  it('round-trips through a versioned key', () => {
    const st = memoryStore()
    const c = addDevices(setCompanyName(emptyMine(), 'Acme'), [dev()], flagged, '2026-10-31')
    expect(saveMine(c, st)).toBe(true)
    expect(MINE_KEY).toMatch(/-v1$/)
    expect(st.data.has(MINE_KEY)).toBe(true)
    expect(loadMine(st).value).toEqual(c)
  })
  it('works when storage is blocked: nothing throws, the data is reported as not persisted', () => {
    expect(loadMine(blocked)).toEqual({ value: emptyMine(), persisted: false })
    expect(saveMine(emptyMine(), blocked)).toBe(false)
    expect(clearMine(blocked)).toBe(false)
    expect(loadMode(blocked)).toBe('demo')
    expect(() => saveMode('mine', blocked)).not.toThrow()
  })
  it('ignores a stored value that is corrupt or fails validation', () => {
    const st = memoryStore()
    st.data.set(MINE_KEY, '{not json')
    expect(loadMine(st).value).toEqual(emptyMine())
    st.data.set(MINE_KEY, JSON.stringify({ version: 1, company: 'x', devices: [{ id: 'bad' }] }))
    expect(loadMine(st).value).toEqual(emptyMine())
  })
  it('the simulated company is the default for new visitors', () => {
    const st = memoryStore()
    expect(loadMode(st)).toBe('demo')
    saveMode('mine', st)
    expect(st.data.get(MODE_KEY)).toBe('mine')
    expect(loadMode(st)).toBe('mine')
    st.data.set(MODE_KEY, 'something else')
    expect(loadMode(st)).toBe('demo')
  })
  it('clear removes the stored company', () => {
    const st = memoryStore()
    saveMine(addDevices(emptyMine(), [dev()], flagged), st)
    expect(clearMine(st)).toBe(true)
    expect(loadMine(st).value.devices).toHaveLength(0)
  })
})

describe('CSV', () => {
  const csv = 'name,product_code,k_number\nVellmar Viewer,llz,K123456\n"Quoted, Name",QIH,\nNo ids,,\nBad code,AB1,\nBad k,LLZ,K12\n,LLZ,\nVellmar Viewer,LLZ,K123456\n'
  it('keeps valid rows and reports each problem with its line', () => {
    const r = parseCsv(csv)
    expect(r.rows.map((x) => [x.name, x.product_code, x.k_number])).toEqual([
      ['Vellmar Viewer', 'LLZ', 'K123456'],
      ['Quoted, Name', 'QIH', null],
    ])
    const lines = r.errors.map((e) => e.line)
    expect(lines).toEqual([4, 5, 6, 7, 8])
    expect(r.errors[3].message).toMatch(/name is empty/)
    expect(r.errors[4].message).toMatch(/duplicate/)
  })
  it('handles CRLF, a BOM and quotes with doubled quotes and line breaks', () => {
    const r = parseCsv('﻿name,product_code\r\n"A ""big"" one\nline",LLZ\r\n')
    expect(r.errors).toEqual([])
    expect(r.rows[0].name).toBe('A "big" one\nline')
  })
  it('needs the right header', () => {
    expect(parseCsv('foo,bar\n1,2').errors[0].message).toMatch(/"name" column/)
    expect(parseCsv('name\nX').errors[0].message).toMatch(/product_code|k_number/)
    expect(parseCsv('').errors[0].message).toMatch(/empty/)
    expect(parseCsv('name,product_code\n').errors[0].message).toMatch(/no devices/)
    expect(parseCsv('name,product_code\n"open,LLZ').errors[0].message).toMatch(/quoted/)
  })
  it('refuses more than 200 devices and files over the size limit', () => {
    const many = 'name,product_code\n' + Array.from({ length: 201 }, (_, i) => `D${i},LLZ`).join('\n')
    expect(parseCsv(many).errors[0].message).toMatch(/At most 200/)
    expect(parseCsv('name,product_code\n' + 'x'.repeat(210_000)).errors[0].message).toMatch(/larger than/)
  })
  it('flags a row that is already in the company', () => {
    const have = addDevices(emptyMine(), [dev({ name: 'Scanner' })], flagged).devices
    expect(parseCsv('name,product_code\nScanner,LLZ', have).errors[0].message).toMatch(/duplicate/)
  })
})

describe('devices and statuses', () => {
  it('a device starts in Needs review only when the sweep flags its code, else Monitoring', () => {
    const hot = [...flagged][0]
    expect(hot).toBeTruthy()
    const c = addDevices(emptyMine(), [dev({ name: 'Hot', product_code: hot }), dev({ name: 'Quiet', product_code: 'ZZZ' })], flagged, '2026-10-31')
    expect(c.devices[0].status).toBe('Needs review')
    expect(c.devices[1].status).toBe('Monitoring — nothing open')
    expect(c.devices.map((d) => d.id)).toEqual(['MY-01', 'MY-02'])
    expect(c.devices[0].k_check).toBe(NOT_CHECKED)
  })
  it('status moves forward only, never back and never sideways', () => {
    expect(canMove('Needs review', 'Testing in progress')).toBe(true)
    expect(canMove('Testing in progress', 'Needs review')).toBe(false)
    expect(canMove('Already covered', 'Not applicable to our device')).toBe(false)
    expect(canMove('Monitoring — nothing open', 'Needs review')).toBe(false)
    expect(nextStatuses('Monitoring — nothing open')).toEqual([])
    const hot = [...flagged][0]
    let c = addDevices(emptyMine(), [dev({ product_code: hot })], flagged, '2026-10-30')
    const same = setDeviceStatus(c, 'MY-01', 'Needs review', '2026-10-31')
    expect(same).toBe(c)
    c = setDeviceStatus(c, 'MY-01', 'Testing in progress', '2026-10-31')
    expect(c.devices[0].history.map((h) => [h.from, h.to])).toEqual([[null, 'Needs review'], ['Needs review', 'Testing in progress']])
    expect(setDeviceStatus(c, 'MY-01', 'Needs review')).toBe(c)
    expect(setDeviceStatus(c, 'MY-99', 'Already covered')).toBe(c)
  })
  it('remove drops one device and ids are not reused while a higher one exists', () => {
    let c = addDevices(emptyMine(), [dev(), dev({ name: 'B' }), dev({ name: 'C' })], flagged)
    c = removeDevice(c, 'MY-02')
    c = addDevices(c, [dev({ name: 'D' })], flagged)
    expect(c.devices.map((d) => d.id)).toEqual(['MY-01', 'MY-03', 'MY-04'])
  })
})

describe('export and import', () => {
  const hot = [...flagged][0]
  const base = () => {
    let c = setCompanyName(emptyMine(), 'Acme Devices')
    c = addDevices(c, [dev({ name: 'One', product_code: hot, k_number: 'K123456', note: 'n', k_check: 'checked' }), dev({ name: 'Two', product_code: null, k_number: 'K654321', source: 'csv' })], flagged, '2026-10-30')
    return setDeviceStatus(c, 'MY-01', 'Testing in progress', '2026-10-31')
  }
  it('an export imports back to the same company', () => {
    const c = base()
    const r = validateImport(JSON.parse(exportJson(c, '2026-10-31T00:00:00Z')))
    expect(r).toEqual({ ok: true, company: c })
  })
  it('names the app and the version in the file', () => {
    const j = JSON.parse(exportJson(base(), '2026-10-31T00:00:00Z'))
    expect(j).toMatchObject({ app: 'maudesignal-my-company', version: 1, company: 'Acme Devices' })
  })
  it('rejects a file with clear messages', () => {
    const good = JSON.parse(exportJson(base()))
    const bad = (mut: (j: Record<string, unknown>) => void) => {
      const j = structuredClone(good)
      mut(j)
      const r = validateImport(j)
      expect(r.ok).toBe(false)
      return r.ok ? [] : r.errors.join(' | ')
    }
    expect(validateImport('x')).toMatchObject({ ok: false })
    expect(validateImport([])).toMatchObject({ ok: false })
    expect(bad((j) => (j.app = 'other'))).toMatch(/Not a MaudeSignal company export/)
    expect(bad((j) => (j.version = 2))).toMatch(/Unsupported version/)
    expect(bad((j) => (j.devices = 'x'))).toMatch(/devices must be a list/)
    expect(bad((j) => (j.company = 'x'.repeat(81)))).toMatch(/company must be text/)
    expect(bad((j) => ((j.devices as Record<string, unknown>[])[0].product_code = 'ab'))).toMatch(/product_code must be 3 capital letters/)
    expect(bad((j) => ((j.devices as Record<string, unknown>[])[0].k_number = 'K1'))).toMatch(/k_number must be K and 6 digits/)
    expect(bad((j) => ((j.devices as Record<string, unknown>[])[0].status = 'Done'))).toMatch(/status is not one of/)
    expect(bad((j) => ((j.devices as Record<string, unknown>[])[0].name = ''))).toMatch(/name must be text/)
    expect(bad((j) => ((j.devices as Record<string, unknown>[])[1].id = 'MY-01'))).toMatch(/used twice/)
    expect(bad((j) => ((j.devices as Record<string, unknown>[])[0].source = 'x'))).toMatch(/source is not one of/)
    expect(bad((j) => ((j.devices as Record<string, unknown>[])[0].added = 'yesterday'))).toMatch(/added must be a date/)
    expect(bad((j) => ((j.devices as Record<string, unknown>[])[0].history = []))).toMatch(/history must be a list/)
  })
  it('rejects a history that goes backwards or does not end on the status', () => {
    const j = JSON.parse(exportJson(base()))
    const d = j.devices[0]
    d.history = [
      { seq: 1, date: '2026-10-30', from: null, to: 'Testing in progress' },
      { seq: 2, date: '2026-10-31', from: 'Testing in progress', to: 'Needs review' },
    ]
    d.status = 'Needs review'
    const r = validateImport(j)
    expect(r.ok).toBe(false)
    expect(r.ok ? '' : r.errors.join(' ')).toMatch(/not a forward move/)
    const k = JSON.parse(exportJson(base()))
    k.devices[0].status = 'Already covered'
    const r2 = validateImport(k)
    expect(r2.ok ? '' : r2.errors.join(' ')).toMatch(/does not match the last history entry/)
  })
  it('rejects more than 200 devices and needs a code or a K-number', () => {
    const j = JSON.parse(exportJson(base()))
    j.devices = Array.from({ length: 201 }, () => j.devices[0])
    expect(validateImport(j)).toMatchObject({ ok: false })
    const k = JSON.parse(exportJson(base()))
    k.devices[1].k_number = null
    const r = validateImport(k)
    expect(r.ok ? '' : r.errors.join(' ')).toMatch(/needs a product_code or a k_number/)
  })
})

describe('K-number look-up (API)', () => {
  const key = { header: 'X-API-Key', value: 'demo' }
  const reply = (body: unknown, status = 200) => async () => new Response(JSON.stringify(body), { status })
  it('sends nothing without an API address or a key', async () => {
    let calls = 0
    const f = async () => (calls++, new Response('{}'))
    expect(await lookupKNumber('K123456', null, key, f)).toMatchObject({ checked: false, text: NOT_CHECKED })
    expect(await lookupKNumber('K123456', 'https://x.test', null, f)).toMatchObject({ checked: false, text: NOT_CHECKED })
    expect(await lookupKNumber('bad', 'https://x.test', key, f)).toMatchObject({ checked: false })
    expect(calls).toBe(0)
  })
  it('sends only the K-number, with the key in the header and no credentials', async () => {
    let seen: { url: string; init?: RequestInit } | null = null
    const f = async (url: string, init?: RequestInit) => {
      seen = { url, init }
      return new Response(JSON.stringify({ device: { device_name: 'Viewer', applicant: 'Acme', product_code: 'llz' } }))
    }
    const r = await lookupKNumber('K123456', 'https://api.test', key, f)
    expect(seen!.url).toBe('https://api.test/v1/tools/lookup_device?k_number=K123456')
    expect(seen!.init?.headers).toEqual({ 'X-API-Key': 'demo' })
    expect(seen!.init?.credentials).toBe('omit')
    expect(seen!.init?.body).toBeUndefined()
    expect(r).toMatchObject({ found: true, checked: true, device_name: 'Viewer', product_code: 'LLZ' })
  })
  it('stores "not checked yet" on a server error, a network error or an odd body, and says so when no record exists', async () => {
    expect((await lookupKNumber('K123456', 'https://a.test', key, reply({}, 500))).text).toBe(NOT_CHECKED)
    expect((await lookupKNumber('K123456', 'https://a.test', key, reply({}, 404))).text).toBe(NOT_CHECKED)
    expect((await lookupKNumber('K123456', 'https://a.test', key, async () => Promise.reject(new Error('down')))).text).toBe(NOT_CHECKED)
    const none = await lookupKNumber('K123456', 'https://a.test', key, reply({ found: false }))
    expect(none).toMatchObject({ found: false, checked: true })
    expect(none.text).toMatch(/no 510\(k\) record/)
    expect(parseLookup('x', 'K123456')).toBeNull()
  })
})

describe('the company the views show', () => {
  const hot = [...flagged][0]
  const mine = addDevices(setCompanyName(emptyMine(), 'Acme'), [dev({ name: 'Mine A', product_code: hot }), dev({ name: 'Mine B', product_code: 'LLZ' }), dev({ name: 'Mine C', product_code: 'ZZZ' })], flagged, '2026-10-31')
  const built = buildMyCompany(mine, C, S)
  it('has the banner, the flag and no audit chain', () => {
    expect(built.mine).toBe(true)
    expect(built.banner).toBe(MINE_BANNER)
    expect(built.company).toBe('Acme')
    expect(built.audit.chain_ok).toBeNull()
    expect(built.statuses).toEqual(C.statuses)
  })
  it('attaches the stored real evidence where the code has some, and says "not fetched yet" where not', () => {
    const b = built.devices.find((d) => d.name === 'Mine B')!
    const stored = C.devices.find((d) => d.product_code === 'LLZ' && d.evidence.available)!
    expect(b.evidence).toEqual(stored.evidence)
    expect(b.patterns).toEqual(stored.patterns)
    const c = built.devices.find((d) => d.name === 'Mine C')!
    expect(c.evidence.available).toBe(false)
    expect(c.evidence.note).toBe('evidence not fetched yet')
    expect(c.patterns).toEqual([])
  })
  it('alert counts: only Needs review devices alert, and they are marked as yours', () => {
    const items = alertItems(S, B, built)
    const mineAlerts = items.filter((a) => a.source === 'company')
    expect(mineAlerts.map((a) => a.deviceName)).toEqual(['Mine A'])
    expect(mineAlerts[0]).toMatchObject({ mine: true, id: 'company:MY-01' })
    expect(alertItems(S, B, C).some((a) => a.mine)).toBe(false)
  })
  it('the shipped simulated company is not changed by building yours', () => {
    expect(C.banner).toBe('Simulated company — sample data. Problem evidence is real FDA data.')
    expect(C.mine).toBeUndefined()
  })
})
