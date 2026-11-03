// The browser's own hash-chained audit trail (board status changes, evidence-pack accept/reject, note-to-file
// exports, live-model failures and fallback choices). Kept in this browser only (no login, no server): it is the
// record of what a named person did on this device, and it says so on every screen that shows it.
//
// Same hash as the Python trail (storage/database.py Database._audit_hash): entry_hash = sha256(prev_hash + body),
// body = json.dumps({"action","actor","entity_id","payload","ts"}, sort_keys=True) with payload =
// json.dumps(payload, sort_keys=True). So an exported browser trail re-verifies with Database.audit_entry_hash.

export interface AuditEntry {
  seq: number
  /** Naive UTC ISO time with microseconds, as Python's datetime.isoformat() writes it. */
  ts: string
  actor: string
  action: string
  entity_id: string
  payload_json: string
  prev_hash: string
  entry_hash: string
}

export const AUDIT_KEY = 'ms-pms-audit-v1'
export const GENESIS = 'GENESIS'
export const LOCAL_NOTE = 'Kept in this browser only: no login, no electronic signature. Export it to your QMS.'

/** Python json.dumps(x, sort_keys=True) with its default separators and ensure_ascii. */
export function pyJson(v: unknown): string {
  if (v === null || v === undefined) return 'null'
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  if (typeof v === 'number') {
    // Payloads carry integers only (Python writes 1.0 where JavaScript writes 1).
    return Number.isFinite(v) ? String(v) : 'NaN'
  }
  if (typeof v === 'string') return pyStr(v)
  if (Array.isArray(v)) return `[${v.map(pyJson).join(', ')}]`
  const o = v as Record<string, unknown>
  const keys = Object.keys(o)
    .filter((k) => o[k] !== undefined)
    .sort()
  return `{${keys.map((k) => `${pyStr(k)}: ${pyJson(o[k])}`).join(', ')}}`
}

function pyStr(s: string): string {
  let out = '"'
  for (const ch of s) {
    const c = ch.codePointAt(0) as number
    if (ch === '"') out += '\\"'
    else if (ch === '\\') out += '\\\\'
    else if (ch === '\n') out += '\\n'
    else if (ch === '\r') out += '\\r'
    else if (ch === '\t') out += '\\t'
    else if (ch === '\b') out += '\\b'
    else if (ch === '\f') out += '\\f'
    else if (c < 0x20 || c > 0x7e) {
      if (c > 0xffff) {
        const v = c - 0x10000
        out += `\\u${(0xd800 + (v >> 10)).toString(16).padStart(4, '0')}\\u${(0xdc00 + (v & 0x3ff)).toString(16).padStart(4, '0')}`
      } else out += `\\u${c.toString(16).padStart(4, '0')}`
    } else out += ch
  }
  return out + '"'
}

async function sha256Hex(text: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))
  return Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, '0')).join('')
}

export async function entryHash(prev: string, ts: string, actor: string, action: string, entityId: string, payloadJson: string): Promise<string> {
  return sha256Hex(prev + pyJson({ ts, actor, action, entity_id: entityId, payload: payloadJson }))
}

/** "2026-11-03T09:12:03.123000" (UTC, naive, microseconds) like Python's datetime.isoformat(). */
export function pyTs(d: Date = new Date()): string {
  // Python omits the fraction when it is zero.
  return d.toISOString().replace('Z', '').replace(/\.000$/, '').replace(/\.(\d{3})$/, '.$1000')
}

export interface AuditStore {
  read: () => string | null
  write: (s: string) => void
}

export function browserStore(): AuditStore {
  return {
    read: () => {
      try {
        return window.localStorage.getItem(AUDIT_KEY)
      } catch {
        return null
      }
    },
    write: (s) => {
      try {
        window.localStorage.setItem(AUDIT_KEY, s)
      } catch {
        // storage blocked (private window): the entry still lives in memory for this page
      }
    },
  }
}

let memory: AuditEntry[] | null = null

export function loadAudit(store: AuditStore = browserStore()): AuditEntry[] {
  const raw = store.read()
  if (raw) {
    try {
      const v = JSON.parse(raw) as unknown
      if (Array.isArray(v)) return v as AuditEntry[]
    } catch {
      // unreadable: shown as a broken chain by verify, never silently replaced
      return [{ seq: 0, ts: '', actor: '', action: 'unreadable', entity_id: '', payload_json: raw.slice(0, 200), prev_hash: '', entry_hash: '' }]
    }
  }
  return memory ?? []
}

/** Append one entry (audit-first: callers change their own state only after this resolves). */
export async function appendAudit(
  e: { actor: string; action: string; entity_id: string; payload: Record<string, unknown> },
  store: AuditStore = browserStore(),
  now: Date = new Date(),
): Promise<AuditEntry> {
  const all = loadAudit(store)
  const last = all[all.length - 1]
  const prev = last ? last.entry_hash : GENESIS
  const ts = pyTs(now)
  const payload_json = pyJson(e.payload)
  const row: AuditEntry = {
    seq: (last?.seq ?? 0) + 1,
    ts,
    actor: e.actor,
    action: e.action,
    entity_id: e.entity_id,
    payload_json,
    prev_hash: prev,
    entry_hash: await entryHash(prev, ts, e.actor, e.action, e.entity_id, payload_json),
  }
  const next = [...all, row]
  memory = next
  store.write(JSON.stringify(next))
  window.dispatchEvent(new CustomEvent('ms-audit'))
  return row
}

/** Recompute every hash: ok, or the first entry that does not match. */
export async function verifyAudit(entries: AuditEntry[]): Promise<{ ok: boolean; firstBad: number | null }> {
  let prev = GENESIS
  for (const r of entries) {
    const h = await entryHash(prev, r.ts, r.actor, r.action, r.entity_id, r.payload_json)
    if (r.prev_hash !== prev || r.entry_hash !== h) return { ok: false, firstBad: r.seq }
    prev = r.entry_hash
  }
  return { ok: true, firstBad: null }
}

/** Testing hook: forget the in-memory copy. */
export function resetAuditMemory(): void {
  memory = null
}

/** A typed person's name: a letter first, 2–80 letters, spaces, dots, apostrophes or hyphens (pms/board.py). */
export const validName = (s: string): boolean => /^[A-Za-z][A-Za-z .'-]{1,79}$/.test(s.trim())
