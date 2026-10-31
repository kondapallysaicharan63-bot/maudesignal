// Pure helpers for the label "possible matches" screen. They read only what a recording stored: a time, token
// count or cost appears only if the record has it for that step, and nothing is ever chosen on the person's behalf.
import { NOT_RECORDED, modelBadge, type Metric, type Trace, type TraceStep } from './trace'
import type { DeviceTypeView, LabelMatch, LabelMatchRecord, LabelReading, MatchFact, MatchTraceStep } from './types'

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
  // A time carried over from an earlier run keeps its stored label ("832 ms, recorded 2026-10-30").
  const carried = s.timing && s.timing !== 'measured' ? `, ${s.timing}` : ''
  return { text: `${fmtMs(s.elapsed_ms)}${carried}`, recorded: true }
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

/** One query of a multi-query step: its stored count, or its sum of groups (labelled), or "count not recorded". */
function queryLine(q: NonNullable<MatchTraceStep['queries']>[number]): string {
  if (typeof q.count === 'number') return `${q.query}: ${int(q.count)} ${q.count === 1 ? 'record' : 'records'}`
  if (typeof q.groups_sum === 'number') return `${q.query}: ${int(q.groups_sum)} (sum of the groups returned)`
  return `${q.query}: count not recorded`
}

/** The stored steps: SAM 3.1 -> Muse Spark read -> each openFDA search -> gate -> done, with stored timings and costs only. */
export function buildMatchTrace(rec: LabelMatchRecord): Trace {
  const steps: TraceStep[] = rec.trace.map((s, i) => {
    const isDone = s.step === 'Done'
    const kind: TraceStep['kind'] =
      s.model === 'SAM 3.1' ? 'sam' : s.model === 'Muse Spark' ? 'read' : s.model === 'openFDA' ? 'tool' : isDone ? 'done' : 'gate'
    const count = typeof s.count === 'number' ? s.count : null
    const qs = s.queries ?? []
    // A step that ran several queries has no single count; each query is listed with its own stored count.
    const multi = qs.length > 1
    const result = multi
      ? `${plural(qs.length, 'query', 'queries')}, each with its own count below`
      : count === null
        ? 'count not recorded'
        : `${int(count)} ${count === 1 ? 'record' : 'records'}`
    return {
      id: `m${i}`,
      kind,
      title: s.step.replace(/^openFDA search: /, 'openFDA: '),
      detail: s.note ?? stepDetail(kind, result, s),
      args: null,
      result,
      lines: multi ? qs.map(queryLine) : [],
      lineUrls: multi ? qs.map((q) => q.url ?? null) : undefined,
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
  if (!asOf) return 'The date of this weekly check was not recorded.'
  const from = weekFrom(view)
  return from ? `Week of ${from} to ${asOf}.` : `Week ending ${asOf}.`
}

/** The stored start date of the report window ("2026-09-24"), or null when none was stored. */
export function weekFrom(view: DeviceTypeView): string | null {
  const f = view.facts.find((x) => x.status === 'pass' && x.topic === 'reports_window')?.data?.from
  return typeof f === 'string' ? f : null
}

/** The stored rules behind the weekly change line, so "no change" can be read next to the counts. */
export const weekChangeRules = (view: DeviceTypeView): string[] => view.summary.this_week_change?.rules ?? []

/** One line for the label list: how many possible matches wait for a person. */
export function matchSummary(l: LabelReading): string {
  const rec = l.matches
  if (!rec) return 'no matching run recorded'
  const n = rec.matches.length
  return n === 0 ? 'no match found' : `${plural(n, 'possible match', 'possible matches')} to confirm`
}

/** Up to three possible matches, highest score first (ties keep the stored order). Ordering only; nothing is chosen. */
export function rankMatches(matches: LabelMatch[]): LabelMatch[] {
  return matches
    .slice(0, 3)
    .map((m, i) => ({ m, i }))
    .sort((a, b) => b.m.score - a.m.score || a.i - b.i)
    .map((x) => x.m)
}

/** True when the first card has a strictly higher score than the next (so "Highest score" is never a tie). */
export const hasClearLeader = (ranked: LabelMatch[]): boolean =>
  ranked.length > 0 && (ranked.length === 1 || ranked[0].score > ranked[1].score)

/** "1 of 3 · score 65 of 100". */
export const rankLine = (rank: number, total: number, score: number): string => `${rank} of ${total} · score ${score} of 100`

/** Thousands separators on bare numbers of five digits or more in stored text (ids such as K260687 and dates are left alone). */
export const fmtNumbers = (text: string): string =>
  text.replace(/(?<![\w.-])\d{5,}(?![\w-])/g, (n) => Number(n).toLocaleString('en-US'))

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2026-10-30T01:34:26Z" -> "Oct 30, 2026, 01:34 UTC"; text that is not an ISO time comes back unchanged. */
export function fmtUtc(iso: string | undefined | null): string | null {
  if (!iso) return null
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso)
  if (!m) return iso
  return `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}, ${m[1]}, ${m[4]}:${m[5]} UTC`
}

export interface KeyStat {
  label: string
  value: string
  note?: string
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const f2 = (n: number): string => n.toLocaleString('en-US', { maximumFractionDigits: 2 })

/** The two or three figures that matter, read from the data stored with the passed facts (never from a withheld fact). */
export function keyStats(view: DeviceTypeView): KeyStat[] {
  const passed = view.facts.filter((f) => f.status === 'pass')
  const data = (topic: string): Record<string, unknown> | null => passed.find((x) => x.topic === topic)?.data ?? null
  const out: KeyStat[] = []
  const total = num(data('reports_total')?.total)
  if (total !== null) out.push({ label: 'Reports', value: f2(total), note: 'all time' })
  const win = data('reports_window')
  const week = num(win?.count)
  const base = num(win?.baseline_weekly_mean)
  if (week !== null) {
    const from = typeof win?.from === 'string' ? win.from : null
    const to = typeof win?.to === 'string' ? win.to : null
    const dates = from && to ? `7 days, ${from} to ${to}` : to ? `7 days ending ${to}` : 'dates not recorded'
    out.push({
      label: 'This week',
      value: f2(week),
      note: `${dates}; ${base !== null ? `vs ${f2(base)} weekly average` : 'weekly average not recorded'}`,
    })
  }
  const recalls = num(data('recalls_total')?.total)
  if (recalls !== null) out.push({ label: 'Recalls', value: f2(recalls), note: 'all time' })
  return out
}

/**
 * The same steps with the consecutive openFDA searches folded into one ("8 searches, 0 to 8 records each"). Each search
 * stays listed as a line with only its stored count and time. Display only; the summary line and run line come from the
 * full trace.
 */
export function groupSearches(trace: Trace): Trace {
  const steps: TraceStep[] = []
  let run: TraceStep[] = []
  const flush = () => {
    if (run.length === 0) return
    if (run.length === 1) steps.push(run[0])
    else {
      const singles = run.filter((s) => s.lines.length === 0)
      const multis = run.length - singles.length
      const sc = singles.map((s) => {
        const m = /^([\d,]+) record/.exec(s.result ?? '')
        return m ? Number(m[1].replace(/,/g, '')) : null
      })
      const known = sc.filter((c): c is number => c !== null)
      let range = 'counts not recorded'
      if (singles.length > 0 && known.length === singles.length) {
        const lo = Math.min(...known)
        const hi = Math.max(...known)
        range = lo === hi ? `${int(lo)} ${lo === 1 ? 'record' : 'records'} each` : `${int(lo)} to ${int(hi)} records each`
      } else if (singles.length === 0) range = 'counts listed per query'
      if (multis > 0 && singles.length > 0 && known.length === singles.length) range += `; ${plural(multis, 'search')} with several queries listed per query`
      steps.push({
        id: `g${steps.length}`,
        kind: 'tool',
        title: `openFDA: ${plural(run.length, 'search', 'searches')}`,
        detail: '',
        args: null,
        result: range,
        lines: run.flatMap((s) => {
          const t = s.title.replace(/^openFDA: /, '')
          const time = s.time.recorded ? ` (${s.time.text})` : ''
          return s.lines.length === 0 ? [`${t}: ${s.result}${time}`] : [`${t}${time}:`, ...s.lines.map((l) => `  ${l}`)]
        }),
        lineUrls: run.flatMap((s) => (s.lines.length === 0 ? [null] : [null, ...s.lines.map((_, i) => s.lineUrls?.[i] ?? null)])),
        model: null,
        time: none,
        tokens: none,
        cost: none,
        grouped: true,
      })
    }
    run = []
  }
  for (const s of trace.steps) {
    if (s.kind === 'tool') run.push(s)
    else {
      flush()
      steps.push(s)
    }
  }
  flush()
  return { ...trace, steps }
}
