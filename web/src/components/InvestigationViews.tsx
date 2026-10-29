import { Icon } from '../icons'
import type { Evidence, InvestigationKind, InvestigationRun, Thread } from '../types'
import { ThreadView } from './ThreadView'

export const KIND_LABEL: Record<InvestigationKind, string> = {
  'weekly-investigator': 'Weekly investigator',
  'recall-sweep': 'Recall sweep',
}

/** What started the run, as one line of text (the recorder may store text or a small object). */
export function triggerText(run: InvestigationRun): string {
  const t = run.trigger
  if (typeof t === 'string' && t.trim()) return t
  if (t && typeof t === 'object')
    return Object.entries(t)
      .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${typeof v === 'string' ? v : JSON.stringify(v)}`)
      .join(' · ')
  return `${KIND_LABEL[run.kind]} run for ${run.product_code}`
}

/** Recorded runs of one kind (investigations.json), newest first. Nothing is shown that was not recorded. */
export function RunList({
  kind,
  runs,
  notes,
  onRun,
}: {
  kind: InvestigationKind
  runs: InvestigationRun[]
  notes: string[]
  onRun: (id: string) => void
}) {
  const mine = runs
    .filter((r) => r.kind === kind)
    .sort((a, b) => b.recorded_at_utc.localeCompare(a.recorded_at_utc))
  return (
    <div>
      <h1 className="t-title-lg m-0">{KIND_LABEL[kind]}</h1>
      <p className="mt-2 text-ink-2">
        {mine.length} recorded {mine.length === 1 ? 'run' : 'runs'}. Each was run once by the model, every sentence was
        checked by the gate, and it is replayed here from the recording.
      </p>
      {notes.length > 0 && mine.length === 0 && <p className="ms-banner ms-banner--info mt-4">{notes[0]}</p>}
      <ul className="m-0 mt-4 list-none p-0">
        {mine.map((r) => (
          <li key={r.id}>
            <button className="ws-side-item items-start border-b border-rule" onClick={() => onRun(r.id)}>
              <span className="min-w-0">
                <span className="ms-code mr-2">{r.product_code}</span>
                <span className="ws-wrap">{triggerText(r)}</span>
                <span className="block text-[14px] text-ink-3">
                  Recorded {r.recorded_at_utc.slice(0, 10)} · {r.model}
                </span>
              </span>
              <Icon name="chevron" size={18} />
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** One recorded run: its steps and gated sentences (as a thread), then the groups it found. */
export function RunView({
  run,
  ev,
  onThread,
}: {
  run: InvestigationRun
  ev: Evidence
  onThread: (id: string) => void
}) {
  const asThread: Thread = {
    id: run.id,
    workflow: run.kind,
    question: triggerText(run),
    voice: null,
    recorded_at_utc: run.recorded_at_utc,
    model: run.model,
    tool_steps: run.tool_steps,
    sentences: run.sentences,
    first_pass: null,
    repaired: false,
  }
  return (
    <div className="space-y-5">
      <div>
        <p className="ms-kicker m-0">
          {KIND_LABEL[run.kind]} · <span className="ms-code">{run.product_code}</span>
        </p>
      </div>
      <ThreadView t={asThread} ev={ev} siblings={[]} onThread={onThread} />
      {run.groups.length > 0 && (
        <section aria-label="Groups">
          <h2 className="ms-kicker m-0">Reports grouped by kind of problem · {run.groups.length}</h2>
          <ul className="m-0 mt-2 list-none p-0">
            {run.groups.map((g) => (
              <li key={g.label} className="border-t border-rule py-2">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="ws-wrap font-semibold">{g.label}</span>
                  <span className="ms-num text-ink-2">{g.count} reports</span>
                </div>
                <p className="ws-wrap m-0 text-[14px] text-ink-3">
                  {g.report_ids.slice(0, 8).map((id, i) => {
                    const row = ev.reports[id]
                    return (
                      <span key={id}>
                        {i > 0 && ', '}
                        {row ? (
                          <a className="underline" href={row.maude_url} target="_blank" rel="noreferrer">
                            {id}
                          </a>
                        ) : (
                          id
                        )}
                      </span>
                    )
                  })}
                  {g.report_ids.length > 8 && ` and ${g.report_ids.length - 8} more`}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
