import { WORKFLOWS } from '../data'
import { Icon } from '../icons'
import type { Evidence, Threads, WorkflowDef, WorkflowId } from '../types'
import { Composer } from './Composer'
import { ThreadView } from './ThreadView'

export type View =
  | { kind: 'new' }
  | { kind: 'workflow'; id: WorkflowId }
  | { kind: 'thread'; id: string }

interface Props {
  view: View
  threads: Threads
  evidence: Evidence
  investigationNotes: string[]
  recordedRuns: number
  onWorkflow: (id: WorkflowId) => void
  onThread: (id: string) => void
}

function WorkflowView(p: Props & { def: WorkflowDef }) {
  const group = p.threads.workflows.find((w) => w.id === p.def.id)
  const items = group ? p.threads.threads.filter((t) => group.thread_ids.includes(t.id)) : []
  const agentic = p.def.id === 'weekly-investigator' || p.def.id === 'recall-sweep'
  return (
    <div>
      <h1 className="t-title-lg m-0">{p.def.title}</h1>
      <p className="mt-2 text-ink-2">{p.def.blurb}</p>
      {agentic && p.recordedRuns === 0 && (
        <p className="ms-banner ms-banner--info mt-4">
          Coming soon. {p.investigationNotes[0] ?? 'No recorded runs yet.'}
        </p>
      )}
      {agentic && p.recordedRuns > 0 && (
        <p className="ms-banner ms-banner--info mt-4">{`${p.recordedRuns} recorded runs.`}</p>
      )}
      {p.def.comingSoon && !agentic && (
        <p className="ms-banner ms-banner--info mt-4">Coming soon. Nothing is stored here yet.</p>
      )}
      {p.def.id === 'vision' && (
        <p className="ms-banner ms-banner--info mt-4">
          Stored readings are loaded. Viewing them here is coming soon.
        </p>
      )}
      {items.length > 0 && (
        <>
          <h2 className="ms-kicker mt-6">Stored questions · {items.length}</h2>
          <ul className="m-0 mt-2 list-none p-0">
            {items.map((t) => (
              <li key={t.id}>
                <button
                  className="ws-side-item items-start border-b border-rule"
                  onClick={() => p.onThread(t.id)}
                >
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

function Welcome({ onWorkflow }: { onWorkflow: (id: WorkflowId) => void }) {
  return (
    <div>
      <p className="ms-kicker">Postmarket surveillance · FDA-cleared AI/ML devices</p>
      <h1 className="t-headline mt-2" style={{ fontSize: 'clamp(30px, 6vw, 44px)' }}>
        What do you want to look into?
      </h1>
      <p className="mt-3 max-w-xl text-ink-2">
        Answers here are written from stored public records (MAUDE reports, recalls, 510(k)s, PubMed,
        MHRA (UK) alerts). Each sentence is checked before it is shown; a sentence with no factual claim
        is marked as such. Pick a workflow to start.
      </p>
      <ul className="m-0 mt-6 grid list-none grid-cols-1 gap-3 p-0 sm:grid-cols-2">
        {WORKFLOWS.map((w) => (
          <li key={w.id}>
            <button
              onClick={() => onWorkflow(w.id)}
              className="h-full w-full rounded-md border border-rule bg-surface p-4 text-left hover:border-rule-strong"
            >
              <span className="t-title block">
                {w.title}
                {w.comingSoon && <span className="ws-pill ml-2 bg-sunk text-ink-2">coming soon</span>}
              </span>
              <span className="mt-1 block text-[15px] leading-snug text-ink-2">{w.blurb}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function ChatPane(p: Props) {
  let body: JSX.Element
  if (p.view.kind === 'new') {
    body = <Welcome onWorkflow={p.onWorkflow} />
  } else if (p.view.kind === 'workflow') {
    const id = p.view.id
    const def = WORKFLOWS.find((w) => w.id === id) ?? WORKFLOWS[0]
    body = <WorkflowView {...p} def={def} />
  } else {
    const id = p.view.id
    const t = p.threads.threads.find((x) => x.id === id)
    const group = p.threads.workflows.find((w) => w.id === t?.workflow)
    const siblings = group ? p.threads.threads.filter((x) => group.thread_ids.includes(x.id)) : []
    body = t ? (
      <ThreadView key={t.id} t={t} ev={p.evidence} siblings={siblings} onThread={p.onThread} />
    ) : (
      <p>That thread is not in the stored data.</p>
    )
  }
  return (
    <main className="flex min-w-0 flex-1 flex-col bg-paper" aria-label="Chat">
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6 md:px-8 md:py-10">
        <div className="mx-auto max-w-3xl">{body}</div>
      </div>
      <Composer threads={p.threads.threads} onThread={p.onThread} />
    </main>
  )
}
