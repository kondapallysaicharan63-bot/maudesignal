// One row pattern for real FDA alerts in the v2 layout (Home, Signals · Ranked, Signals · All alerts): line 1 the code
// and device type, line 2 the rule as a badge, line 3 the stored numbers and source (each piece kept on one line). The
// whole row opens the alert panel. Numbers come from alerts.json; nothing is computed here.
import { Fragment } from 'react'
import type { AlertDetail } from '../alerts'
import type { AlertItem } from '../dashboard'
import { Icon } from '../icons'
import { Pill } from '../components/artifacts/common'
import { itemOf, rankReal, realAlertItems, realDetails } from './realAlerts'
import type { WorkspaceData } from '../types'

export interface AlertRowModel {
  id: string
  code: string
  title: string | null
  tone: 'bad' | 'warn'
  label: string
  /** Lines under the badge (the stored numbers, then the source); each piece stays on one line. */
  meta: string[][]
}

function fromDetail(d: AlertDetail): AlertRowModel {
  const it = itemOf(d)
  const w = d.window
  const nums: string[] = []
  if (w && w.this_week.count != null) {
    nums.push(`${w.this_week.count} ${d.source.kind === 'brief' ? 'that week' : 'this week'}`)
    if (w.baseline_4wk.weekly_mean != null) nums.push(`${w.baseline_4wk.weekly_mean} a week before`)
  }
  const src = [`Stored · ${d.source.label}`, ...(d.source.as_of ? [d.source.as_of] : [])]
  const meta = nums.length ? [nums, src] : [src]
  return { id: d.id, code: d.product_code, title: d.device_type, tone: it.kind === 'severity_escalation' ? 'bad' : 'warn', label: it.label, meta }
}

function fromItem(a: AlertItem): AlertRowModel {
  return {
    id: a.id,
    code: a.productCode,
    title: a.deviceName ?? null,
    tone: a.kind === 'severity_escalation' ? 'bad' : 'warn',
    label: a.label,
    meta: [[a.detail], [a.source === 'brief' ? 'Demo snapshot brief' : 'AI device sweep', a.date].filter(Boolean)],
  }
}

/** The real alerts as rows, ranked (more serious first). Never a simulated device. */
export function realRows(data: Pick<WorkspaceData, 'alerts' | 'sweep' | 'briefs'>): AlertRowModel[] {
  const details = realDetails(data)
  return details.length > 0 ? rankReal(details).map(fromDetail) : realAlertItems(data).map(fromItem)
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
            aria-label={`${ranked ? `${i + 1}. ` : ''}${r.title ? `${r.title}, ` : ''}${r.code}: ${r.label}. ${r.meta.map((l) => l.join(', ')).join('; ')}. Open details.`}
          >
            {ranked && (
              <span className="ms2-rank ms-num" aria-hidden="true">
                {i + 1}
              </span>
            )}
            <span className="ms2-alertrow-body">
              <span className="ms2-alertrow-l1">
                <span className="ms-code">{r.code}</span>
                {r.title && <span className="ms2-alertrow-title">{r.title}</span>}
              </span>
              <span className="ms2-alertrow-l2">
                <Pill tone={r.tone}>{r.label}</Pill>
              </span>
              {r.meta.map((line, k) => (
                <span key={k} className="ms2-alertrow-l3 ms-num">
                  {line.map((m, j) => (
                    <Fragment key={j}>
                      {j > 0 && ' '}
                      <span className="ms2-nowrap">
                        {j > 0 && '· '}
                        {m}
                      </span>
                    </Fragment>
                  ))}
                </span>
              ))}
            </span>
            <Icon name="chevron" size={18} />
          </button>
        </li>
      ))}
    </List>
  )
}
