// Pure helpers for claim chips. A chip is only "verified" when the gate passed the claim AND
// every evidence id it lists resolves to a stored row in evidence.json.
import type { Claim, Evidence, EvidenceOther, EvidenceReport, Sentence } from './types'

export type ChipState = 'verified' | 'withheld' | 'no-claim'

export interface ResolvedClaim {
  claim: Claim
  reports: { id: string; row: EvidenceReport }[]
  others: { id: string; row: EvidenceOther }[]
  missing: string[]
}

/** Lower rank = more serious. Unknown event types sort last. */
const SEVERITY = ['Death', 'Injury', 'Malfunction']

export function severityRank(eventType: string): number {
  const i = SEVERITY.indexOf(eventType)
  return i === -1 ? SEVERITY.length : i
}

/** Severity first, then newest date_received first, then id for a stable order. */
export function sortReports(rows: { id: string; row: EvidenceReport }[]): { id: string; row: EvidenceReport }[] {
  return [...rows].sort(
    (a, b) =>
      severityRank(a.row.event_type) - severityRank(b.row.event_type) ||
      b.row.date_received.localeCompare(a.row.date_received) ||
      a.id.localeCompare(b.id),
  )
}

export function resolveClaim(claim: Claim, ev: Evidence): ResolvedClaim {
  const reports: ResolvedClaim['reports'] = []
  const others: ResolvedClaim['others'] = []
  const missing: string[] = []
  for (const id of claim.evidence_ids) {
    const r = ev.reports[id]
    const o = ev.other[id]
    if (r) reports.push({ id, row: r })
    else if (o) others.push({ id, row: o })
    else missing.push(id)
  }
  return { claim, reports: sortReports(reports), others, missing }
}

export function chipState(s: Sentence): ChipState {
  if (s.status !== 'pass') return 'withheld'
  return s.claims.length === 0 ? 'no-claim' : 'verified'
}

/** A sentence resolves when it is withheld with a reason, has no claim, or all its claims resolve. */
export function sentenceResolves(s: Sentence, ev: Evidence): boolean {
  if (s.status !== 'pass') return s.reasons.length > 0
  return s.claims.every((c) => c.status === 'pass' && resolveClaim(c, ev).missing.length === 0)
}

export interface WithheldRef {
  threadId: string
  /** Index into the thread's final `sentences`. */
  index: number
}

/** Every withheld sentence of the final answers, in stored order (the same set manifest.json counts). */
export function withheldSentences(threads: { id: string; sentences: Sentence[] }[]): WithheldRef[] {
  const out: WithheldRef[] = []
  for (const t of threads)
    t.sentences.forEach((s, index) => {
      if (s.status === 'block') out.push({ threadId: t.id, index })
    })
  return out
}

/** 20260825 -> 2026-08-25 */
export function fmtDate(d: string): string {
  return /^\d{8}$/.test(d) ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)}` : d
}
