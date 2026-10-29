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

export type InvestigationKind = 'weekly-investigator' | 'recall-sweep'

export interface InvestigationGroup {
  label: string
  report_ids: string[]
  count: number
}

/** One recorded agentic run (investigations.json; written by Track A's recorder, never by the exporter). */
export interface InvestigationRun {
  id: string
  kind: InvestigationKind
  product_code: string
  trigger: string | Record<string, unknown> | null
  recorded_at_utc: string
  model: string
  tool_steps: ToolStep[]
  sentences: Sentence[]
  groups: InvestigationGroup[]
  protocol?: unknown
}

export interface Investigations {
  investigations: InvestigationRun[]
  notes: string[]
}

export interface AuditEntry {
  seq: number
  ts: string
  actor: string
  action: string
  entity_id: string
  payload: Record<string, unknown>
  prev_hash: string
  entry_hash: string
}

export interface AuditRun {
  run_label: string
  chain_ok: boolean
  first_bad_seq: number | null
  entries: AuditEntry[]
}

export interface Audit {
  runs: AuditRun[]
  notes: string[]
}

export interface Dossier {
  doc_id: string
  pdf: { draft: string; approved: string }
  narrative: { model: string; skill_version: string; created_at: string } | null
  review: { model: string; findings: unknown[]; parse_error: string } | null
  notes: string[]
}

export interface SamBox {
  x1: number
  y1: number
  x2: number
  y2: number
  w: number
  h: number
  c: number
}

export interface LabelField {
  value: string
  legibility: string
}

export interface LabelCheck {
  source: string
  outcome: string
  detail: string
}

export interface LabelReading {
  image: string
  image_size: [number, number]
  sam: { prompt_used: string | null; boxes: SamBox[]; chosen_box: SamBox | null; note: string }
  fields: Record<string, LabelField>
  checks: LabelCheck[]
  k_number: string | null
  k_status: string
  gtin: string | null
  gtin_valid?: boolean | null
  overall_legibility: string
  match_basis: string
  model: string
}

export type ReadStatus = 'VERIFIED' | 'CONFLICT' | 'UNVERIFIABLE'

export interface K510Field {
  name: string
  status: ReadStatus
  value: string | string[] | null
  read_a: { value: string | string[] | null; page: number | null; legibility: string } | null
  read_b: { value: string | string[] | null; page: number | null; legibility: string } | null
  reads_agree: boolean
  similarity: number | null
  checks: LabelCheck[]
  note: string
}

export interface K510Reading {
  k_number: string
  pdf_url: string
  page_count: number
  pages_read: number
  has_text_layer: boolean
  agreement_pct: number
  counts: Record<ReadStatus, number>
  fields: K510Field[]
}

export interface Vision {
  k510: K510Reading[]
  labels: LabelReading[]
  notes: string[]
}

export interface SweepRow {
  product_code: string
  classification: string
  current_count: number
  baseline_count: number
  baseline_weekly_mean: number
  spike_ratio: number | null
  current_severe_count: number
  queries?: [string, string][]
}

export interface Sweep {
  meta: {
    generated_utc: string
    devices_on_list: number
    codes_on_list: number
    codes_checked: number
    errors: number
    as_of: string
    source: string
    window: { current_start: string; current_end: string; baseline_start: string; baseline_end: string }
  }
  rows: SweepRow[]
}

export interface ProtocolStep {
  tool: string
  dataset: string
  filters: Record<string, unknown>
  date_from: string | null
  date_to: string | null
  count: number | null
  run_at: string | null
}

export interface Protocol {
  protocols: Record<string, ProtocolStep[]>
  notes?: string[]
}

export interface WorkspaceData {
  manifest: Manifest
  threads: Threads
  briefs: Brief[]
  sources: Source[]
  schedules: Schedule[]
  investigations: Investigations
  evidence: Evidence
  audit: Audit
  dossier: Dossier
  vision: Vision
  sweep: Sweep
  protocol: Protocol
}

export type WorkflowId =
  | 'ai-sweep'
  | 'check-device'
  | 'weekly-signals'
  | 'ask-copilot'
  | 'capa-need-evidence'
  | 'weekly-investigator'
  | 'recall-sweep'
  | 'vision'

export interface WorkflowDef {
  id: WorkflowId
  title: string
  blurb: string
}
