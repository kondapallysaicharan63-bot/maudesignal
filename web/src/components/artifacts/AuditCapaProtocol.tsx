import { useState } from 'react'
import { approveLocally, shortHash, type CapaDraft, type CapaLocalState } from '../../artifacts'
import type { Audit, AuditRun, Evidence, ProtocolStep } from '../../types'
import { Empty, Pill, Segmented } from './common'

function RunView({ run, open }: { run: AuditRun; open: boolean }) {
  return (
    <details open={open} className="border-t border-rule">
      <summary className="flex min-h-11 cursor-pointer flex-wrap items-center justify-between gap-2 py-2">
        <span className="ms-code" style={{ fontSize: 14 }}>
          {run.run_label}
        </span>
        <span className="flex items-center gap-2">
          <span className="text-[14px] text-ink-3">{run.entries.length} entries</span>
          {run.chain_ok ? (
            <Pill tone="ok">Hash chain verified ✓</Pill>
          ) : (
            <Pill tone="bad">Chain broken at entry {run.first_bad_seq ?? '?'}</Pill>
          )}
        </span>
      </summary>
      <ol className="m-0 list-none p-0 pb-2">
        {run.entries.map((e) => (
          <li key={e.seq} className="border-l-2 border-rule py-1 pl-3">
            <p className="ws-wrap m-0 text-[15px]">
              <span className="ms-num text-ink-3">#{e.seq}</span> {e.action}{' '}
              <span className="ms-code">{e.entity_id}</span>
            </p>
            <p className="ws-wrap m-0 text-[14px] text-ink-3">
              {e.actor} · {e.ts}
            </p>
            <p className="ms-code m-0 break-all">
              hash {shortHash(e.entry_hash)} ← previous {e.prev_hash === 'GENESIS' ? 'GENESIS' : shortHash(e.prev_hash)}
            </p>
          </li>
        ))}
      </ol>
    </details>
  )
}

export function AuditTab({ audit, activeRun, generatedUtc }: { audit: Audit; activeRun: string | null; generatedUtc: string }) {
  const runs = [...audit.runs].sort((a, b) => Number(b.run_label === activeRun) - Number(a.run_label === activeRun))
  return (
    <article>
      <p className="ms-kicker">Audit trail</p>
      <p className="ws-wrap mt-2 text-ink-2">
        Every answer and draft is logged in a chain: each entry carries the hash of the one before it. The chain was
        re-computed from the stored entries when this data was exported ({generatedUtc}); "verified" means every link
        matched.
      </p>
      <div className="mt-3">
        {runs.length === 0 ? (
          <Empty title="No audit runs stored" />
        ) : (
          runs.map((r) => <RunView key={r.run_label} run={r} open={r.run_label === activeRun} />)
        )}
      </div>
      {audit.notes.map((n) => (
        <p key={n} className="ws-wrap mt-2 text-[14px] text-ink-3">
          {n}
        </p>
      ))}
    </article>
  )
}

type Role = 'viewer' | 'reviewer'

function CapaCard({
  d,
  role,
  state,
  onState,
  evidence,
}: {
  d: CapaDraft
  role: Role
  state: CapaLocalState
  onState: (s: CapaLocalState) => void
  evidence: Evidence
}) {
  const [name, setName] = useState('')
  return (
    <section className="rounded-md border border-rule bg-surface p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="ms-code">{d.id}</span>
        {state.status === 'draft' ? (
          <Pill tone="warn">Status: draft</Pill>
        ) : (
          <Pill tone="ok">Status: approved (demo: not saved)</Pill>
        )}
      </div>
      <h3 className="ws-wrap m-0 mt-2 text-[17px] font-semibold">{d.title}</h3>
      <p className="ws-wrap mt-1 text-ink-2">{d.problem}</p>
      <p className="m-0 text-[14px] text-ink-3">Drafted text, not checked claim by claim.</p>
      <p className="m-0 text-[14px] text-ink-3">
        Product code <span className="ms-code">{d.productCode}</span> · drafted {d.ts} by {d.actor}
      </p>
      <h4 className="ms-kicker mt-3">Evidence · {d.reportIds.length} reports</h4>
      <ul className="m-0 mt-1 list-none p-0">
        {d.reportIds.map((id) => {
          const r = evidence.reports[id]
          return (
            <li key={id} className="py-0.5">
              {r ? (
                <a className="ms-code text-accent underline" href={r.maude_url} target="_blank" rel="noreferrer">
                  {id}
                </a>
              ) : (
                <span className="ms-code">{id}</span>
              )}
            </li>
          )
        })}
      </ul>
      {state.status === 'approved' && (
        <div className="mt-3">
          <p className="ms-banner ms-banner--warn m-0">
            Approved by {state.by}. Demo: not saved. This exists only in this browser tab; reloading resets it, and
            nothing is filed with FDA.
          </p>
          {role === 'reviewer' && (
            <button className="ms-chip mt-2 min-h-10" onClick={() => onState({ status: 'draft' })}>
              Set back to draft
            </button>
          )}
        </div>
      )}
      {state.status === 'draft' && role === 'reviewer' && (
        <form
          className="mt-3"
          onSubmit={(e) => {
            e.preventDefault()
            const next = approveLocally(name)
            if (next) onState(next)
          }}
        >
          <label className="block text-[14px] text-ink-3" htmlFor={`rev-${d.id}`}>
            Your name (a named person approves)
          </label>
          <input
            id={`rev-${d.id}`}
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoComplete="off"
            className="mt-1 min-h-10 w-full rounded-xs border border-rule bg-paper px-2 text-ink"
          />
          <button
            type="submit"
            disabled={!name.trim()}
            className="mt-2 min-h-10 rounded-xs bg-inverse px-4 text-on-inverse disabled:opacity-50"
          >
            Approve (demo: not saved)
          </button>
        </form>
      )}
    </section>
  )
}

