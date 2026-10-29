import { DEMO_WORKFLOWS, describeCron, isoDay, demoSnapshotLabel, visibleWorkflows } from '../data'
import { flaggedRows } from '../artifacts'
import { Icon } from '../icons'
import type { Brief, InvestigationRun, Schedule, Source, Sweep, Threads, Vision, WorkflowId } from '../types'

interface Props {
  open: boolean
  collapsed: boolean
  threads: Threads
  briefs: Brief[]
  sources: Source[]
  schedules: Schedule[]
  runs: InvestigationRun[]
  vision: Vision
  sweep: Sweep
  activeWorkflow: WorkflowId | null
  activeBrief: string | null
  isRead: (date: string) => boolean
  onNewChat: () => void
  onWorkflow: (id: WorkflowId) => void
  onBrief: (date: string) => void
  onClose: () => void
}

function scheduleResult(s: Schedule): string {
  const r = s.last_result
  if (!r) return 'No result yet'
  if (r.flagged !== undefined && r.checked !== undefined)
    return `Last: ${r.flagged} flagged of ${r.checked} device types · ${r.date.slice(0, 10)}`
  return `Newest brief: ${r.date} · demo snapshot`
}

export function Sidebar(p: Props) {
  // Greetings (no tool steps, no claims) are not answers, so they are not counted.
  const greeting = new Set(
    p.threads.threads
      .filter((t) => t.tool_steps.length === 0 && t.sentences.every((s) => s.claims.length === 0))
      .map((t) => t.id),
  )
  const counts = new Map<string, number>(
    p.threads.workflows.map((w) => [w.id, w.thread_ids.filter((id) => !greeting.has(id)).length]),
  )
  counts.set('ai-sweep', flaggedRows(p.sweep).length)
  counts.set('vision', p.vision.k510.length + p.vision.labels.length)
  for (const kind of ['weekly-investigator', 'recall-sweep'])
    counts.set(kind, p.runs.filter((r) => r.kind === kind).length)
  const workflows = visibleWorkflows(p.runs)
  return (
    <>
      {p.open && (
        <div className="fixed inset-0 z-30 bg-ink/40 md:hidden" onClick={p.onClose} aria-hidden="true" />
      )}
      <aside
        id="sidebar"
        aria-label="Workspace"
        className={[
          'z-40 flex w-[min(88vw,22rem)] shrink-0 flex-col border-r border-rule bg-surface transition-transform duration-200',
          'max-md:fixed max-md:inset-y-0 max-md:left-0',
          p.open ? '' : 'max-md:invisible max-md:-translate-x-full',
          p.collapsed ? 'md:hidden' : 'md:static md:w-72',
        ].join(' ')}
      >
        <div className="flex items-center justify-between px-3 pt-3 md:hidden">
          <span className="font-serif text-xl font-semibold">MaudeSignal</span>
          <button className="ws-icon-btn" onClick={p.onClose} aria-label="Close menu">
            <Icon name="close" />
          </button>
        </div>
        <div className="px-3 pt-3">
          <button
            className="ms-btn ms-btn--secondary w-full justify-start"
            onClick={p.onNewChat}
            style={{ height: 44 }}
          >
            <Icon name="plus" size={18} /> New chat
          </button>
        </div>

        <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-24" aria-label="Sections">
          <h2 className="ws-heading">Workflows</h2>
          <ul className="m-0 list-none p-0">
            {workflows.map((w) => {
              const n = counts.get(w.id)
              return (
                <li key={w.id}>
                  <button
                    className="ws-side-item"
                    aria-current={p.activeWorkflow === w.id ? 'true' : undefined}
                    onClick={() => p.onWorkflow(w.id)}
                  >
                    <span className="min-w-0">
                      {w.title}
                      {DEMO_WORKFLOWS.includes(w.id) && <span className="text-[13px] text-ink-3"> · demo</span>}
                    </span>
                    {n !== undefined && (
                      <span className="ms-num shrink-0 text-[14px] text-ink-3">
                        {w.id === 'ai-sweep' ? `${n} flagged` : n}
                      </span>
                    )}
                  </button>
                </li>
              )
            })}
          </ul>

          <h2 className="ws-heading">Daily briefs · demo snapshot</h2>
          {p.briefs.length === 0 ? (
            <p className="px-3 text-[15px] text-ink-3">No briefs stored yet.</p>
          ) : (
            <ul className="m-0 list-none p-0">
              {p.briefs.map((b) => (
                <li key={b.date}>
                  <button
                    className="ws-side-item"
                    aria-current={p.activeBrief === b.date ? 'true' : undefined}
                    onClick={() => p.onBrief(b.date)}
                  >
                    <span className="min-w-0">
                      <span className="ms-num block">{b.date}</span>
                      <span className="block truncate text-[14px] text-ink-3">
                        Demo snapshot · week {isoDay(b.window.current_start)} to {isoDay(b.window.current_end)}
                      </span>
                    </span>
                    {!p.isRead(b.date) && <span className="ws-dot" role="img" aria-label="unread" />}
                  </button>
                </li>
              ))}
            </ul>
          )}

          <h2 className="ws-heading">Schedules</h2>
          <ul className="m-0 list-none space-y-2 p-0 px-3">
            {p.schedules.map((s) => (
              <li key={s.id} className="text-[15px] leading-snug">
                <span className="block font-semibold">{s.label}</span>
                <span className="block text-ink-3">{describeCron(s.cron)}</span>
                <span className="ws-wrap block text-ink-2">{scheduleResult(s)}</span>
              </li>
            ))}
          </ul>

          <h2 className="ws-heading">Sources · demo database</h2>
          <ul className="m-0 list-none p-0 px-3">
            {p.sources.map((s) => (
              <li key={s.id} className="flex justify-between gap-3 py-[3px] text-[15px]">
                <span>{s.label}</span>
                <span className="ms-num text-ink-2">{s.records.toLocaleString('en-US')}</span>
              </li>
            ))}
          </ul>
          <p className="px-3 pt-2 text-[13px] leading-snug text-ink-3">
            {demoSnapshotLabel(p.sources)}: stored records in the demo database, not live openFDA. MHRA (UK) is regulator
            context only and never counted in a MAUDE number.
          </p>
        </nav>
      </aside>
    </>
  )
}
