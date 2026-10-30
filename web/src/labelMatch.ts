// Pure helpers for the label "possible matches" screen. They read only what a recording stored: a time, token
// count or cost appears only if the record has it for that step, and nothing is ever chosen on the person's behalf.
import { NOT_RECORDED, modelBadge, type Metric, type Trace, type TraceStep } from './trace'
import type { DeviceTypeView, LabelMatchRecord, LabelReading, MatchFact, MatchTraceStep } from './types'

const none: Metric = { text: NOT_RECORDED, recorded: false }

export const FIELD_LABEL: Record<string, string> = {
  device_name: 'Device name',
  manufacturer: 'Manufacturer',
  model_number: 'Model number',
  k_number: 'K-number',
  udi: 'UDI',
  gtin: 'GTIN',
}

/** The note above the fields when the overall reading is not clear; null when it is clear (or not stored). */
export function legibilityBanner(overall: string | null | undefined): string | null {
  if (overall === 'illegible')
    return 'This label could not be read. Field values are hidden because they cannot be relied on. Take a clearer photo to search.'
  if (overall && overall !== 'clear')
    return 'This label was only partly legible. Compare each value with the photo before you confirm anything.'
  return null
}

export interface FieldRow {
  key: string
  label: string
  /** The value to show; null when there is none or when it is hidden. */
  value: string | null
  legibility: string
  hidden: boolean
}

/**
 * The fields to show. They come from the matching run when one was recorded (that is what the matches were searched
 * with), otherwise from the stored reading. When the overall reading is illegible every value is hidden; a single
 * illegible field is hidden too.
 */
export function fieldRows(l: LabelReading): { rows: FieldRow[]; overall: string; fromMatchRun: boolean } {
  const rec = l.matches ?? null
  const src = rec?.label ?? { fields: l.fields, overall_legibility: l.overall_legibility }
  const overall = src.overall_legibility
  const rows = Object.entries(src.fields).map(([key, f]) => {
    const hidden = overall === 'illegible' || f.legibility === 'illegible'
    return {
      key,
      label: FIELD_LABEL[key] ?? key,
      value: hidden || !f.value ? null : f.value,
      legibility: f.legibility,
      hidden,
    }
  })
  return { rows, overall, fromMatchRun: rec !== null }
}

/** "1.3 s" or "404 ms". */
export function fmtMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`
}

const usd = (n: number): string => `$${n.toFixed(n < 0.1 ? 4 : 2)}`
const int = (n: number): string => n.toLocaleString('en-US')

function timeOf(s: MatchTraceStep): Metric {
  if (typeof s.elapsed_ms !== 'number' || !Number.isFinite(s.elapsed_ms)) return none
  if (s.timing && /not recorded/i.test(s.timing)) return none
  return { text: fmtMs(s.elapsed_ms), recorded: true }
}

const costOf = (s: MatchTraceStep): Metric =>
  typeof s.cost_usd === 'number' && Number.isFinite(s.cost_usd) ? { text: usd(s.cost_usd), recorded: true } : none

const tokensOf = (s: MatchTraceStep): Metric =>
  typeof s.input_tokens === 'number' && typeof s.output_tokens === 'number'
    ? { text: `${int(s.input_tokens)} in · ${int(s.output_tokens)} out`, recorded: true }
    : none

const plural = (n: number, one: string, many = `${one}s`): string => `${n} ${n === 1 ? one : many}`

function stepDetail(kind: TraceStep['kind'], result: string, s: MatchTraceStep): string {
  if (kind === 'tool') return `Result: ${result}.`
  if (kind === 'sam') return 'SAM 3.1 finds the label in the photo.'
  if (kind === 'read') return 'Muse Spark reads the cropped label.'
  if (kind === 'done') return s.timing && s.timing !== 'measured' ? `Run time: ${s.timing}.` : 'Finished.'
  return 'Checked against the stored openFDA records.'
}

/** The stored steps: SAM 3.1 -> Muse Spark read -> each openFDA search -> gate -> done, with stored timings and costs only. */
export function buildMatchTrace(rec: LabelMatchRecord): Trace {
  const steps: TraceStep[] = rec.trace.map((s, i) => {
    const isDone = s.step === 'Done'
    const kind: TraceStep['kind'] =
      s.model === 'SAM 3.1' ? 'sam' : s.model === 'Muse Spark' ? 'read' : s.model === 'openFDA' ? 'tool' : isDone ? 'done' : 'gate'
    const count = typeof s.count === 'number' ? s.count : null
    const result = count === null ? 'count not recorded' : plural(count, 'record')
    return {
      id: `m${i}`,
      kind,
      title: s.step.replace(/^openFDA search: /, 'openFDA: '),
      detail: s.note ?? stepDetail(kind, result, s),
      args: null,
      result,
      lines: [],
      model: s.model === 'openFDA' || s.model === 'gate' ? null : modelBadge(s.model),
      time: timeOf(s),
      tokens: tokensOf(s),
      cost: costOf(s),
    }
  })
  const done = rec.trace.find((s) => s.step === 'Done')
  const total = rec.reading?.cost_usd?.total
  const inTok = rec.reading?.input_tokens
  const outTok = rec.reading?.output_tokens
  return {
    steps,
    beforeGate: steps.filter((s) => s.kind !== 'gate' && s.kind !== 'done').length,
    usage: {
      time: done ? timeOf(done) : none,
      tokens:
        typeof inTok === 'number' && typeof outTok === 'number'
          ? { text: `${int(inTok)} in · ${int(outTok)} out`, recorded: true }
          : none,
      cost: typeof total === 'number' ? { text: usd(total), recorded: true } : none,
    },
  }
}

const SECTIONS: { title: string; topics: string[] }[] = [
  { title: 'Reports', topics: ['reports_total', 'reports_window'] },
  { title: 'Recalls', topics: ['recalls_total', 'recalls_latest'] },
  { title: '510(k) clearances', topics: ['clearances_total', 'clearances_latest'] },
  { title: "This week's change", topics: ['this_week_change'] },
]

export interface FactSection {
  title: string
  facts: MatchFact[]
}

/** The device type's passed facts grouped as reports, recalls, 510(k) and this week's change. Withheld facts are counted, never shown. */
export function factSections(view: DeviceTypeView): { sections: FactSection[]; withheld: number; typeFact: MatchFact | null } {
  const passed = view.facts.filter((f) => f.status === 'pass')
  const sections = SECTIONS.map((s) => ({
    title: s.title,
    facts: s.topics.flatMap((t) => passed.filter((f) => f.topic === t)),
  })).filter((s) => s.facts.length > 0)
  return {
    sections,
    withheld: view.facts.length - passed.length,
    typeFact: passed.find((f) => f.topic === 'device_type') ?? null,
  }
}

/** The dates the stored weekly change was made for: "week ending 2026-09-30", or a plain statement that none was stored. */
export function weekChangeDates(view: DeviceTypeView): string {
  const asOf = view.summary.this_week_change?.as_of
  return asOf ? `Week ending ${asOf}.` : 'The date of this weekly check was not recorded.'
}

/** One line for the label list: how many possible matches wait for a person. */
export function matchSummary(l: LabelReading): string {
  const rec = l.matches
  if (!rec) return 'no matching run recorded'
  const n = rec.matches.length
  return n === 0 ? 'no match found' : `${plural(n, 'possible match', 'possible matches')} to confirm`
}
