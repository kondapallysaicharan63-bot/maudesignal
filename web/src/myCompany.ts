// "Make it yours": a person's own company and devices, kept only in this browser (localStorage, versioned key).
// Everything here is pure or takes the storage as an argument, so it is tested without a DOM. Nothing in this file
// calls the network except lookupKNumber, which sends only a K-number and only when an API address and a demo key exist.
import { NEEDS_REVIEW } from './dashboard'
import type { Brief, Company, CompanyDevice, CompanyHistoryEntry, Sweep } from './types'

export const MINE_KEY = 'ms-my-company-v1'
export const MODE_KEY = 'ms-company-mode-v1'
export const MINE_BANNER = 'Your company — your data stays in your browser'
export const EXPORT_APP = 'maudesignal-my-company'
export const SCHEMA_VERSION = 1
export const MAX_DEVICES = 200
export const MAX_CSV_BYTES = 200_000
export const MAX_JSON_BYTES = 400_000
export const ACTOR = 'You (this browser)'
export const NOT_CHECKED = 'not checked yet'
export const MEMORY_NOTE =
  'This browser blocks storage, so your company is kept in memory only and is lost when you close or reload the tab. Use Export JSON to keep a copy.'

/** The statuses and their order (the same forward-only ranks as the simulated company). */
export const STATUSES: { label: string; rank: number }[] = [
  { label: 'Needs review', rank: 1 },
  { label: 'Testing in progress', rank: 2 },
  { label: 'Already covered', rank: 3 },
  { label: 'Not applicable to our device', rank: 3 },
  { label: 'Monitoring — nothing open', rank: 4 },
]
const rankOf = (label: string): number => STATUSES.find((s) => s.label === label)?.rank ?? -1
export const isStatus = (label: unknown): label is string => typeof label === 'string' && rankOf(label) > 0

/** A status only moves to a later one (a higher rank); it never goes back and never moves sideways. */
export const canMove = (from: string, to: string): boolean => rankOf(from) > 0 && rankOf(to) > rankOf(from)
/** The statuses a device can move to from `from`. */
export const nextStatuses = (from: string): string[] => STATUSES.filter((s) => canMove(from, s.label)).map((s) => s.label)

export type DeviceSource = 'code' | 'k_number' | 'csv' | 'label' | 'json'
export interface MineHistory {
  seq: number
  date: string
  from: string | null
  to: string
}
export interface MineDevice {
  id: string
  name: string
  product_code: string | null
  k_number: string | null
  added: string
  source: DeviceSource
  /** Note shown with the device, e.g. a product code the site does not know. */
  note: string | null
  /** "not checked yet" or what the K-number look-up returned. */
  k_check: string
  status: string
  history: MineHistory[]
}
export interface MineCompany {
  version: 1
  company: string
  devices: MineDevice[]
}
export const emptyMine = (): MineCompany => ({ version: 1, company: '', devices: [] })

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const today = (): string => new Date().toISOString().slice(0, 10)

// ── Storage ──────────────────────────────────────────────────────────────

export interface Loaded<T> {
  value: T
  /** False when the storage could not be read or written (blocked): the data then lives in memory only. */
  persisted: boolean
}
export interface Store {
  get(k: string): string | null
  set(k: string, v: string): void
  remove(k: string): void
}
/** The browser's localStorage; every call may throw (private window, blocked site data). */
export const browserStore: Store = {
  get: (k) => localStorage.getItem(k),
  set: (k, v) => localStorage.setItem(k, v),
  remove: (k) => localStorage.removeItem(k),
}

/** Reads the company; a stored value that fails validation is ignored (an empty company), never trusted. */
export function loadMine(store: Store = browserStore): Loaded<MineCompany> {
  let raw: string | null
  try {
    raw = store.get(MINE_KEY)
  } catch {
    return { value: emptyMine(), persisted: false }
  }
  if (raw === null) return { value: emptyMine(), persisted: probe(store) }
  try {
    const r = validateImport(JSON.parse(raw) as unknown, true)
    return { value: r.ok ? r.company : emptyMine(), persisted: true }
  } catch {
    return { value: emptyMine(), persisted: true }
  }
}

