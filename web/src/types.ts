// Shapes of web/public/data/*.json (see web/DATA_CONTRACT.md). Only what the UI reads.

export interface Manifest {
  schema_version: string
  generated_utc: string
  source_commit: string | null
  files: string[]
  header: {
    claims_verified: number
    sentences_verified: number
    sentences_withheld: number
    answers: number
    audit_chain_ok: boolean
  }
  notes: string[]
}

export interface Claim {
  kind: string
  status: 'pass' | 'block'
  reason: string
  evidence_ids: string[]
}

export interface Sentence {
  text: string
  status: 'pass' | 'block'
  reasons: string[]
  claims: Claim[]
}

export interface ToolStep {
  name: string
  arguments: Record<string, unknown>
  summary: string
}

export interface Thread {
  id: string
  workflow: string
  question: string
  voice: { transcript_text: string; language: string; audio_seconds: number } | null
  recorded_at_utc: string
  model: string
  tool_steps: ToolStep[]
  sentences: Sentence[]
  first_pass: { passed: number; blocked: number; sentences: Sentence[] } | null
  repaired: boolean
}

export interface EvidenceReport {
  product_code: string
  date_received: string
  event_type: string
  report_source: string
  brand: string
  excerpt: string
  maude_url: string
}

export interface EvidenceOther {
  kind: string
  label: string
  url: string
}

export interface Evidence {
  reports: Record<string, EvidenceReport>
  other: Record<string, EvidenceOther>
}

export interface WorkflowGroup {
  id: string
  title: string
  thread_ids: string[]
}

export interface Threads {
  workflows: WorkflowGroup[]
  threads: Thread[]
}

export interface Brief {
  date: string
  headline: string
  counts: { new: number; more_serious_than_usual: number; reports_suddenly_increased: number; stable: number }
  window: { current_start: string; current_end: string; baseline_start: string; baseline_end: string }
  signals: { product_code: string; label: string; current_count: number; baseline_count: number }[]
  footer: string | null
}

export interface Source {
  id: string
  label: string
  records: number
  last_refresh: string | null
}

export interface Schedule {
  id: string
  label: string
  cron: string | null
  last_result: { date: string; headline?: string; flagged?: number; checked?: number } | null
}

export interface Investigations {
  investigations: unknown[]
  notes: string[]
}

export interface WorkspaceData {
  manifest: Manifest
  threads: Threads
  briefs: Brief[]
  sources: Source[]
  schedules: Schedule[]
  investigations: Investigations
  evidence: Evidence
}

export type WorkflowId =
  | 'weekly-signals'
  | 'ask-copilot'
  | 'capa-need-evidence'
  | 'weekly-investigator'
  | 'recall-sweep'
  | 'vision'
  | 'intake'

export interface WorkflowDef {
  id: WorkflowId
  title: string
  blurb: string
  /** Not implemented yet: shown as "coming soon", never faked. */
  comingSoon?: boolean
}
