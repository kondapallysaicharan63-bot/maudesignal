// Builds the step timeline shown under every answer. Pure: it reads only what a recording stored.
// A time, token count or cost appears on a step only if the recording stored it for that step; the
// recordings store tokens and cost for the whole run (never per step) and no duration at all, so the
// per-step values read "not recorded" and the run-level values are shown on the run line.
import type { LabelReading, Sentence, Thread } from './types'

export const NOT_RECORDED = 'not recorded'

export type StepKind = 'heard' | 'plan' | 'tool' | 'gate' | 'done' | 'sam' | 'read' | 'check' | 'review'

export interface Metric {
  /** Text shown for the value. Equals NOT_RECORDED when the recording did not store it. */
  text: string
  recorded: boolean
}

export interface TraceStep {
  id: string
  kind: StepKind
  title: string
  detail: string
  /** Tool calls only: the arguments as short "key: value" text, and the stored result summary. */
  args: string | null
  result: string | null
  /** Extra lines, e.g. each withheld reason. */
  lines: string[]
  /** Model badge, or null for a step done by plain code. */
  model: string | null
  time: Metric
  tokens: Metric
  cost: Metric
  /** True for a display step that folds several searches into one (their own counts and times are in `lines`). */
  grouped?: boolean
}

export interface RunUsage {
  tokens: Metric
  cost: Metric
  time: Metric
}

export interface Trace {
  steps: TraceStep[]
  /** Number of steps before the gate check / checks (the ones replayed before the sentences). */
  beforeGate: number
  usage: RunUsage
}

const none: Metric = { text: NOT_RECORDED, recorded: false }

const usd = (n: number): string => `$${n.toFixed(n < 0.1 ? 4 : 2)}`
const int = (n: number): string => n.toLocaleString('en-US')

/** "muse-spark-1.3" -> "Muse Spark". Other names are shown as stored. */
export function modelBadge(model: string | null | undefined): string {
  if (!model) return ''
  const m = model.toLowerCase()
  if (m.startsWith('muse-spark')) return 'Muse Spark'
  if (m.startsWith('muse-wonder')) return 'Muse Wonder'
  if (m.startsWith('muse-image')) return 'Muse Image'
  if (m.startsWith('sam')) return 'SAM 3.1'
  return model
}

/** "weekly_signals" -> "Weekly signals". */
export function toolDisplayName(name: string): string {
  const s = name.replace(/_/g, ' ').trim()
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : name
}

/** The arguments as short "key: value" text; "no arguments" when there are none. Values are cut at 60 characters. */
export function argsSummary(args: Record<string, unknown> | null | undefined): string {
  const entries = Object.entries(args ?? {})
  if (entries.length === 0) return 'no arguments'
  return entries
    .map(([k, v]) => {
      const raw = typeof v === 'string' ? v : JSON.stringify(v)
      const s = raw.length > 60 ? `${raw.slice(0, 57)}...` : raw
      return `${k}: ${s}`
    })
    .join(', ')
}

function runUsage(u: Thread['usage']): RunUsage {
  if (!u) return { tokens: none, cost: none, time: none }
  const hasTokens = Number.isFinite(u.input_tokens) && Number.isFinite(u.output_tokens)
  return {
    tokens: hasTokens ? { text: `${int(u.input_tokens)} in · ${int(u.output_tokens)} out`, recorded: true } : none,
    cost: Number.isFinite(u.cost_usd) ? { text: usd(u.cost_usd), recorded: true } : none,
    time:
      typeof u.duration_s === 'number' && Number.isFinite(u.duration_s)
        ? { text: `${u.duration_s.toFixed(1)} s`, recorded: true }
        : none,
  }
}

const count = (n: number, one: string, many = `${one}s`): string => `${n} ${n === 1 ? one : many}`

type StepInit = Pick<TraceStep, 'id' | 'kind' | 'title' | 'detail'> &
  Partial<Pick<TraceStep, 'lines' | 'model' | 'time' | 'tokens' | 'cost' | 'args' | 'result'>>

const step = (p: StepInit): TraceStep => ({ lines: [], args: null, result: null, model: null, time: none, tokens: none, cost: none, ...p })

/** The gate's reason for every withheld sentence. */
function withheldLines(sentences: Sentence[]): string[] {
  return sentences.filter((s) => s.status !== 'pass').flatMap((s) => (s.reasons.length ? s.reasons : ['no reason stored']))
}

