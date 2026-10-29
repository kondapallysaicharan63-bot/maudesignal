import { DEMO_WORKFLOWS, demoSnapshotLabel, WORKFLOWS } from '../data'
import type { AlertItem } from '../dashboard'
import { FULLSCREEN } from '../layout'
import { Icon } from '../icons'
import type { WorkflowDef, WorkflowId, WorkspaceData } from '../types'
import { Composer } from './Composer'
import { Dashboard } from './Dashboard'
import { RunList, RunView } from './InvestigationViews'
import { LiveCheckView } from './LiveCheckView'
import { PanelBar } from './PanelBar'
import { SweepCard } from './SweepCard'
import { ThreadView } from './ThreadView'
import { VisionWorkflow, type VisionSel } from './VisionWorkflow'

export type View =
  | { kind: 'new' }
  | { kind: 'workflow'; id: WorkflowId }
  | { kind: 'thread'; id: string }
  | { kind: 'run'; id: string }

/** Stable identity of the screen shown (used to scope the composer's messages). */
export const viewKey = (v: View): string => (v.kind === 'new' ? 'new' : `${v.kind}:${v.id}`)

export interface WithheldNav {
  /** Sentence to highlight in the open thread. */
  highlight: { threadId: string; index: number }
  pos: number
  total: number
  onNext: () => void
}

interface Props {
  view: View
  data: WorkspaceData
  withheld: WithheldNav | null
  onWorkflow: (id: WorkflowId) => void
  onThread: (id: string) => void
  onRun: (id: string) => void
  onVision: (sel: VisionSel) => void
  onBrief: (date: string) => void
  onAlert: (a: AlertItem) => void
  expanded: boolean
  onToggleExpand: () => void
}

function StoredList({ def, data, onThread }: { def: WorkflowDef; data: WorkspaceData; onThread: (id: string) => void }) {
  const group = data.threads.workflows.find((w) => w.id === def.id)
  const items = group ? data.threads.threads.filter((t) => group.thread_ids.includes(t.id)) : []
  const demo = DEMO_WORKFLOWS.includes(def.id)
  return (
    <div>
      <h1 className="t-title-lg m-0">{def.title}</h1>
      <p className="mt-2 text-ink-2">{def.blurb}</p>
      {demo && (
        <p className="ms-banner ms-banner--warn mt-4">
          <span className="ws-wrap">
            <strong>{demoSnapshotLabel(data.sources)}.</strong> These answers were recorded against the demo database, not
            this week's openFDA data. For the newest real data, open the AI device sweep.
          </span>
        </p>
      )}
      {items.length > 0 && (
        <>
          <h2 className="ms-kicker mt-6">Stored questions · {items.length}</h2>
          <ul className="m-0 mt-2 list-none p-0">
            {items.map((t) => (
              <li key={t.id}>
                <button className="ws-side-item items-start border-b border-rule" onClick={() => onThread(t.id)}>
                  <span className="ws-wrap">{t.question}</span>
                  <Icon name="chevron" size={18} />
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

export function ChatPane(p: Props) {
  const { data } = p
  let body: JSX.Element
  if (p.view.kind === 'new') {
    body = <Dashboard data={data} onWorkflow={p.onWorkflow} onBrief={p.onBrief} onAlert={p.onAlert} />
  } else if (p.view.kind === 'workflow') {
    const id = p.view.id
    const def = WORKFLOWS.find((w) => w.id === id) ?? WORKFLOWS[0]
    if (id === 'ai-sweep') body = <SweepCard sweep={data.sweep} />
    else if (id === 'check-device') body = <LiveCheckView />
    else if (id === 'vision') body = <VisionWorkflow vision={data.vision} onOpen={p.onVision} />
    else if (id === 'weekly-investigator' || id === 'recall-sweep')
      body = <RunList kind={id} runs={data.investigations.investigations} notes={data.investigations.notes} onRun={p.onRun} />
    else body = <StoredList def={def} data={data} onThread={p.onThread} />
  } else if (p.view.kind === 'run') {
    const id = p.view.id
    const run = data.investigations.investigations.find((r) => r.id === id)
    body = run ? <RunView run={run} ev={data.evidence} onThread={p.onThread} /> : <p>That run is not in the stored data.</p>
  } else {
    const id = p.view.id
    const t = data.threads.threads.find((x) => x.id === id)
    const group = data.threads.workflows.find((w) => w.id === t?.workflow)
    const siblings = group ? data.threads.threads.filter((x) => group.thread_ids.includes(x.id)) : []
    const hl = p.withheld && p.withheld.highlight.threadId === id ? p.withheld : null
    body = t ? (
      <ThreadView
        key={t.id}
        t={t}
        ev={data.evidence}
        siblings={siblings}
        onThread={p.onThread}
        highlight={hl ? hl.highlight.index : null}
        withheldNav={hl ? { pos: hl.pos, total: hl.total, onNext: hl.onNext } : undefined}
        snapshot={demoSnapshotLabel(data.sources)}
      />
    ) : (
      <p>That thread is not in the stored data.</p>
    )
  }
  return (
    <main
      className={['flex min-w-0 flex-1 flex-col bg-paper', p.expanded ? FULLSCREEN : ''].join(' ')}
      aria-label={p.view.kind === 'new' ? 'Home' : 'Chat'}
      data-expanded={p.expanded}
    >
      <PanelBar title={p.view.kind === 'new' ? 'Home' : 'Chat'} panel="main" expanded={p.expanded} onToggle={p.onToggleExpand} />
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6 md:px-8 md:py-8">
        <div className={['mx-auto pb-16', p.view.kind === 'new' ? 'max-w-6xl' : 'max-w-3xl'].join(' ')}>{body}</div>
      </div>
      <Composer threads={data.threads.threads} onThread={p.onThread} viewKey={viewKey(p.view)} chips={p.view.kind === 'new'} />
    </main>
  )
}