function probe(store: Store): boolean {
  try {
    store.set('ms-probe', '1')
    store.remove('ms-probe')
    return true
  } catch {
    return false
  }
}

/** Writes the company; false when storage is blocked (the caller keeps the data in memory and shows MEMORY_NOTE). */
export function saveMine(c: MineCompany, store: Store = browserStore): boolean {
  try {
    store.set(MINE_KEY, JSON.stringify(c))
    return true
  } catch {
    return false
  }
}

export function clearMine(store: Store = browserStore): boolean {
  try {
    store.remove(MINE_KEY)
    return true
  } catch {
    return false
  }
}

export type Mode = 'demo' | 'mine'
/** The chosen view. Anything but a stored "mine" is the simulated Demo MedTech Co. (the default for new visitors). */
export function loadMode(store: Store = browserStore): Mode {
  try {
    return store.get(MODE_KEY) === 'mine' ? 'mine' : 'demo'
  } catch {
    return 'demo'
  }
}
export function saveMode(m: Mode, store: Store = browserStore): void {
  try {
    store.set(MODE_KEY, m)
  } catch {
    /* kept in memory by the caller */
  }
}

// ── Inputs: product code, K-number ───────────────────────────────────────

export const normalizeCode = (s: string): string => s.trim().toUpperCase()
export const isProductCode = (s: string): boolean => /^[A-Z]{3}$/.test(s)
export const normalizeK = (s: string): string => s.trim().toUpperCase()
export const isKNumber = (s: string): boolean => /^K\d{6}$/.test(s)

/** The product codes this site has stored data for: the sweep, the briefs and the simulated company. */
export function knownCodes(sweep: Sweep | null | undefined, briefs: Brief[] | null | undefined, company: Company | null | undefined): Set<string> {
  const out = new Set<string>()
  for (const r of sweep?.rows ?? []) out.add(r.product_code)
  for (const b of briefs ?? []) {
    for (const c of Object.keys(b.device_types ?? {})) out.add(c)
    for (const s of b.signals ?? []) out.add(s.product_code)
  }
  for (const d of company?.devices ?? []) out.add(d.product_code)
  return out
}

export const UNKNOWN_CODE_NOTE = 'This product code is not one this site has stored data for, so no stored FDA evidence is shown. It is accepted as typed.'

export interface CodeCheck {
  ok: boolean
  code: string
  /** Set for an accepted code the site does not know. */
  note: string | null
  error: string | null
}
export function checkCode(raw: string, known: ReadonlySet<string>): CodeCheck {
  const code = normalizeCode(raw)
  if (!isProductCode(code)) return { ok: false, code, note: null, error: 'A product code is exactly 3 letters, for example LLZ.' }
  return { ok: true, code, note: known.has(code) ? null : UNKNOWN_CODE_NOTE, error: null }
}

// ── CSV ──────────────────────────────────────────────────────────────────

export interface CsvRow {
  line: number
  name: string
  product_code: string | null
  k_number: string | null
}
export interface CsvError {
  line: number
  message: string
}
export interface CsvResult {
  rows: CsvRow[]
  errors: CsvError[]
}

/** Splits CSV text into rows of cells (quotes, doubled quotes, commas and line breaks inside quotes). Null when a quote is never closed. */
export function splitCsv(text: string): string[][] | null {
  const rows: string[][] = []
  let row: string[] = []
  let cell = ''
  let quoted = false
  const s = text.replace(/^﻿/, '')
  for (let i = 0; i < s.length; i++) {
    const ch = s[i]
    if (quoted) {
      if (ch === '"') {
        if (s[i + 1] === '"') {
          cell += '"'
          i++
        } else quoted = false
      } else cell += ch
    } else if (ch === '"' && cell === '') quoted = true
    else if (ch === ',') {
      row.push(cell)
      cell = ''
    } else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && s[i + 1] === '\n') i++
      row.push(cell)
      rows.push(row)
      row = []
      cell = ''
    } else cell += ch
  }
  if (quoted) return null
  if (cell !== '' || row.length > 0) {
    row.push(cell)
    rows.push(row)
  }
  return rows.filter((r) => r.some((c) => c.trim() !== ''))
}

