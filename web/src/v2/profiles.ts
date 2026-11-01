// Simulated device lifecycle profiles (web/public/data/company_profiles.json, built by
// scripts/build_company_profiles.py). Everything here is SIMULATED sample data except the product code, its FDA
// device name, class and regulation number, which the script reads from stored FDA data in the repo.
import { useEffect, useState } from 'react'
import type { Company } from '../types'
import { appRoot, withLayout } from './router'

export interface Dated {
  date: string
  /** True when the date is after the file's as-of date (a plan, not a fact). */
  planned: boolean
}

export type Pathway = '510(k)' | 'De Novo' | 'PMA'
export type Stage = 'development' | 'under_review' | 'decided' | 'on_market' | 'post_market'

export interface Milestone extends Dated {
  key: string
  label: string
}

export interface Attendee {
  name: string
  role: string
}

export interface Protocol extends Dated {
  id: string
  title: string
  standard: string | null
  result: 'pass' | 'fail' | 'planned'
  report: string
}

export interface Problem extends Dated {
  id: string
  found_in: string
  description: string
  change: string
  retest_id: string
  retest_date: string
  retest_result: 'pass' | 'fail'
}

export interface Study extends Dated {
  label: string
  test_set: string
  positives: number
  negatives: number
  true_positives: number
  true_negatives: number
  sensitivity: number
  specificity: number
  reference: string
}

export interface Capa {
  id: string
  title: string
  owner: string
  opened: string
  closed: string | null
  state: 'open' | 'closed'
}

export interface ClauseTag {
  tag: string
  why: string
}

export interface RiskCell {
  severity: number
  severity_label: string
  probability: number
  probability_label: string
  score: number
  zone: 'acceptable' | 'reduce as far as possible' | 'not acceptable'
}

export interface Assessment {
  result: string
  rationale: string
}

export interface MdrAssessment extends Assessment {
  receipt_date?: string
  due_date?: string
  submitted_date?: string
  day_of_30?: number
  clock_note?: string
}

export type DecisionOutcome =
  | (Dated & { kind: 'ntf'; rationale: string; signed_by: string; signed_role: string; tags: ClauseTag[] })
  | (Dated & { kind: 'capa'; capa_id: string; owner: string; due: string; due_planned: boolean; status: string; tags: ClauseTag[] })
  | (Dated & {
      kind: 'escalation'
      assessed_by: string
      follow_up_capa: { capa_id: string; owner: string; due: string; due_planned: boolean; status: string } | null
      mdr: MdrAssessment
      correction_removal: Assessment
      recall: Assessment
      signed_by: string
      signed_role: string
      tags: ClauseTag[]
    })

export interface DecisionPath {
  id: string
  signal: { kind: 'pattern' | 'sweep'; pattern_id: string | null }
  state: 'open' | 'decided'
  pre_market: boolean
  triage: Dated & { owner: string; role: string; note: string; tags: ClauseTag[] }
  board: Dated & { held: boolean; attendees: Attendee[]; summary: string; decision: string | null; tags: ClauseTag[] }
  outcome: DecisionOutcome | null
  risk: {
    hhe_summary: string
    before: RiskCell
    after: RiskCell
    after_is_expected: boolean
    risk_file: Dated & { ref: string; change: string }
    tags: ClauseTag[]
  } | null
}

export interface DeviceDecision {
  none_reason: string | null
  paths: DecisionPath[]
}

export interface ActivityEntry {
  date: string
  person: string
  role: string
  action: string
}

export interface DeviceProfile {
  id: string
  name: string
  model: string
  product_code: string
  owner: string
  simulated: true
  overview: {
    fda_device_name: string | null
    fda_name_source: string
    device_class: string | null
    regulation_number: string | null
    classification_source: string
    classification_fetched: string | null
    pathway: Pathway
    intended_use: string
    stage: Stage
    status_label: string
    software: boolean
    ai: boolean
  }
  milestones: Milestone[]
  design: {
    inputs: { id: string; text: string }[]
    outputs: { id: string; text: string }[]
    hazards: { id: string; hazard: string; harm: string; severity: string; control: string; residual: string }[]
    software: { iec62304_class: string; documentation_level: string } | null
    reviews: (Dated & { id: string; name: string; attendees: Attendee[]; outcome: string })[]
  }
  vv: { protocols: Protocol[]; problems: Problem[]; study: Study | null }
  regulatory: {
    pathway: Pathway
    decision_verb: 'cleared' | 'granted' | 'approved'
    presub: Dated & { number: string; feedback: string[] }
    submission: Dated & { number: string }
    ai_request: (Dated & { summary: string }) | null
    ai_response: (Dated & { summary: string }) | null
    decision: (Dated & { outcome: string }) | null
    predicate: string | null
    fda_days: number | null
    hold_days: number | null
  }
  market: {
    launch: Dated | null
    regions: string[]
    sites: number | null
    units_shipped: number | null
    udi_di: string
  }
  postmarket: {
    complaints_by_month: { month: string; count: number }[]
    categories: { name: string; count: number }[]
    capas: Capa[]
  }
  decision: DeviceDecision
  activity: ActivityEntry[]
}

