// Time and cost (F27). A time or cost figure exists only when a person typed the inputs (their assumptions) or when
// a recorded measurement carries who, when and how. This file holds the parsing of measurements.json and the one
// calculation; it never contains a number of its own except the limits on what counts as a timing.
import { readStore, writeStore } from '../storage'

export const TASKS = [
  { id: 'similar-events', label: "Complaint: find problems reported on other makers' devices of the same type in the last 12 months" },
  { id: 'weekly-trend', label: 'Weekly trend for code X vs prior 4 weeks' },
  { id: 'evidence-section', label: 'Assemble the evidence section for a PMS board / CAPA-need form' },
] as const
export type TaskId = (typeof TASKS)[number]['id']

export interface Measurement {
  id: string
  task: string
  who: string
  when: string
  how: string
  manual_minutes: number
  maudesignal_minutes: number
  notes: string
}

const str = (v: unknown): string => (typeof v === 'string' ? v.trim() : '')
/** Measured minutes: more than 0 and at most 10000 (about a week). Anything else is not a timing. */
const mins = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) && v > 0 && v <= 10000 ? v : null)

/** The entries of measurements.json that can be shown. An entry without who, when and how is dropped, not shown. */
export function parseMeasurements(raw: unknown): Measurement[] {
  if (!raw || typeof raw !== 'object') return []
  const list = (raw as { measurements?: unknown }).measurements
  if (!Array.isArray(list)) return []
  const out: Measurement[] = []
  for (const e of list) {
    if (!e || typeof e !== 'object') continue
    const o = e as Record<string, unknown>
    const manual = mins(o.manual_minutes)
    const tool = mins(o.maudesignal_minutes)
    const m = { id: str(o.id), task: str(o.task), who: str(o.who), when: str(o.when), how: str(o.how), notes: str(o.notes) }
    if (!m.id || !m.task || !m.who || !m.when || !m.how || manual === null || tool === null) continue
    out.push({ ...m, manual_minutes: manual, maudesignal_minutes: tool })
  }
  return out
}

/** The entries for one task (the entry's task is the task id or the task's full label). */
export function forTask(list: Measurement[], id: TaskId): Measurement[] {
  const label = TASKS.find((t) => t.id === id)?.label.toLowerCase()
  return list.filter((m) => m.task === id || m.task.toLowerCase() === label)
}

/** True when MaudeSignal took longer than the manual way in this recording. */
export const slower = (m: Measurement): boolean => m.maudesignal_minutes > m.manual_minutes

/** The calculator's two jobs, each with its own monthly count and minutes. Only these tasks can feed it. */
export const JOBS = [
  { task: 'similar-events' as TaskId, count: 'complaints', manual: 'complaintManual', tool: 'complaintTool' },
  { task: 'weekly-trend' as TaskId, count: 'trends', manual: 'trendManual', tool: 'trendTool' },
] as const

export interface Assumptions {
  complaints: string
  complaintManual: string
  complaintTool: string
  trends: string
  trendManual: string
  trendTool: string
  hourly: string
}
export const EMPTY: Assumptions = {
  complaints: '',
  complaintManual: '',
  complaintTool: '',
  trends: '',
  trendManual: '',
  trendTool: '',
  hourly: '',
}
export type Source = 'assumptions' | 'recorded'

/** A typed value as a non-negative number: digits with an optional decimal part only. Else null. */
export function num(v: string): number | null {
  const s = v.trim()
  if (!/^\d+(\.\d+)?$/.test(s)) return null
  const n = Number(s)
  return Number.isFinite(n) ? n : null
}

export interface Result {
  hoursManual: number
  hoursTool: number
  /** Manual minus MaudeSignal, in hours per month (negative when MaudeSignal was slower). */
  hoursDiff: number
  cost: number | null
}

/** Results from the person's own inputs; null until at least one job has its count and both minutes typed. */
export function compute(a: Assumptions): Result | null {
  let manual = 0
  let tool = 0
  let any = false
  for (const j of JOBS) {
    const c = num(a[j.count])
    const m = num(a[j.manual])
    const t = num(a[j.tool])
    if (c === null || m === null || t === null) continue
    any = true
    manual += c * m
    tool += c * t
  }
  if (!any) return null
  const hoursManual = manual / 60
  const hoursTool = tool / 60
  const hoursDiff = hoursManual - hoursTool
  const rate = num(a.hourly)
  const cost = rate === null ? null : hoursDiff * rate
  if (![hoursManual, hoursTool, hoursDiff].every(Number.isFinite) || (cost !== null && !Number.isFinite(cost))) return null
  return { hoursManual, hoursTool, hoursDiff, cost }
}

export type Means = Partial<Record<TaskId, { manual: number; tool: number; n: number }>>

/** The mean recorded minutes per job, from entries of that job's task only. Null when no entry matches either job. */
export function recordedMeans(list: Measurement[]): Means | null {
  const out: Means = {}
  for (const j of JOBS) {
    const rows = forTask(list, j.task)
    if (rows.length === 0) continue
    const sum = rows.reduce((s, m) => ({ a: s.a + m.manual_minutes, b: s.b + m.maudesignal_minutes }), { a: 0, b: 0 })
    out[j.task] = { manual: sum.a / rows.length, tool: sum.b / rows.length, n: rows.length }
  }
  return Object.keys(out).length === 0 ? null : out
}

const KEY = 'ms-roi-assumptions'

/** What this browser kept from last time (localStorage only; never sent anywhere). */
export function loadAssumptions(): { a: Assumptions; source: Source } {
  try {
    const raw = readStore(KEY)
    if (!raw) return { a: EMPTY, source: 'assumptions' }
    const o = JSON.parse(raw) as Record<string, unknown>
    const a = { ...EMPTY }
    for (const k of Object.keys(EMPTY) as (keyof Assumptions)[]) {
      const v = o[k]
      a[k] = typeof v === 'string' && /^[\d.]{0,12}$/.test(v) ? v : ''
    }
    return { a, source: o.source === 'recorded' ? 'recorded' : 'assumptions' }
  } catch {
    return { a: EMPTY, source: 'assumptions' }
  }
}

export function saveAssumptions(a: Assumptions, source: Source): void {
  try {
    writeStore(KEY, JSON.stringify({ ...a, source }))
  } catch {
    // nothing is kept; the page still works
  }
}

/** A number for display: at most one decimal, no trailing zero. */
export const fmt = (n: number): string => String(Math.round(n * 10) / 10)