export function CapaTab({
  drafts,
  evidence,
}: {
  drafts: CapaDraft[]
  evidence: Evidence
}) {
  const [role, setRole] = useState<Role>('viewer')
  // Local UI state only: never written to storage or sent anywhere.
  const [states, setStates] = useState<Record<string, CapaLocalState>>({})
  return (
    <article>
      <p className="ms-kicker">CAPA-need evidence</p>
      <p className="ws-wrap mt-2 text-ink-2">
        Drafts only. A person decides whether a corrective action is needed; nothing is filed with FDA.
      </p>
      <div className="mt-3">
        <Segmented
          label="Role"
          value={role}
          options={[
            { id: 'viewer', label: 'Viewer' },
            { id: 'reviewer', label: 'Human reviewer' },
          ]}
          onChange={setRole}
        />
      </div>
      {role === 'viewer' && (
        <p className="mt-2 text-[14px] text-ink-3">Approving is only offered to a human reviewer.</p>
      )}
      <div className="mt-3 grid gap-3">
        {drafts.length === 0 ? (
          <Empty title="No CAPA-need evidence in the stored runs" />
        ) : (
          drafts.map((d) => (
            <CapaCard
              key={d.id}
              d={d}
              role={role}
              evidence={evidence}
              state={states[d.id] ?? { status: 'draft' }}
              onState={(s) => setStates((cur) => ({ ...cur, [d.id]: s }))}
            />
          ))
        )}
      </div>
    </article>
  )
}

export function ProtocolTab({
  threadIds,
  threadId,
  onThread,
  steps,
  notes,
}: {
  threadIds: string[]
  threadId: string | null
  onThread: (id: string) => void
  steps: ProtocolStep[]
  notes: string[]
}) {
  return (
    <article>
      <p className="ms-kicker">Search protocol</p>
      <p className="ws-wrap mt-2 text-ink-2">
        What was searched for an answer: dataset, filters, dates and counts, so an auditor can repeat each search.
      </p>
      {threadIds.length > 0 && (
        <>
          <label className="mt-3 block text-[14px] text-ink-3" htmlFor="protocol-pick">
            Stored answer
          </label>
          <select
            id="protocol-pick"
            value={threadId ?? ''}
            onChange={(e) => onThread(e.target.value)}
            className="min-h-10 w-full rounded-xs border border-rule bg-surface px-2 text-ink"
          >
            {threadId === null || !threadIds.includes(threadId) ? <option value="">Choose an answer</option> : null}
            {threadIds.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </>
      )}
      {steps.length === 0 ? (
        <div className="mt-3 rounded-md border border-rule bg-sunk p-3">
          <Empty title="No search protocol stored for this answer">
            <p className="m-0">
              The protocol is built from the tool calls recorded with each answer. Until it exists for this one, nothing
              is shown here.
            </p>
            {notes.map((n) => (
              <p key={n} className="m-0 mt-1">
                {n}
              </p>
            ))}
          </Empty>
        </div>
      ) : (
        <ol className="m-0 mt-3 list-none p-0">
          {steps.map((s, i) => (
            <li key={i} className="border-t border-rule py-2">
              <p className="m-0">
                <span className="ms-num text-ink-3">{i + 1}.</span> <span className="ms-code" style={{ fontSize: 14 }}>{s.tool}</span>
              </p>
              <dl className="m-0 mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[15px]">
                <dt className="text-ink-3">Dataset</dt>
                <dd className="ws-wrap m-0">{s.dataset}</dd>
                <dt className="text-ink-3">Filters</dt>
                <dd className="ws-wrap m-0">
                  {Object.keys(s.filters).length === 0 ? 'none' : JSON.stringify(s.filters)}
                </dd>
                <dt className="text-ink-3">Dates</dt>
                <dd className="ms-num m-0">
                  {s.date_from && s.date_to ? `${s.date_from} to ${s.date_to}` : 'no date range'}
                </dd>
                <dt className="text-ink-3">Count</dt>
                <dd className="ms-num m-0">{s.count === null ? 'not recorded' : s.count}</dd>
                <dt className="text-ink-3">Run at</dt>
                <dd className="ms-num ws-wrap m-0">{s.run_at ?? 'not recorded'}</dd>
              </dl>
            </li>
          ))}
        </ol>
      )}
    </article>
  )
}