export interface ProfilesFile {
  schema_version: string
  simulated: true
  banner: string
  company: string | null
  as_of: string
  seed: number
  generated_by: string
  real_fields: string[]
  profiles: Record<string, DeviceProfile>
}

export const SIM_LABEL = 'SIMULATED — sample data'
/** The repeated tag inside a card that mixes real and simulated data (sentence case; the banner uses SIM_LABEL). */
export const SIM_TAG = 'Simulated — sample data'

/** The word FDA uses for a decision on each pathway. "approved" is for PMA only. */
export const DECISION_VERB: Record<Pathway, 'cleared' | 'granted' | 'approved'> = {
  '510(k)': 'cleared',
  'De Novo': 'granted',
  PMA: 'approved',
}

export type StageGroup = 'development' | 'review' | 'decided' | 'market'
export const STAGE_GROUP: Record<Stage, StageGroup> = {
  development: 'development',
  under_review: 'review',
  decided: 'decided',
  on_market: 'market',
  post_market: 'market',
}

const asProfiles = (raw: unknown): ProfilesFile | null =>
  typeof raw === 'object' && raw !== null && typeof (raw as ProfilesFile).profiles === 'object' && (raw as ProfilesFile).simulated === true
    ? (raw as ProfilesFile)
    : null

let cache: Promise<ProfilesFile | null> | null = null

/** Loads company_profiles.json once (null when it is missing). Only the v2 layout asks for it. */
export function loadProfiles(): Promise<ProfilesFile | null> {
  if (!cache)
    cache = fetch(`${import.meta.env.BASE_URL}data/company_profiles.json`)
      .then((r) => (r.ok ? r.json() : null))
      .then(asProfiles)
      .catch(() => null)
  return cache
}

/** The profiles file: undefined while loading, null when missing. */
export function useProfiles(): ProfilesFile | null | undefined {
  const [file, setFile] = useState<ProfilesFile | null | undefined>(undefined)
  useEffect(() => {
    let live = true
    void loadProfiles().then((f) => {
      if (live) setFile(f)
    })
    return () => {
      live = false
    }
  }, [])
  return file
}

export interface DeviceSummary {
  development: number
  review: number
  decided: number
  market: number
  openCapas: number
  /** Decision paths still open (no outcome yet). */
  needDecision: number
  /** Devices with at least one open decision path. */
  needDecisionDevices: number
}

/** The tiles above Our devices, counted from the data (decisions due = decision paths with no outcome yet). */
export function summarize(file: ProfilesFile, company: Company): DeviceSummary {
  const out: DeviceSummary = { development: 0, review: 0, decided: 0, market: 0, openCapas: 0, needDecision: 0, needDecisionDevices: 0 }
  for (const d of company.devices) {
    const p = file.profiles[d.id]
    if (!p) continue
    const open = p.decision.paths.filter((x) => x.state === 'open').length
    out.needDecision += open
    if (open > 0) out.needDecisionDevices += 1
    out[STAGE_GROUP[p.overview.stage]] += 1
    out.openCapas += p.postmarket.capas.filter((c) => c.state === 'open').length
  }
  return out
}

/** "2026-07-20" as "20 Jul 2026" (UTC, no time zone shift). */
export function niceDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!m) return iso
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  return `${Number(m[3])} ${months[Number(m[2]) - 1]} ${m[1]}`
}

/** "2026-07" as "Jul 2026". */
export function niceMonth(ym: string): string {
  return niceDate(`${ym}-01`).replace(/^1 /, '')
}

/** Days from a to b (ISO dates). */
export const daysBetween = (a: string, b: string): number => Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86_400_000)

/**
 * The address of the investigation page (built on another branch) for a complaint on this device:
 * /investigate?code=<PRODUCT_CODE>&device=<device id>. Other query parameters (?r=, ?layout) are kept.
 */
export function investigateHref(
  code: string,
  device: string,
  loc: { pathname: string; search: string } = window.location,
  flag: string | undefined = import.meta.env.VITE_LAYOUT_DEFAULT as string | undefined,
): string {
  const q = new URLSearchParams()
  q.set('code', code)
  q.set('device', device)
  new URLSearchParams(withLayout(loc.search, flag)).forEach((v, k) => {
    if (k !== 'code' && k !== 'device') q.append(k, v)
  })
  return `${appRoot(loc.pathname)}investigate?${q.toString()}`
}
