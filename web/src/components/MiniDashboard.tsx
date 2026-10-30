import { useState } from 'react'
import { miniStats, recentItems, workflowThreads, type RecentItem } from '../dashboard'
import { WORKFLOWS } from '../data'
import { Icon } from '../icons'
import { FULLSCREEN } from '../layout'
import type { WorkflowId, WorkspaceData } from '../types'
import { MetricsChart } from './MetricsChart'
import { NEEDS_REVIEW } from '../dashboard'
import { Crumbs, ExpandButton } from './PanelBar'
import { StatusBars, StatusFilterList } from './OurDevices'
import { SweepFlagged, SweepRules } from './SweepCard'

export function miniTitle(workflow: WorkflowId): string {
  return WORKFLOWS.find((w) => w.id === workflow)?.title ?? 'Dashboard'
}

/** The key numbers of one workflow, computed from the stored exports. */
export function MiniStats({ workflow, data, expanded = false }: { workflow: WorkflowId; data: WorkspaceData; expanded?: boolean }) {
  const stats = miniStats(workflow, data)
  return (
    <dl className={['m-0 grid gap-2', expanded ? 'grid-cols-2 md:grid-cols-4' : 'grid-cols-2 lg:grid-cols-1'].join(' ')}>
      {stats.map((s) => (
        <div key={s.label} className="rounded-md border border-rule bg-paper p-3 max-lg:p-2">
          <dt className="text-[17px] leading-snug text-ink-2">{s.label}</dt>
          <dd className="t-index ms-num ws-wrap m-0 mt-1 max-lg:!text-[26px] max-lg:!leading-tight">{s.value}</dd>
          {s.note && <dd className="m-0 mt-0.5 text-[17px] leading-snug text-ink-2">{s.note}</dd>}
        </div>
      ))}
    </dl>
  )
}

