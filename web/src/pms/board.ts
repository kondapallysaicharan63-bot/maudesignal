// PMS board state (PRD-19), replayed from the browser's hash-chained audit trail only (src/maudesignal/pms/board.py).
// A row's status changes only when a named person asks; the audit entry is written first.
import { appendAudit, type AuditEntry, type AuditStore, validName } from './audit'

export const STATUSES = ['new', 'under_review', 'note_to_file', 'escalated', 'closed'] as const
export type Status = (typeof STATUSES)[number]
export const STATUS_LABELS: Record<Status, string> = {
  new: 'New',
  under_review: 'Under review',
  note_to_file: 'Note to file',
  escalated: 'Escalated',
  closed: 'Closed',
}
export const TRANSITIONS: Record<Status, Status[]> = {
  new: ['under_review'],
  under_review: ['note_to_file', 'escalated', 'closed'],
  note_to_file: ['under_review', 'closed'],
  escalated: ['under_review', 'closed'],
  closed: ['under_review'],
}
export const BOARD_ACTION = 'board_status'
export const NOT_A_QMS = 'This is not a QMS. Status, owner and due date are typed by a named person and kept in this browser.'

export interface BoardRow {
  code: string
  why: string
  status: Status
  owner: string | null
  due: string | null
  due_basis: string | null
  /** Last audit entry about this code (status change, pack decision or note to file). */
  audit_seq: number | null
  decision: string | null
}

const isStatus = (s: unknown): s is Status => typeof s === 'string' && (STATUSES as readonly string[]).includes(s)

export function boardRows(flagged: { code: string; why: string }[], audit: AuditEntry[]): BoardRow[] {
  const rows = new Map<string, BoardRow>()
  for (const f of flagged)
    if (!rows.has(f.code)) rows.set(f.code, { code: f.code, why: f.why, status: 'new', owner: null, due: null, due_basis: null, audit_seq: null, decision: null })
  for (const e of audit) {
    if (!e.entity_id.startsWith('board:')) continue
    const code = e.entity_id.slice(6)
    let p: Record<string, unknown> = {}
    try {
      p = JSON.parse(e.payload_json) as Record<string, unknown>
    } catch {
      continue
    }
    const r = rows.get(code) ?? { code, why: String(p.why ?? ''), status: 'new' as Status, owner: null, due: null, due_basis: null, audit_seq: null, decision: null }
    if (e.action === BOARD_ACTION && isStatus(p.to)) {
      r.status = p.to
      if (typeof p.owner === 'string' && p.owner) r.owner = p.owner
      if (typeof p.due === 'string') r.due = p.due
      if (typeof p.due_basis === 'string') r.due_basis = p.due_basis
    }
    if (e.action === 'note_to_file' && typeof p.decision === 'string') r.decision = p.decision
    r.audit_seq = e.seq
    rows.set(code, r)
  }
  return [...rows.values()]
}

/** Advisory MDR clock (21 CFR 803.50 / 803.53) from an awareness date the person types. Null for a bad date. */
export function mdrDue(awareness: string, fiveDay = false): { due: string; basis: string } | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(awareness.trim())
  if (!m) return null
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])))
  if (d.getUTCMonth() !== Number(m[2]) - 1) return null
  if (fiveDay) {
    let added = 0
    while (added < 5) {
      d.setUTCDate(d.getUTCDate() + 1)
      if (d.getUTCDay() !== 0 && d.getUTCDay() !== 6) added += 1
    }
    return { due: d.toISOString().slice(0, 10), basis: '5 work days, 21 CFR 803.53 (advisory; a person decides)' }
  }
  d.setUTCDate(d.getUTCDate() + 30)
  return { due: d.toISOString().slice(0, 10), basis: '30 calendar days, 21 CFR 803.50 (advisory; a person decides)' }
}

export class BoardError extends Error {}

export async function changeStatus(
  a: { code: string; why: string; current: Status; to: Status; actor: string; owner?: string; awareness?: string; fiveDay?: boolean },
  store?: AuditStore,
): Promise<AuditEntry> {
  if (!validName(a.actor)) throw new BoardError('A status changes only by a named person. Type your name.')
  if (a.owner && !validName(a.owner)) throw new BoardError('Owner must be a typed name.')
  if (!TRANSITIONS[a.current].includes(a.to))
    throw new BoardError(`${STATUS_LABELS[a.current]} cannot move to ${STATUS_LABELS[a.to]}. Allowed: ${TRANSITIONS[a.current].map((t) => STATUS_LABELS[t]).join(', ')}.`)
  const payload: Record<string, unknown> = { from: a.current, to: a.to, why: a.why }
  if (a.owner) payload.owner = a.owner.trim()
  if (a.awareness) {
    const d = mdrDue(a.awareness, a.fiveDay)
    if (!d) throw new BoardError('Awareness date must be a real day, YYYY-MM-DD.')
    Object.assign(payload, { awareness: a.awareness, due: d.due, due_basis: d.basis })
  }
  return appendAudit({ actor: a.actor.trim(), action: BOARD_ACTION, entity_id: `board:${a.code}`, payload }, store)
}
