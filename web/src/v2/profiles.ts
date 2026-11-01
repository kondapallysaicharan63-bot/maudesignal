// Simulated device lifecycle profiles (web/public/data/company_profiles.json, built by
// scripts/build_company_profiles.py). Everything here is SIMULATED sample data except the product code, its FDA
// device name, class and regulation number, which the script reads from stored FDA data in the repo.
import { useEffect, useState } from 'react'
import type { Company } from '../types'

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
  needDecision: number
}

/** The tiles above Our devices, counted from the data (needs-decision from company.json statuses). */
export function summarize(file: ProfilesFile, company: Company): DeviceSummary {
  const out: DeviceSummary = { development: 0, review: 0, decided: 0, market: 0, openCapas: 0, needDecision: 0 }
  for (const d of company.devices) {
    const p = file.profiles[d.id]
    if (d.status?.label === 'Needs review') out.needDecision += 1
    if (!p) continue
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