/** Parses the CSV (columns name, product_code, k_number) into valid rows and per-line errors; nothing is imported by this call. */
export function parseCsv(text: string, existing: MineDevice[] = []): CsvResult {
  const out: CsvResult = { rows: [], errors: [] }
  if (new Blob([text]).size > MAX_CSV_BYTES) {
    out.errors.push({ line: 0, message: `The file is larger than ${MAX_CSV_BYTES / 1000} KB.` })
    return out
  }
  const cells = splitCsv(text)
  if (cells === null) {
    out.errors.push({ line: 0, message: 'A quoted value is never closed.' })
    return out
  }
  if (cells.length === 0) {
    out.errors.push({ line: 0, message: 'The file is empty.' })
    return out
  }
  const head = cells[0].map((h) => h.trim().toLowerCase())
  const col = (n: string) => head.indexOf(n)
  const iName = col('name')
  const iCode = col('product_code')
  const iK = col('k_number')
  if (iName < 0) out.errors.push({ line: 1, message: 'The header row needs a "name" column (columns: name, product_code, k_number).' })
  if (iCode < 0 && iK < 0) out.errors.push({ line: 1, message: 'The header row needs a "product_code" or a "k_number" column.' })
  if (out.errors.length > 0) return out
  const body = cells.slice(1)
  if (body.length === 0) out.errors.push({ line: 0, message: 'The file has a header row but no devices.' })
  if (body.length > MAX_DEVICES) out.errors.push({ line: 0, message: `At most ${MAX_DEVICES} devices can be imported (this file has ${body.length}).` })
  if (out.errors.length > 0) return out
  const seen = new Set(existing.map((d) => `${d.name.toLowerCase()}|${d.product_code ?? ''}|${d.k_number ?? ''}`))
  body.forEach((r, i) => {
    const line = i + 2
    const name = (r[iName] ?? '').trim()
    const code = iCode >= 0 ? normalizeCode(r[iCode] ?? '') : ''
    const k = iK >= 0 ? normalizeK(r[iK] ?? '') : ''
    const problems: string[] = []
    if (!name) problems.push('name is empty')
    else if (name.length > 120) problems.push('name is longer than 120 characters')
    if (code && !isProductCode(code)) problems.push(`product_code "${code.slice(0, 12)}" is not 3 letters`)
    if (k && !isKNumber(k)) problems.push(`k_number "${k.slice(0, 12)}" is not K followed by 6 digits`)
    if (!code && !k) problems.push('needs a product_code or a k_number')
    const key = `${name.toLowerCase()}|${code}|${k}`
    if (problems.length === 0 && seen.has(key)) problems.push('is a duplicate')
    if (problems.length > 0) out.errors.push({ line, message: `Line ${line}: ${problems.join('; ')}.` })
    else {
      seen.add(key)
      out.rows.push({ line, name, product_code: code || null, k_number: k || null })
    }
  })
  return out
}

// ── Editing ──────────────────────────────────────────────────────────────

export interface NewDevice {
  name: string
  product_code: string | null
  k_number: string | null
  source: DeviceSource
  note?: string | null
  k_check?: string
}

const nextId = (devices: MineDevice[]): string => {
  const n = devices.reduce((m, d) => Math.max(m, Number(/^MY-(\d+)$/.exec(d.id)?.[1] ?? 0)), 0)
  return `MY-${String(n + 1).padStart(2, '0')}`
}

/**
 * Adds devices. A device starts in "Needs review" only when its product code is flagged by the AI device sweep (the
 * same stored data that drives the alert bell); otherwise it starts in "Monitoring — nothing open". Nothing else is guessed.
 */
export function addDevices(c: MineCompany, inputs: NewDevice[], flagged: ReadonlySet<string>, date: string = today()): MineCompany {
  const devices = [...c.devices]
  for (const x of inputs) {
    if (devices.length >= MAX_DEVICES) break
    const status = x.product_code && flagged.has(x.product_code) ? NEEDS_REVIEW : 'Monitoring — nothing open'
    devices.push({
      id: nextId(devices),
      name: x.name.trim().slice(0, 120),
      product_code: x.product_code,
      k_number: x.k_number,
      added: date,
      source: x.source,
      note: x.note ?? null,
      k_check: x.k_check ?? NOT_CHECKED,
      status,
      history: [{ seq: 1, date, from: null, to: status }],
    })
  }
  return { ...c, devices }
}

