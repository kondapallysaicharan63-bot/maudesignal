import { useState } from 'react'
import { miniStats, workflowThreads } from '../dashboard'
import { WORKFLOWS } from '../data'
import { FULLSCREEN } from '../layout'
import type { WorkflowId, WorkspaceData } from '../types'
import { MetricsChart } from './MetricsChart'
import { ExpandButton } from './PanelBar'
import { SweepRules } from './SweepCard'

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
          <dt className="text-[14px] leading-snug text-ink-2">{s.label}</dt>
          <dd className="t-index ms-num ws-wrap m-0 mt-1 max-xl:!text-[26px] max-xl:!leading-tight">{s.value}</dd>
          {s.note && <dd className="m-0 mt-0.5 text-[14px] leading-snug text-ink-3">{s.note}</dd>}
        </div>
      ))}
    </dl>
  )
}

/** Left column beside the chat: the workflow's own key numbers. Expands to full screen with a little more. */
export function MiniPane({
  workflow,
  data,
  expanded,
  onToggleExpand,
}: {
  workflow: WorkflowId
  data: WorkspaceData
  expanded: boolean
  onToggleExpand: () => void
}) {
  const [shown, setShown] = useState(true) // below the xl breakpoint the numbers can be hidden to give the chat room
  const threads = workflowThreads(data, workflow)
  return (
    <aside
      aria-label={`${miniTitle(workflow)} dashboard`}
      data-expanded={expanded}
      className={[
        'flex shrink-0 flex-col border-rule bg-surface',
        expanded ? `${FULLSCREEN} overflow-y-auto` : 'max-xl:border-b xl:w-64 xl:overflow-y-auto xl:border-r',
      ].join(' ')}
    >
      <div className="flex shrink-0 items-center justify-between gap-2 px-4 py-1">
        <h2 className="m-0 text-[16px] font-semibold">{miniTitle(workflow)}</h2>
        <span className="flex items-center">
          {!expanded && (
            <button
              type="button"
              className="ws-icon-btn xl:hidden"
              aria-expanded={shown}
              aria-controls="mini-body"
              onClick={() => setShown((s) => !s)}
            >
              <span className="text-[15px]">{shown ? 'Hide numbers' : 'Show numbers'}</span>
            </button>
          )}
          <ExpandButton panel="mini" expanded={expanded} onToggle={onToggleExpand} />
        </span>
      </div>
      <div id="mini-body" className={['px-4 pb-4', shown || expanded ? '' : 'max-xl:hidden'].join(' ')}>
        <MiniStats workflow={workflow} data={data} expanded={expanded} />
        {expanded && workflow === 'ai-sweep' && <SweepRules sweep={data.sweep} />}
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
