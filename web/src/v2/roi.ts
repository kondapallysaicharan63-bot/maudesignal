// Time and cost (F27). A time or cost figure exists only when a person typed the inputs (their assumptions) or when
// a recorded measurement carries who, when and how. This file holds the parsing of measurements.json and the one
// calculation; it never contains a number of its own.
import { readStore, writeStore } from '../storage'

export const TASKS = [
  { id: 'similar-events', label: 'Complaint: find similar events at other makers in the last 12 months' },
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
const mins = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : null)

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

export interface Assumptions {
  complaints: string
  trends: string
  hourly: string
  manual: string
  tool: string
}
export const EMPTY: Assumptions = { complaints: '', trends: '', hourly: '', manual: '', tool: '' }

/** A typed value as a non-negative number, or null when empty or not a number. */
export function num(v: string): number | null {
  const s = v.trim()
  if (s === '') return null
  const n = Number(s)
  return Number.isFinite(n) && n >= 0 ? n : null
}

export interface Result {
  hoursManual: number
  hoursTool: number
  hoursDiff: number
  cost: number | null
}

/** Results from the person's own inputs; null until the needed values are typed (minutes for both and at least one count). */
export function compute(a: Assumptions): Result | null {
  const manual = num(a.manual)
  const tool = num(a.tool)
  const c = num(a.complaints)
  const t = num(a.trends)
  if (manual === null || tool === null || (c === null && t === null)) return null
  const jobs = (c ?? 0) + (t ?? 0)
  const hoursManual = (jobs * manual) / 60
  const hoursTool = (jobs * tool) / 60
  const hoursDiff = hoursManual - hoursTool
  const rate = num(a.hourly)
  return { hoursManual, hoursTool, hoursDiff, cost: rate === null ? null : hoursDiff * rate }
}

/** The mean of the recorded minutes, or null when nothing is recorded. */
export function recordedMeans(list: Measurement[]): { manual: number; tool: number; n: number } | null {
  if (list.length === 0) return null
  const sum = list.reduce((s, m) => ({ a: s.a + m.manual_minutes, b: s.b + m.maudesignal_minutes }), { a: 0, b: 0 })
  return { manual: sum.a / list.length, tool: sum.b / list.length, n: list.length }
}

const KEY = 'ms-roi-assumptions'

/** What this browser kept from last time (localStorage only; never sent anywhere). */
export function loadAssumptions(): Assumptions {
  try {
    const raw = readStore(KEY)
    if (!raw) return EMPTY
    const o = JSON.parse(raw) as Record<string, unknown>
    const pick = (k: keyof Assumptions): string => (typeof o[k] === 'string' ? (o[k] as string).slice(0, 12) : '')
    return { complaints: pick('complaints'), trends: pick('trends'), hourly: pick('hourly'), manual: pick('manual'), tool: pick('tool') }
  } catch {
    return EMPTY
  }
}

export function saveAssumptions(a: Assumptions): void {
  try {
    writeStore(KEY, JSON.stringify(a))
  } catch {
    // nothing is kept; the page still works
  }
}

/** A number for display: at most one decimal, no trailing zero. */
export const fmt = (n: number): string => String(Math.round(n * 10) / 10)