/** Moves a device to a later status. Returns the same object when the move is not forward or the device is unknown. */
export function setDeviceStatus(c: MineCompany, id: string, to: string, date: string = today()): MineCompany {
  const d = c.devices.find((x) => x.id === id)
  if (!d || !canMove(d.status, to)) return c
  return {
    ...c,
    devices: c.devices.map((x) =>
      x.id === id ? { ...x, status: to, history: [...x.history, { seq: x.history.length + 1, date, from: x.status, to }] } : x,
    ),
  }
}

export const removeDevice = (c: MineCompany, id: string): MineCompany => ({ ...c, devices: c.devices.filter((d) => d.id !== id) })
export const setCompanyName = (c: MineCompany, name: string): MineCompany => ({ ...c, company: name.trim().slice(0, 80) })

// ── JSON export / import ─────────────────────────────────────────────────

export function exportJson(c: MineCompany, now: string = new Date().toISOString()): string {
  return JSON.stringify({ app: EXPORT_APP, version: SCHEMA_VERSION, exported_utc: now, company: c.company, devices: c.devices }, null, 2)
}

export type ImportResult = { ok: true; company: MineCompany } | { ok: false; errors: string[] }

const str = (v: unknown, max: number): string | null => (typeof v === 'string' && v.length <= max ? v : null)
const DATE = /^\d{4}-\d{2}-\d{2}$/

/** Checks an exported file (or the stored value when `stored`) field by field. Clear messages; nothing is repaired silently. */
export function validateImport(raw: unknown, stored = false): ImportResult {
  const errors: string[] = []
  if (!isObj(raw)) return { ok: false, errors: ['The file is not a JSON object.'] }
  if (!stored && raw.app !== EXPORT_APP) errors.push(`Not a MaudeSignal company export (app should be "${EXPORT_APP}").`)
  if (!stored && raw.version !== SCHEMA_VERSION) errors.push(`Unsupported version ${JSON.stringify(raw.version)?.slice(0, 20)}; this page reads version ${SCHEMA_VERSION}.`)
  if (stored && raw.version !== SCHEMA_VERSION) errors.push('Stored version differs.')
  const company = str(raw.company ?? '', 80)
  if (company === null) errors.push('company must be text of at most 80 characters.')
  if (!Array.isArray(raw.devices)) errors.push('devices must be a list.')
  else if (raw.devices.length > MAX_DEVICES) errors.push(`At most ${MAX_DEVICES} devices (this file has ${raw.devices.length}).`)
  if (errors.length > 0 || !Array.isArray(raw.devices)) return { ok: false, errors }
  const devices: MineDevice[] = []
  const ids = new Set<string>()
  raw.devices.forEach((x: unknown, i: number) => {
    const at = `devices[${i}]`
    if (!isObj(x)) return void errors.push(`${at} is not an object.`)
    const id = typeof x.id === 'string' && /^MY-\d{1,4}$/.test(x.id) ? x.id : null
    if (!id) errors.push(`${at}.id must look like MY-01.`)
    else if (ids.has(id)) errors.push(`${at}.id ${id} is used twice.`)
    else ids.add(id)
    const name = str(x.name, 120)
    if (!name || !name.trim()) errors.push(`${at}.name must be text of 1 to 120 characters.`)
    const code = x.product_code === null || x.product_code === undefined ? null : typeof x.product_code === 'string' && isProductCode(x.product_code) ? x.product_code : false
    if (code === false) errors.push(`${at}.product_code must be 3 capital letters or null.`)
    const k = x.k_number === null || x.k_number === undefined ? null : typeof x.k_number === 'string' && isKNumber(x.k_number) ? x.k_number : false
    if (k === false) errors.push(`${at}.k_number must be K and 6 digits or null.`)
    if (code === null && k === null) errors.push(`${at} needs a product_code or a k_number.`)
    const added = typeof x.added === 'string' && DATE.test(x.added) ? x.added : null
    if (!added) errors.push(`${at}.added must be a date like 2026-10-31.`)
    const source = (['code', 'k_number', 'csv', 'label', 'json'] as const).find((s) => s === x.source)
    if (!source) errors.push(`${at}.source is not one of code, k_number, csv, label, json.`)
    const note = x.note === null || x.note === undefined ? null : str(x.note, 300)
    if (x.note !== null && x.note !== undefined && note === null) errors.push(`${at}.note must be text of at most 300 characters.`)
    const kCheck = str(x.k_check ?? NOT_CHECKED, 300)
    if (kCheck === null) errors.push(`${at}.k_check must be text of at most 300 characters.`)
    if (!isStatus(x.status)) errors.push(`${at}.status is not one of the known statuses.`)
    const hist = checkHistory(x.history, at, errors)
    if (hist && isStatus(x.status) && hist.length > 0 && hist[hist.length - 1].to !== x.status)
      errors.push(`${at}.status does not match the last history entry.`)
    if (errors.length === 0 && id && name && code !== false && k !== false && added && source && kCheck !== null && isStatus(x.status) && hist)
      devices.push({ id, name: name.trim(), product_code: code, k_number: k, added, source, note, k_check: kCheck, status: x.status, history: hist })
  })
  if (errors.length > 0) return { ok: false, errors: errors.slice(0, 12) }
  return { ok: true, company: { version: 1, company: (company ?? '').trim(), devices } }
}

