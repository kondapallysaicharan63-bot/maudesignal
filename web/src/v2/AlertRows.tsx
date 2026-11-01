// One row pattern for alerts in the v2 layout (Home, Signals · Ranked, Signals · All alerts), two lines per row:
// line 1 the code, the device name and the rule as a badge; line 2 the stored counts, "4 this week (0.25 before)".
// The source ("Stored · AI device sweep · 2026-09-30") is said once, in the list's caption. The whole row opens the
// alert panel. Numbers and names come from the stored exports; a missing name is said, never made up.
import type { AlertDetail } from '../alerts'
import type { AlertItem } from '../dashboard'
import { Icon } from '../icons'
import { Pill } from '../components/artifacts/common'
import type { WorkspaceData } from '../types'
import { demoDetails, itemOf, rankReal, realAlertItems, sweepDetails } from './realAlerts'

export const NO_NAME = 'name not in stored data'

export interface AlertRowModel {
  id: string
  code: string
  /** The device type's name from the stored data; null when no stored file names it. */
  name: string | null
  tone: 'bad' | 'warn'
  label: string
  /** "4 this week (0.25 before)"; null when no count is stored. */
  counts: string | null
}

export interface AlertRowList {
  rows: AlertRowModel[]
  /** Said once above the list, e.g. "Stored · AI device sweep · 2026-09-30". */
  source: string | null
}

/** Device type names the stored briefs give, by product code. */
function briefNames(data: Pick<WorkspaceData, 'briefs'>): Map<string, string> {
  const m = new Map<string, string>()
  for (const b of data.briefs ?? []) for (const [c, n] of Object.entries(b.device_types ?? {})) if (n && !m.has(c)) m.set(c, n)
  return m
}

function fromDetail(d: AlertDetail, names: Map<string, string>): AlertRowModel {
  const it = itemOf(d)
  const w = d.window
  let counts: string | null = null
  if (w && w.this_week.count != null) {
    const where = d.source.kind === 'brief' ? 'that week' : 'this week'
    counts = w.baseline_4wk.weekly_mean != null ? `${w.this_week.count} ${where} (${w.baseline_4wk.weekly_mean} before)` : `${w.this_week.count} ${where}`
  }
  return {
    id: d.id,
    code: d.product_code,
    name: d.device_type ?? names.get(d.product_code) ?? null,
    tone: it.kind === 'severity_escalation' ? 'bad' : 'warn',
    label: it.label,
    counts,
  }
}

function fromItem(a: AlertItem, names: Map<string, string>): AlertRowModel {
  return {
    id: a.id,
    code: a.productCode,
    name: a.deviceName ?? names.get(a.productCode) ?? null,
    tone: a.kind === 'severity_escalation' ? 'bad' : 'warn',
    label: a.label,
    counts: a.detail || null,
  }
}

function sourceOf(details: AlertDetail[]): string | null {
  const d = details[0]
  if (!d) return null
  const dates = [...new Set(details.map((x) => x.source.as_of).filter(Boolean))]
  return `Stored · ${d.source.label}${dates.length === 1 ? ` · ${dates[0]}` : ''}`
}

/** This week's real alerts (the AI device sweep), ranked. Never a simulated device, never the demo brief. */
export function realRows(data: Pick<WorkspaceData, 'alerts' | 'sweep' | 'briefs'>): AlertRowList {
  const names = briefNames(data)
  const details = sweepDetails(data)
  if (details.length > 0) return { rows: rankReal(details).map((d) => fromDetail(d, names)), source: sourceOf(details) }
  return { rows: realAlertItems(data).map((a) => fromItem(a, names)), source: 'Stored · AI device sweep' }
}

/** The demo-snapshot brief's alerts (real reports from the demo database, not this week), listed apart. */
export function demoRows(data: Pick<WorkspaceData, 'alerts' | 'briefs'>): AlertRowList {
  const names = briefNames(data)
  const details = demoDetails(data)
  return { rows: rankReal(details).map((d) => fromDetail(d, names)), source: sourceOf(details) }
}

export function AlertRows({
  rows,
  onOpen,
  ranked = false,
  label,
  testid,
}: {
  rows: AlertRowModel[]
  onOpen: (id: string, code: string) => void
  ranked?: boolean
  label: string
  testid?: string
}) {
  if (rows.length === 0) return <p className="ms2-muted m-0">No alerts right now.</p>
  const List = ranked ? 'ol' : 'ul'
  return (
    <List className="ms2-alerts" aria-label={label} data-testid={testid}>
      {rows.map((r, i) => (
        <li key={r.id} data-testid={ranked ? 'ranked-row' : undefined}>
          <button
            type="button"
            className="ms2-alertrow"
            onClick={() => onOpen(r.id, r.code)}
            aria-label={`${ranked ? `${i + 1}. ` : ''}${r.code}, ${r.name ?? NO_NAME}: ${r.label}.${r.counts ? ` ${r.counts}.` : ''} Open details.`}
          >
            {ranked && (
              <span className="ms2-rank ms-num" aria-hidden="true">
                {i + 1}
              </span>
            )}
            <span className="ms2-alertrow-body">
              <span className="ms2-alertrow-l1">
                <span className="ms-code">{r.code}</span>
                {r.name ? (
                  <span className="ms2-alertrow-title">{r.name}</span>
                ) : (
                  <span className="ms2-muted" data-testid="no-name">
                    · {NO_NAME}
                  </span>
                )}
                <Pill tone={r.tone}>{r.label}</Pill>
              </span>
              {r.counts && <span className="ms2-alertrow-l3 ms-num">{r.counts}</span>}
            </span>
            <Icon name="chevron" size={18} />
          </button>
        </li>
      ))}
    </List>
  )
}

/** A short caption above a list: where the rows come from, said once. */
export function SourceCaption({ text, testid }: { text: string | null; testid?: string }) {
  if (!text) return null
  return (
    <p className="ms2-caption" data-testid={testid}>
      <span className="ms2-tag">Stored</span> {text.replace(/^Stored · /, '')}
    </p>
  )
}
