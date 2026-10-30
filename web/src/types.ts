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
  /** Tokens and cost of the recorded run; `duration_s` only if the recording stored one (none do today). */
  usage?: { input_tokens: number; output_tokens: number; cost_usd: number; duration_s?: number } | null
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
  signals: { product_code: string; classification: string; label: string; current_count: number; baseline_count: number }[]
  footer: string | null
  /** Product code to device name, as stored in the digest. */
  device_types?: Record<string, string>
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

/** One possible match, as stored. Nothing here is a confirmation: a person confirms in the app. */
export interface LabelMatch {
  source: string
  record_id: string
  owner: string
  device_name: string
  product_code: string
  device_type_name: string
  decision_date?: string | null
  query_url: string
  score: number
  why_matched: string[]
  why_not_matched: string[]
  k_number?: string | null
}

export interface MatchFact {
  id: string
  topic: string
  status: string
  text: string
  query_url: string
  /** The stored numbers behind the sentence. */
  data?: Record<string, unknown>
}

export interface DeviceTypeView {
  product_code: string
  device_type_name: string
  facts: MatchFact[]
  summary: { this_week_change?: { change?: string; as_of?: string | null; rules?: string[] } | null } & Record<string, unknown>
}

export interface MatchTraceStep {
  step: string
  model: string
  elapsed_ms?: number | null
  timing?: string
  note?: string
  cost_usd?: number | null
  input_tokens?: number | null
  output_tokens?: number | null
  count?: number | null
  url?: string | null
  urls?: string[]
  /** Steps that ran several openFDA queries keep one entry per query; count is null where only a sum of groups was stored. */
  queries?: { query: string; url?: string | null; count?: number | null; groups_sum?: number | null }[]
}

/** The stored label -> possible matches record (``demo/vision/label-match-*.json``). */
export interface LabelMatchRecord {
  generated_utc?: string
  label: { fields: Record<string, LabelField>; overall_legibility: string }
  status: string
  note: string
  matches: LabelMatch[]
  device_type_views: Record<string, DeviceTypeView>
  trace: MatchTraceStep[]
  scoring_rules?: string[]
  reading?: { model?: string; input_tokens?: number | null; output_tokens?: number | null; cost_usd?: { total?: number | null } }
  disclaimer?: string
  confirmed: null
}

export interface LabelReading {
  image: string
  /** The stored possible matches; null when no matching run was recorded for this photo. */
  matches?: LabelMatchRecord | null
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
  /** Run-level usage as stored with the reading (the live API answer may omit it). */
  input_tokens?: number
  output_tokens?: number
  cost_usd?: { spark?: number; sam?: number; total?: number }
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
  company: Company
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
  | 'our-devices'

export interface WorkflowDef {
  id: WorkflowId
  title: string
  blurb: string
}

// ── company.json: a simulated company, real FDA evidence (DATA_CONTRACT.md) ──
export interface CompanyHistoryEntry {
  seq: number
  date: string
  ts: string
  actor: string
  action: 'register' | 'change'
  from_status: string | null
  to_status: string
  details: Record<string, string>
  note: string
  entry_hash: string
}

export interface CompanyQuote {
  report_id: string
  text: string
  url: string
}

export interface CompanyPattern {
  id: string
  label: string
  kind: 'investigator' | 'keyword'
  display_label: string
  basis: string
  count: number
  report_ids: string[]
  first_received: string | null
  last_received: string | null
  quotes: CompanyQuote[]
  links: { label: string; url: string }[]
  gate: { count: string; reason: string; quotes_passed: number; quotes_withheld: number }
}

export interface CompanyRecall {
  recall_number: string
  recalling_firm: string | null
  status: string | null
  date_initiated: string | null
  excerpt: string | null
  /** True when the excerpt is only the start of a longer sentence (shown with an ellipsis). */
  excerpt_truncated?: boolean
  url: string | null
}

export interface CompanyEvidence {
  origin: 'demo_db' | 'fetched' | 'missing'
  available: boolean
  note: string | null
  fetched_utc?: string | null
  report_count: { value: number; gate: string; reason: string } | null
  window: { date_from: string | null; date_to: string | null } | null
  queries: { label: string; url: string }[]
  recalls: {
    stored: number
    matched_total: number | null
    gate: string
    reason: string
    latest: CompanyRecall[]
  } | null
  gate_totals?: { pass: number; block: number }
  /** Group counts recomputed from the listed report ids (not claim-gate verdicts). */
  recomputed?: { pass: number; block: number }
}

export interface CompanyDevice {
  id: string
  name: string
  model: string
  product_code: string
  owner: string
  device_type: { name: string | null; source: string | null; query_url: string | null }
  sweep: { classification: string; as_of: string; current_count: number; query_url: string } | null
  status: { label: string; set_by: string; date: string; detail: string; details: Record<string, string> } | null
  history: CompanyHistoryEntry[]
  evidence: CompanyEvidence
  patterns: CompanyPattern[]
}

export interface Company {
  schema_version: string
  generated_utc: string
  banner: string
  company: string | null
  statuses: { label: string; rank: number }[]
  devices: CompanyDevice[]
  audit: { file: string; chain_ok: boolean | null; first_bad_seq: number | null; entries: unknown[] }
  notes: string[]
}