/** History must start with a registration and only move forward. */
function checkHistory(raw: unknown, at: string, errors: string[]): MineHistory[] | null {
  if (!Array.isArray(raw) || raw.length === 0 || raw.length > 10) {
    errors.push(`${at}.history must be a list of 1 to 10 entries.`)
    return null
  }
  const out: MineHistory[] = []
  for (let j = 0; j < raw.length; j++) {
    const h: unknown = raw[j]
    if (!isObj(h) || typeof h.date !== 'string' || !DATE.test(h.date) || !isStatus(h.to) || (h.from !== null && !isStatus(h.from))) {
      errors.push(`${at}.history[${j}] needs date, from (or null) and to (a known status).`)
      return null
    }
    const from = h.from as string | null
    if (j === 0 ? from !== null : from !== out[j - 1].to || !canMove(from, h.to)) {
      errors.push(`${at}.history[${j}] is not a forward move from the one before it.`)
      return null
    }
    out.push({ seq: j + 1, date: h.date, from, to: h.to })
  }
  return out
}

// ── K-number look-up (API) ───────────────────────────────────────────────

export const LOOKUP_PATH = '/v1/tools/lookup_device'
export interface KLookup {
  /** True when the API answered with a record for this K-number. */
  found: boolean
  checked: boolean
  device_name: string | null
  applicant: string | null
  product_code: string | null
  /** The line stored in the device's k_check field. */
  text: string
}
export const NOT_CHECKED_RESULT: KLookup = { found: false, checked: false, device_name: null, applicant: null, product_code: null, text: NOT_CHECKED }

type Fetcher = (url: string, init?: RequestInit) => Promise<Response>
const pick = (o: Record<string, unknown>, ...keys: string[]): string | null => {
  for (const k of keys) if (typeof o[k] === 'string' && (o[k] as string).trim()) return (o[k] as string).trim().slice(0, 200)
  return null
}

/** Reads a lookup_device answer (the record may sit at the top or under facts/result/device); null when it holds no record. */
export function parseLookup(body: unknown, k: string): KLookup | null {
  if (!isObj(body)) return null
  const inner = [body.device, body.result, body.facts, body.record].find(isObj) ?? body
  const rec = isObj(inner) ? inner : body
  const name = pick(rec, 'device_name', 'name')
  const code = pick(rec, 'product_code')
  const applicant = pick(rec, 'applicant')
  if (!name && !code && !applicant) return null
  const pc = code && isProductCode(code.toUpperCase()) ? code.toUpperCase() : null
  return {
    found: true,
    checked: true,
    device_name: name,
    applicant,
    product_code: pc,
    text: `checked with the FDA 510(k) record ${k}${name ? `: ${name}` : ''}${applicant ? ` (${applicant})` : ''}`.slice(0, 300),
  }
}

/**
 * GET {api}/v1/tools/lookup_device?k_number=K… with the demo key in the key header. Without an API address or a key, or on any
 * failure, the K-number is stored as "not checked yet". Only the K-number is sent; never the company name or the device list.
 */
