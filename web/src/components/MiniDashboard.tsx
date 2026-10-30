import { useState } from 'react'
import { miniStats, recentItems, workflowThreads, type RecentItem } from '../dashboard'
import { WORKFLOWS } from '../data'
import { Icon } from '../icons'
import { FULLSCREEN } from '../layout'
import type { WorkflowId, WorkspaceData } from '../types'
import { MetricsChart } from './MetricsChart'
import { Crumbs, ExpandButton } from './PanelBar'
import { SweepFlagged, SweepRules } from './SweepCard'

export function miniTitle(workflow: WorkflowId): string {
  return WORKFLOWS.find((w) => w.id === workflow)?.title ?? 'Dashboard'
}

/** The key numbers of one workflow, computed from the stored exports. */
export function MiniStats({ workflow, data, expanded = false }: { workflow: WorkflowId; data: WorkspaceData; expanded?: boolean }) {
  const stats = miniStats(workflow, data)
  return (
    <dl className={['m-0 grid gap-2', expanded ? 'grid-cols-2 md:grid-cols-4' : 'grid-cols-2 xl:grid-cols-1'].join(' ')}>
      {stats.map((s) => (
        <div key={s.label} className="rounded-md border border-rule bg-paper p-3 max-xl:p-2">
          <dt className="text-[15px] leading-snug text-ink-2">{s.label}</dt>
          <dd className="t-index ms-num ws-wrap m-0 mt-1 max-xl:!text-[26px] max-xl:!leading-tight">{s.value}</dd>
          {s.note && <dd className="m-0 mt-0.5 text-[15px] leading-snug text-ink-2">{s.note}</dd>}
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
}: {
  items: RecentItem[]
  expanded: boolean
  onOpen: (i: RecentItem) => void
}) {
  if (items.length === 0) return null
  if (expanded)
    return (
      <div className="mt-4">
        <h3 className="ms-kicker m-0 mb-2">Recorded answers in this workflow · {items.length}</h3>
        <div className="overflow-x-auto rounded-md border border-rule">
          <table className="w-full border-collapse text-left text-[16px]">
            <thead>
              <tr className="bg-sunk text-[15px] text-ink-2">
                <th className="px-3 py-2 font-semibold">Question or run</th>
                <th className="px-3 py-2 font-semibold">Shown</th>
                <th className="px-3 py-2 font-semibold">Withheld</th>
                <th className="px-3 py-2 font-semibold">Cost</th>
              </tr>
            </thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.id} className="border-t border-rule">
                  <td className="px-3 py-1">
                    <button type="button" className="min-h-11 text-left text-accent underline" onClick={() => onOpen(i)}>
                      {i.label}
                    </button>
                  </td>
                  <td className="ms-num px-3 py-1">{i.shown}</td>
                  <td className="ms-num px-3 py-1">{i.withheld}</td>
                  <td className="ms-num whitespace-nowrap px-3 py-1">{i.cost}</td>
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
      <ul className="m-0 list-none p-0">
        {items.slice(0, 8).map((i) => (
          <li key={i.id} className="border-t border-rule first:border-t-0">
            <button
              type="button"
              className="flex min-h-11 w-full items-center justify-between gap-1 rounded-xs py-2 text-left text-[16px] leading-snug text-ink hover:bg-sunk"
              onClick={() => onOpen(i)}
            >
              <span className="min-w-0">
                <span className="ws-wrap line-clamp-3 block">{i.label}</span>
                <span className="ms-num block text-[14px] text-ink-2">
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
}: {
  workflow: WorkflowId
  data: WorkspaceData
  expanded: boolean
  onToggleExpand: () => void
  onThread?: (id: string) => void
  onRun?: (id: string) => void
}) {
  // Below the xl breakpoint the numbers start folded away so the chat keeps the screen.
  const [shown, setShown] = useState(false)
  const threads = workflowThreads(data, workflow)
  const items = recentItems(workflow, data)
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
        expanded ? `${FULLSCREEN} overflow-y-auto` : 'max-xl:max-h-[50dvh] max-xl:overflow-y-auto max-xl:border-b xl:w-56 xl:overflow-y-auto xl:border-r 2xl:w-64',
      ].join(' ')}
    >
      <div className="flex shrink-0 items-center justify-between gap-2 px-3 py-1">
        {expanded ? <Crumbs panel="mini" /> : <h2 className="m-0 min-w-0 truncate text-[17px] font-semibold" title={miniTitle(workflow)}>{miniTitle(workflow)}</h2>}
        <span className="flex shrink-0 items-center">
          {!expanded && (
            <button
              type="button"
              className="ws-icon-btn min-h-11 xl:hidden"
              aria-expanded={shown}
              aria-controls="mini-body"
              onClick={() => setShown((s) => !s)}
            >
              <span className="text-[17px]">{shown ? 'Hide numbers' : 'Show numbers'}</span>
            </button>
          )}
          <ExpandButton panel="mini" expanded={expanded} onToggle={onToggleExpand} iconOnly />
        </span>
      </div>
      <div id="mini-body" className={['px-3 pb-4', shown || expanded ? '' : 'max-xl:hidden'].join(' ')}>
        <MiniStats workflow={workflow} data={data} expanded={expanded} />
        {!expanded && <Recent items={items} expanded={false} onOpen={open} />}
        {expanded && workflow === 'ai-sweep' && (
          <>
            <SweepRules sweep={data.sweep} />
            <div className="mt-4">
              <SweepFlagged sweep={data.sweep} />
            </div>
          </>
        )}
        {expanded && <Recent items={items} expanded onOpen={open} />}
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
