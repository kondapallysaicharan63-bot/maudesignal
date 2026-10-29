import { WORKFLOWS } from '../data'
import { Icon } from '../icons'
import type { Sentence, Thread, Threads, WorkflowDef, WorkflowId } from '../types'

export type View =
  | { kind: 'new' }
  | { kind: 'workflow'; id: WorkflowId }
  | { kind: 'thread'; id: string }

interface Props {
  view: View
  threads: Threads
  investigationNotes: string[]
  recordedRuns: number
  onWorkflow: (id: WorkflowId) => void
  onThread: (id: string) => void
}

const DISCLAIMER =
  'Signals for a person to review. Not medical advice; a named person makes every decision. Nothing is filed with FDA.'

function Composer() {
  return (
    <div className="shrink-0 border-t border-rule bg-paper px-3 pb-4 pt-3 md:px-6">
      <div className="mx-auto max-w-3xl">
        <div className="flex items-center gap-2 rounded-md border border-rule-strong bg-surface px-3 py-2">
          <button className="ws-icon-btn" disabled aria-label="Add (coming soon)" title="Coming soon">
            <Icon name="plus" />
          </button>
          <input
            disabled
            aria-label="Message (coming soon)"
            placeholder="Asking new questions: coming soon"
            className="min-w-0 flex-1 bg-transparent text-[17px] text-ink placeholder:text-ink-3 focus:outline-none"
          />
        </div>
        <p className="mt-2 text-center text-[13px] leading-snug text-ink-3">{DISCLAIMER}</p>
      </div>
    </div>
  )
}

function SentenceLine({ s }: { s: Sentence }) {
  const ok = s.status === 'pass'
  return (
    <li className="py-1.5">
      <span className={`ws-pill mr-2 ${ok ? 'bg-success-soft text-success' : 'bg-critical-soft text-critical'}`}>
        {ok ? 'Verified' : 'Withheld'}
      </span>
      <span className={`ws-wrap ${ok ? '' : 'text-ink-3 line-through'}`}>{s.text}</span>
      {!ok && s.reasons.length > 0 && (
        <ul className="ws-wrap m-0 mt-1 list-disc pl-8 text-[15px] text-critical">
          {s.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
    </li>
  )
}

function ThreadView({ t }: { t: Thread }) {
  return (
    <div className="space-y-5">
      <div className="ml-auto max-w-[85%] rounded-md bg-sunk px-4 py-3">
        <p className="ws-wrap m-0">{t.question}</p>
        {t.voice && <p className="m-0 mt-1 text-[13px] text-ink-3">Recorded voice question · {t.voice.audio_seconds} s</p>}
      </div>
      {t.tool_steps.length > 0 && (
        <ul className="m-0 list-none space-y-1 p-0 text-[15px] text-ink-2" aria-label="Steps taken">
          {t.tool_steps.map((s, i) => (
            <li key={i} className="flex gap-2">
              <span className="ms-code shrink-0">{s.name}</span>
              <span className="ws-wrap">{s.summary}</span>
            </li>
          ))}
        </ul>
      )}
      <ul className="m-0 list-none p-0">
        {t.sentences.map((s, i) => (
          <SentenceLine key={i} s={s} />
        ))}
      </ul>
      <p className="m-0 text-[13px] text-ink-3">
        Stored run · {t.model} · {t.recorded_at_utc.slice(0, 10)}
      </p>
    </div>
  )
}

function WorkflowView(p: Props & { def: WorkflowDef }) {
  const group = p.threads.workflows.find((w) => w.id === p.def.id)
  const items = group ? p.threads.threads.filter((t) => group.thread_ids.includes(t.id)) : []
  const agentic = p.def.id === 'weekly-investigator' || p.def.id === 'recall-sweep'
  return (
    <div>
      <h1 className="t-title-lg m-0">{p.def.title}</h1>
      <p className="mt-2 text-ink-2">{p.def.blurb}</p>
      {p.def.comingSoon && (
        <p className="ms-banner ms-banner--info mt-4">Coming soon. Nothing is stored here yet.</p>
      )}
      {agentic && (
        <p className="ms-banner ms-banner--info mt-4">
          {p.recordedRuns === 0
            ? (p.investigationNotes[0] ?? 'No recorded runs yet.')
            : `${p.recordedRuns} recorded runs.`}
        </p>
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
        Every answer here was written from stored public records (MAUDE reports, recalls, 510(k)s, PubMed,
        MHRA (UK) alerts) and checked sentence by sentence before it was shown. Pick a workflow to start.
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
    body = t ? <ThreadView t={t} /> : <p>That thread is not in the stored data.</p>
  }
  return (
    <main className="flex min-w-0 flex-1 flex-col bg-paper" aria-label="Chat">
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6 md:px-8 md:py-10">
        <div className="mx-auto max-w-3xl">{body}</div>
      </div>
      <Composer />
    </main>
  )
}