export async function lookupKNumber(
  k: string,
  apiBase: string | null,
  key: { header: string; value: string } | null,
  fetcher: Fetcher = (u, i) => fetch(u, i),
): Promise<KLookup> {
  if (!apiBase || !key || !isKNumber(k)) return NOT_CHECKED_RESULT
  const ctl = new AbortController()
  const timer = setTimeout(() => ctl.abort(), 12_000)
  try {
    const res = await fetcher(`${apiBase}${LOOKUP_PATH}?k_number=${encodeURIComponent(k)}`, {
      method: 'GET',
      headers: { [key.header]: key.value },
      credentials: 'omit',
      signal: ctl.signal,
    })
    if (!res.ok) return NOT_CHECKED_RESULT
    return parseLookup(await res.json(), k) ?? { ...NOT_CHECKED_RESULT, checked: true, text: `checked: no 510(k) record found for ${k}` }
  } catch {
    return NOT_CHECKED_RESULT
  } finally {
    clearTimeout(timer)
  }
}

// ── The company the Our devices views show ───────────────────────────────

const toHistory = (h: MineHistory): CompanyHistoryEntry => ({
  seq: h.seq,
  date: h.date,
  ts: `${h.date}T00:00:00+00:00`,
  actor: ACTOR,
  action: h.from === null ? 'register' : 'change',
  from_status: h.from,
  to_status: h.to,
  details: {},
  note: '',
  entry_hash: '',
})

const NO_EVIDENCE = {
  origin: 'missing' as const,
  available: false,
  note: 'evidence not fetched yet',
  report_count: null,
  window: null,
  queries: [],
  recalls: null,
}

/**
 * Turns the person's devices into the same Company shape the simulated company uses, so the table, chips, device pages and
 * alert counts are the same views. Real FDA evidence is attached only where it is stored for the device's product code
 * (taken from the simulated company's stored evidence for that code); otherwise the device page says it is not fetched yet.
 */
export function buildMyCompany(mine: MineCompany, demo: Company, sweep: Sweep | null | undefined, generated: string = demo.generated_utc): Company {
  const byCode = new Map<string, CompanyDevice>()
  for (const d of demo.devices) if (d.evidence.available && !byCode.has(d.product_code)) byCode.set(d.product_code, d)
  const devices: CompanyDevice[] = mine.devices.map((m) => {
    const src = m.product_code ? byCode.get(m.product_code) : undefined
    const row = m.product_code ? sweep?.rows.find((r) => r.product_code === m.product_code) : undefined
    return {
      id: m.id,
      name: m.name,
      model: m.k_number ?? 'no K-number given',
      product_code: m.product_code ?? '—',
      owner: 'you',
      device_type: src?.device_type ?? { name: null, source: null, query_url: null },
      sweep: row
        ? {
            classification: row.classification,
            as_of: sweep?.meta.as_of ?? '',
            current_count: row.current_count,
            query_url: row.queries?.[0]?.[1] ?? '',
          }
        : null,
      status: { label: m.status, set_by: ACTOR, date: m.history[m.history.length - 1]?.date ?? m.added, detail: '', details: {} },
      history: m.history.map(toHistory),
      evidence: src
        ? src.evidence
        : { ...NO_EVIDENCE, note: m.product_code ? 'evidence not fetched yet' : 'no product code given, so no FDA evidence can be looked up' },
      patterns: src?.patterns ?? [],
      mine: { k_number: m.k_number, k_check: m.k_check, note: m.note, source: m.source },
    }
  })
  return {
    schema_version: demo.schema_version,
    generated_utc: generated,
    banner: MINE_BANNER,
    company: mine.company || null,
    statuses: demo.statuses,
    devices,
    audit: { file: '', chain_ok: null, first_bad_seq: null, entries: [] },
    notes: ['Your company: names, statuses and dates are what you typed. Problem evidence is real FDA data, shown only where it is stored for the product code.'],
    mine: true,
  }
}

/** Product codes the AI device sweep flags as risky (a new kind of problem or more serious than usual). */
export function flaggedCodes(sweep: Sweep | null | undefined): Set<string> {
  return new Set((sweep?.rows ?? []).filter((r) => r.classification === 'new_signal' || r.classification === 'severity_escalation').map((r) => r.product_code))
}
