// Web research shown under an answer, only when the server sent it. These are outside pages: never FDA records, never
// checked by the claim gate, and labelled so. "Save to audit" keeps one item in the audit trail (the server route is built
// by another track; when it answers 404 the buttons are hidden).
import { useState } from 'react'
import { RESEARCH_LABEL, type ResearchBlock, type ResearchItem, type SaveOutcome } from '../live/api'

type ItemState = 'idle' | 'saving' | 'saved' | 'failed'

export function ResearchSection({ block, onSave }: { block: ResearchBlock; onSave?: (item: ResearchItem) => Promise<SaveOutcome> }) {
  const [state, setState] = useState<Record<string, ItemState>>({})
  const [saveMissing, setSaveMissing] = useState(!onSave)
  const save = async (item: ResearchItem) => {
    if (!onSave) return
    setState((s) => ({ ...s, [item.url]: 'saving' }))
    const out = await onSave(item)
    if (out === 'unsupported') setSaveMissing(true)
    setState((s) => ({ ...s, [item.url]: out === 'saved' ? 'saved' : out === 'failed' ? 'failed' : 'idle' }))
  }
  return (
    <section className="mt-3 rounded-md border border-rule bg-surface p-3" aria-label={RESEARCH_LABEL} data-testid="research" data-status={block.status}>
      <h3 className="m-0 text-[16px] font-semibold text-ink" data-testid="research-label">
        {RESEARCH_LABEL}
      </h3>
      {block.items.length === 0 ? (
        <p className="m-0 mt-1 text-[16px] text-ink-2" data-testid="research-empty">
          No web pages were found{block.status && block.status !== 'ok' ? ` (${block.status.replace(/_/g, ' ')})` : ''}.
        </p>
      ) : (
        <ul className="m-0 mt-1 list-none p-0">
          {block.items.map((it) => {
            const st = state[it.url] ?? 'idle'
            return (
              <li key={it.url} className="border-t border-rule py-2 first:border-t-0" data-testid="research-item">
                <a href={it.url} target="_blank" rel="noopener noreferrer" className="ws-wrap font-semibold text-accent underline">
                  {it.title}
                </a>
                <p className="m-0 mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[15px] text-ink-2">
                  {it.date && <span data-testid="research-date">{it.date}</span>}
                  {it.source && <span data-testid="research-source">{it.source}</span>}
                  {!saveMissing &&
                    (st === 'saved' ? (
                      <span className="font-semibold text-success" data-testid="research-saved">
                        Saved
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="ms-btn ms-btn--secondary ms-btn--sm !min-h-11"
                        onClick={() => void save(it)}
                        disabled={st === 'saving'}
                        aria-label={`Save to audit: ${it.title}`}
                        data-testid="research-save"
                      >
                        {st === 'saving' ? 'Saving…' : st === 'failed' ? 'Not saved — try again' : 'Save to audit'}
                      </button>
                    ))}
                </p>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