/** The workflow's recorded answers: a short list in the column, a table when the panel is expanded. */
function Recent({
  items,
  expanded,
  onOpen,
  activeId,
}: {
  items: RecentItem[]
  expanded: boolean
  onOpen: (i: RecentItem) => void
  /** The recorded answer open in the chat, marked in the list. */
  activeId: string | null
}) {
  if (items.length === 0) return null
  if (expanded)
    return (
      <div className="mt-4">
        <h3 className="ms-kicker m-0 mb-2">Recorded answers in this workflow · {items.length} · sorted newest first</h3>
        <div className="rounded-md border border-rule">
          <table className="w-full table-fixed border-collapse text-left text-[16px]">
            <thead>
              <tr className="bg-sunk text-[17px] text-ink-2">
                <th className="px-3 py-2 font-semibold">Question or run</th>
                <th className="w-[4.5rem] px-2 py-2 font-semibold">Shown</th>
                <th className="w-[5.5rem] px-2 py-2 font-semibold">Withheld</th>
                <th className="w-[6.5rem] px-2 py-2 font-semibold">Cost</th>
              </tr>
            </thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.id} className={['border-t border-rule', i.id === activeId ? 'bg-accent-soft font-semibold' : ''].join(' ')} aria-current={i.id === activeId ? 'true' : undefined}>
                  <td className="px-3 py-1">
                    <button type="button" className="ws-wrap min-h-11 text-left text-accent underline" onClick={() => onOpen(i)}>
                      {i.label}
                    </button>
                  </td>
                  <td className="ms-num px-2 py-1">{i.shown}</td>
                  <td className="ms-num px-2 py-1">{i.withheld}</td>
                  <td className="ms-num ws-wrap px-2 py-1">{i.cost}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    )
  return (
    <div className="mt-4">
      <h3 className="ms-kicker m-0 mb-1">Recorded answers · {items.length}</h3>
      <p className="m-0 mb-1 text-[17px] text-ink-2">Sorted newest first. The open answer is marked.</p>
      <ul className="m-0 list-none p-0">
        {items.slice(0, 8).map((i) => (
          <li key={i.id} className="border-t border-rule first:border-t-0">
            <button
              type="button"
              className={[
                'flex min-h-11 w-full items-center justify-between gap-1 rounded-xs px-2 py-2 text-left text-[17px] leading-snug text-ink hover:bg-sunk',
                i.id === activeId ? 'bg-accent-soft font-semibold shadow-[inset_4px_0_0_var(--accent)]' : '',
              ].join(' ')}
              aria-current={i.id === activeId ? 'true' : undefined}
              onClick={() => onOpen(i)}
            >
              <span className="min-w-0">
                <span className="ws-wrap line-clamp-3 block">{i.label}</span>
                <span className="ms-num block text-[17px] font-normal text-ink-2">
                  {i.shown} shown · {i.cost}
                </span>
              </span>
              <span className="shrink-0 text-accent" aria-hidden="true">
                <Icon name="chevron" size={18} />
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Left column beside the chat: the workflow's own key numbers. Expands to full screen with a little more. */
export function MiniPane({
  workflow,
  data,
  expanded,
  onToggleExpand,
  onThread = () => undefined,
  onRun = () => undefined,
  focusCode = null,
  activeId = null,
  deviceFilter = null,
  onDeviceFilter = () => undefined,
}: {
  workflow: WorkflowId
  data: WorkspaceData
  expanded: boolean
  onToggleExpand: () => void
  onThread?: (id: string) => void
  onRun?: (id: string) => void
  /** Product code to scroll to and mark in the flagged list (set by an alert link). */
  focusCode?: string | null
  /** Id of the thread or run open in the chat. */
  activeId?: string | null
  /** Our devices: the status the table is filtered to, and how to change it. */
  deviceFilter?: string | null
  onDeviceFilter?: (label: string | null) => void
}) {
  // Below the xl breakpoint the numbers start folded away so the chat keeps the screen.
  const [shown, setShown] = useState(false)
  const threads = workflowThreads(data, workflow)
  const items = recentItems(workflow, data)
  const devices = workflow === 'our-devices'
  const needReview = devices ? data.company.devices.filter((d) => d.status?.label === NEEDS_REVIEW).length : 0
  const pick = (label: string | null) => {
    setShown(false)
    onDeviceFilter(label)
  }
  const open = (i: RecentItem) => {
    if (expanded) onToggleExpand()
    if (i.kind === 'run') onRun(i.id)
    else onThread(i.id)
  }
  return (
    <aside
      aria-label={`${miniTitle(workflow)} dashboard`}
      data-expanded={expanded}
      className={[
        'flex shrink-0 flex-col border-rule bg-surface',
        expanded ? `${FULLSCREEN} overflow-y-auto` : 'max-lg:max-h-[50dvh] max-lg:overflow-y-auto max-lg:border-b lg:w-56 lg:overflow-y-auto lg:border-r xl:w-64',
      ].join(' ')}
    >
      <div className="flex shrink-0 items-center justify-between gap-2 px-3 py-1">
        {expanded && devices ? (
          <h2 className="m-0 min-w-0 truncate text-[19px] font-semibold">{miniTitle(workflow)}</h2>
        ) : expanded ? (
          <Crumbs panel="mini" />
        ) : (
          <>
            <h2 className="ws-wrap m-0 min-w-0 text-[17px] font-semibold leading-snug max-lg:hidden">
              {miniTitle(workflow)}
            </h2>
            {/* Phone and tablet: one bar that names the workflow and opens its numbers and recorded answers. */}
            <button
              type="button"
              className="flex min-h-11 min-w-0 flex-1 items-center justify-between gap-2 text-left lg:hidden"
              aria-expanded={shown}
              aria-controls="mini-body"
              onClick={() => setShown((s) => !s)}
              data-testid="mini-toggle"
            >
              <span className="min-w-0">
                <span className="block truncate text-[17px] font-semibold">{miniTitle(workflow)}</span>
                <span className="block text-[17px] text-ink-2" data-testid="mini-summary">
                  {devices
                    ? `${needReview} ${needReview === 1 ? 'needs' : 'need'} review · ${data.company.devices.length} devices`
                    : shown
                      ? 'Hide stats and recorded answers'
                      : 'Stats and recorded answers'}
                </span>
              </span>
              <span className="shrink-0 text-ink-2">
                <Icon name={shown ? 'up' : 'down'} size={20} />
              </span>
            </button>
          </>
        )}
        <span className="flex shrink-0 items-center">
          {expanded && devices ? (
            <button
              type="button"
              className="ws-icon-btn min-h-11 min-w-11 border-rule-strong bg-surface"
              onClick={onToggleExpand}
              aria-label="Close the dashboard (Esc)"
              title="Close (Esc)"
              data-testid="expand-mini"
            >
              <Icon name="close" size={20} />
            </button>
          ) : (
            <ExpandButton panel="mini" expanded={expanded} onToggle={onToggleExpand} iconOnly />
          )}
        </span>
      </div>
      <div id="mini-body" className={['px-3 pb-4', shown || expanded ? '' : 'max-lg:hidden'].join(' ')}>
        {devices ? (
          expanded ? (
            <StatusBars company={data.company} onFilter={onDeviceFilter} />
          ) : (
            <StatusFilterList company={data.company} filter={deviceFilter} onFilter={pick} />
          )
        ) : (
          <MiniStats workflow={workflow} data={data} expanded={expanded} />
        )}
        {!expanded && <Recent items={items} expanded={false} onOpen={open} activeId={activeId} />}
        {expanded && workflow === 'ai-sweep' && (
          <>
            <SweepRules sweep={data.sweep} />
            <div className="mt-4">
              <SweepFlagged sweep={data.sweep} focusCode={focusCode} />
            </div>
          </>
        )}
        {expanded && <Recent items={items} expanded onOpen={open} activeId={activeId} />}
        {expanded && threads.length > 0 && (
          <div className="mt-4">
            <h3 className="ms-kicker m-0 mb-2">Recorded runs in this workflow</h3>
            <MetricsChart threads={threads} />
          </div>
        )}
      </div>
    </aside>
  )
}
