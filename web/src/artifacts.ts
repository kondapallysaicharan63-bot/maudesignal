// Pure helpers for the artifacts pane. Everything here reads stored exports only.
import type { Audit, AuditRun, Protocol, ProtocolStep, Sweep, SweepRow, Thread } from './types'

export type TabId = 'brief' | 'digest' | 'dossier' | 'vision' | 'audit' | 'capa' | 'protocol'

export const TABS: { id: TabId; label: string }[] = [
  { id: 'brief', label: 'Daily brief' },
  { id: 'digest', label: 'Signal digest' },
  { id: 'dossier', label: 'Dossier' },
  { id: 'vision', label: 'Vision' },
  { id: 'audit', label: 'Audit trail' },
  { id: 'capa', label: 'CAPA draft' },
  { id: 'protocol', label: 'Protocol' },
]

/** Which artifact tabs a stored thread produced, most specific first (the first one opens). */
export function producedTabs(thread: Thread | null): TabId[] {
  if (!thread) return []
  const names = new Set(thread.tool_steps.map((s) => s.name))
  const out: TabId[] = []
  if (names.has('draft_capa')) out.push('capa', 'dossier')
  if (names.has('weekly_signals')) out.push('brief', 'digest')
  if (names.has('device_510k')) out.push('vision')
  if (thread.tool_steps.length > 0) out.push('protocol')
  out.push('audit')
  return out
}

export const CLASS_LABEL: Record<string, string> = {
  new_signal: 'New kind of problem',
  severity_escalation: 'More serious than usual',
  spike: 'Reports suddenly increased',
  stable: 'No change',
}

/** Sweep rows that are not "stable", most reports this week first. */
export function flaggedRows(sweep: Sweep): SweepRow[] {
  return sweep.rows
    .filter((r) => r.classification !== 'stable')
    .sort((a, b) => b.current_count - a.current_count || a.product_code.localeCompare(b.product_code))
}

/** The audit run a thread was recorded in: voice questions have their own run, typed ones share "typed". */
export function auditRunFor(audit: Audit, thread: Thread | null): AuditRun | null {
  if (!thread) return null
  return audit.runs.find((r) => r.run_label === thread.id) ?? audit.runs.find((r) => r.run_label === 'typed') ?? null
}

export interface CapaDraft {
  id: string
  title: string
  problem: string
  productCode: string
  reportIds: string[]
  ts: string
  actor: string
}

const str = (v: unknown): string => (typeof v === 'string' ? v : '')

/** Every `capa.draft` audit entry, in recorded order. */
export function capaDrafts(audit: Audit): CapaDraft[] {
  const out: CapaDraft[] = []
  for (const run of audit.runs)
    for (const e of run.entries) {
      if (e.action !== 'capa.draft') continue
      const ids = Array.isArray(e.payload.report_ids) ? e.payload.report_ids.map(String) : []
      out.push({
        id: e.entity_id,
        title: str(e.payload.title),
        problem: str(e.payload.problem_statement),
        productCode: str(e.payload.product_code),
        reportIds: ids,
        ts: e.ts,
        actor: e.actor,
      })
    }
  return out
}

export function shortHash(h: string): string {
  return h.length > 14 ? `${h.slice(0, 8)}…${h.slice(-4)}` : h
}

/** Search-protocol steps recorded for one thread (empty when none were stored). */
export function protocolFor(protocol: Protocol, threadId: string | null): ProtocolStep[] {
  return threadId ? (protocol.protocols[threadId] ?? []) : []
}

/** Local-only approval state of a CAPA draft: never saved anywhere. */
export type CapaLocalState = { status: 'draft' } | { status: 'approved'; by: string }

export function approveLocally(name: string): CapaLocalState | null {
  const n = name.trim()
  return n ? { status: 'approved', by: n } : null
}