/** The timeline for one recorded copilot answer: (heard) -> planning -> each tool call -> gate check -> done. */
export function buildThreadTrace(t: Thread): Trace {
  const steps: TraceStep[] = []
  if (t.voice) {
    steps.push(
      step({
        id: 'heard',
        kind: 'heard',
        title: 'Heard',
        detail: `Transcribed the recorded voice question (${t.voice.audio_seconds.toFixed(1)} s, ${t.voice.language}).`,
        model: 'Voice Transcribe',
      }),
    )
  }
  steps.push(
    step({
      id: 'plan',
      kind: 'plan',
      title: 'Planning',
      detail:
        t.tool_steps.length === 0
          ? 'The model answered without calling a tool.'
          : `The model chose ${count(t.tool_steps.length, 'tool call')} to read the stored records.`,
      model: modelBadge(t.model),
    }),
  )
  t.tool_steps.forEach((s, i) =>
    steps.push(
      step({
        id: `tool-${i}`,
        kind: 'tool',
        title: toolDisplayName(s.name),
        detail: `Arguments: ${argsSummary(s.arguments)}. Result: ${s.summary || 'no summary stored'}.`,
        args: argsSummary(s.arguments),
        result: s.summary || 'no summary stored',
        model: modelBadge(t.model),
      }),
    ),
  )
  const beforeGate = steps.length
  const shown = t.sentences.filter((s) => s.status === 'pass').length
  const withheld = t.sentences.length - shown
  const finalLine = `Final: ${count(shown, 'sentence')} passed, ${withheld} withheld.`
  const first = t.first_pass
    ? `First pass: ${t.first_pass.passed} passed, ${t.first_pass.blocked} blocked.${
        t.repaired ? ' The model repaired the draft and the gate checked it again.' : ''
      }`
    : 'First pass: not recorded.'
  steps.push(
    step({
      id: 'gate',
      kind: 'gate',
      title: 'Gate check',
      detail: `${first} ${finalLine}`,
      lines: withheldLines(t.sentences),
    }),
    step({
      id: 'done',
      kind: 'done',
      title: 'Done',
      detail: `Answer shown: ${count(shown, 'sentence')}${withheld ? `, ${withheld} withheld` : ''}.`,
    }),
  )
  return { steps, beforeGate, usage: runUsage(t.usage) }
}

/** The timeline for one stored device-label reading: SAM 3.1 finds the label, Muse Spark reads it, then the checks. */
export function buildLabelTrace(l: LabelReading): Trace {
  const costs = l.cost_usd && typeof l.cost_usd === 'object' ? l.cost_usd : null
  const cost = (n: number | undefined): Metric => (typeof n === 'number' ? { text: usd(n), recorded: true } : none)
  const fields = Object.values(l.fields).filter((f) => f.value).length
  const steps: TraceStep[] = [
    step({
      id: 'sam',
      kind: 'sam',
      title: 'Find the label',
      detail: `SAM 3.1 found ${count(l.sam.boxes.length, 'label box', 'label boxes')}${l.sam.prompt_used ? ` for the prompt "${l.sam.prompt_used}"` : ''}.`,
      model: 'SAM 3.1',
      cost: cost(costs?.sam),
    }),
    step({
      id: 'read',
      kind: 'read',
      title: 'Read the label',
      detail: `Read ${count(fields, 'field')} with text from the cropped label.`,
      model: modelBadge(l.model),
      cost: cost(costs?.spark),
    }),
  ]
  const beforeGate = steps.length
  steps.push(
    step({
      id: 'check',
      kind: 'check',
      title: 'Checks',
      detail: `${count(l.checks.length, 'check')} against openFDA and the printed digits.`,
      lines: l.checks.map((c) => `${c.source.replace(/_/g, ' ')}: ${c.outcome}`),
    }),
    step({ id: 'done', kind: 'done', title: 'Done', detail: 'Reading complete. Lot and serial numbers are never stored.' }),
  )
  const tokens: Metric =
    typeof l.input_tokens === 'number' && typeof l.output_tokens === 'number'
      ? { text: `${int(l.input_tokens)} in · ${int(l.output_tokens)} out`, recorded: true }
      : none
  return {
    steps,
    beforeGate,
    usage: { tokens, cost: typeof costs?.total === 'number' ? cost(costs.total) : none, time: none },
  }
}

/** The one stored step of the dossier review: Muse Wonder reads the PDF and returns findings only. */
export function buildReviewTrace(review: { model: string; findings: unknown[]; parse_error: string }): Trace {
  const steps = [
    step({
      id: 'review',
      kind: 'review',
      title: 'Independent review of the PDF',
      detail: review.parse_error
        ? `The review could not be read (${review.parse_error}).`
        : `${count(review.findings.length, 'finding')} returned. Findings only; nothing is changed by the review.`,
      model: modelBadge(review.model),
    }),
    step({ id: 'done', kind: 'done', title: 'Done', detail: 'Advisory only. A named person reviews and decides.' }),
  ]
  return { steps, beforeGate: 1, usage: { tokens: none, cost: none, time: none } }
}

/** True when this step stored at least one of time, tokens or cost. */
export const stepHasMetrics = (s: TraceStep): boolean => s.time.recorded || s.tokens.recorded || s.cost.recorded

/** The recorded values of one step as short text parts, e.g. ["4.2 s", "1,203 in · 88 out"]. Empty when none was stored. */
export function stepMetricParts(s: TraceStep): string[] {
  return [s.time, s.tokens, s.cost].filter((m) => m.recorded).map((m) => m.text)
}

/**
 * One line for the collapsed trace, e.g. "7 steps · Muse Spark · 4 tools · $0.0470". Only what was stored:
 * the cost is left out when the run did not record one, and tools are left out when no tool was called.
 */
export function traceSummary(trace: Trace): string {
  const models = [...new Set(trace.steps.map((s) => s.model).filter((m): m is string => !!m))]
  const tools = trace.steps.filter((s) => s.kind === 'tool').length
  const parts = [count(trace.steps.length, 'step')]
  if (models.length) parts.push(models.join(' + '))
  if (tools) parts.push(count(tools, 'tool'))
  if (trace.usage.cost.recorded) parts.push(trace.usage.cost.text)
  return parts.join(' · ')
}
