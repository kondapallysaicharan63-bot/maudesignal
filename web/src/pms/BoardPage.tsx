// PMS board (PRD-19, /board): Flagged code | Why flagged | Status | Owner | Due date (MDR clock, advisory) | Decision /
// audit link. Rows are the real FDA alerts (AI device sweep + stored brief; never the simulated company) plus any code
// a person recorded a decision for. Status changes only by a named person, written to the browser audit trail first.
import { useMemo, useState } from 'react'
import type { AlertDetail } from '../alerts'
import type { WorkspaceData } from '../types'
import { realDetails } from '../v2/realAlerts'
import { LOCAL_NOTE, type AuditEntry } from './audit'
import { boardRows, BoardError, changeStatus, NOT_A_QMS, STATUS_LABELS, TRANSITIONS, type BoardRow, type Status } from './board'
import { buildLine } from './build'
import { DataAsOfBanner, storedAsOf } from './DataAsOf'
import { EvidencePackPanel } from './EvidencePackPanel'
import { DECISIONS, packFromAlert, whyFlagged, type Decision } from './pack'
import { useAudit } from './useAudit'

const BTN = { minHeight: 44 }

function StatusForm({ row, onDone }: { row: BoardRow; onDone: () => void }) {
  const next = TRANSITIONS[row.status]
  const [to, setTo] = useState<Status>(next[0])
  const [actor, setActor] = useState('')
  const [owner, setOwner] = useState(row.owner ?? '')
  const [awareness, setAwareness] = useState('')
  const [fiveDay, setFiveDay] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const id = (k: string) => `bd-${row.code}-${k}`
  const submit = async () => {
    setBusy(true)
    setErr(null)
    try {
      await changeStatus({ code: row.code, why: row.why, current: row.status, to, actor, owner: owner || undefined, awareness: awareness || undefined, fiveDay })
      setActor('')
      onDone()
    } catch (e) {
      setErr(e instanceof BoardError ? e.message : 'The change could not be recorded.')
    }
    setBusy(false)
  }
  return (
    <form
      className="ms2-pms-form"
      aria-label={`Change status of ${row.code}`}
      onSubmit={(e) => {
        e.preventDefault()
        void submit()
      }}
      data-testid={`board-form-${row.code}`}
    >
      <div className="ms2-pms-field">
        <label className="ms2-inv-label" htmlFor={id('to')}>
          Move to
        </label>
        <select id={id('to')} className="ms2-inv-input" style={BTN} value={to} onChange={(e) => setTo(e.target.value as Status)} data-testid={`board-to-${row.code}`}>
          {next.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABELS[s]}
            </option>
          ))}
        </select>
      </div>
      <div className="ms2-pms-field">
        <label className="ms2-inv-label" htmlFor={id('actor')}>
          Your name
        </label>
        <input id={id('actor')} className="ms2-inv-input" style={BTN} value={actor} onChange={(e) => setActor(e.target.value)} autoComplete="name" data-testid={`board-actor-${row.code}`} />
      </div>
      <div className="ms2-pms-field">
        <label className="ms2-inv-label" htmlFor={id('owner')}>
          Owner
        </label>
        <input id={id('owner')} className="ms2-inv-input" style={BTN} value={owner} onChange={(e) => setOwner(e.target.value)} data-testid={`board-owner-${row.code}`} />
      </div>
      <div className="ms2-pms-field">
        <label className="ms2-inv-label" htmlFor={id('aware')}>
          Awareness date (for the advisory MDR clock)
        </label>
        <input id={id('aware')} type="date" className="ms2-inv-input" style={BTN} value={awareness} onChange={(e) => setAwareness(e.target.value)} data-testid={`board-aware-${row.code}`} />
      </div>
      <label className="ms2-pms-radio" style={BTN}>
        <input type="checkbox" checked={fiveDay} onChange={(e) => setFiveDay(e.target.checked)} /> 5-work-day clock (21 CFR 803.53)
      </label>
      <button type="submit" className="ms-btn ms-btn--primary" style={BTN} disabled={busy} data-testid={`board-submit-${row.code}`}>
        Record status change
      </button>
      {err && (
        <p role="alert" className="ms-banner ms-banner--err m-0" data-testid={`board-error-${row.code}`}>
          {err}
        </p>
      )}
    </form>
  )
}

export function flaggedFromData(data: Pick<WorkspaceData, 'alerts'>): { code: string; why: string; alert: AlertDetail }[] {
  const out: { code: string; why: string; alert: AlertDetail }[] = []
  for (const a of realDetails(data)) if (a.rule && !out.some((o) => o.code === a.product_code)) out.push({ code: a.product_code, why: whyFlagged(a), alert: a })
  return out
}

export function AuditList({ entries, ok, firstBad }: { entries: AuditEntry[]; ok: boolean | null; firstBad: number | null }) {
  return (
    <section className="ms2-card mt-6" aria-labelledby="local-audit-h" data-testid="local-audit">
      <h2 id="local-audit-h" className="ms2-h2">
        This browser's audit trail
      </h2>
      <p className="m-0 mt-1" data-testid="local-audit-status">
        {ok === null ? (
          'Checking the chain…'
        ) : ok ? (
          <span className="ms2-ok">Chain verified: {entries.length} entr{entries.length === 1 ? 'y' : 'ies'}, every SHA-256 hash recomputed.</span>
        ) : (
          <span className="ms2-bad">Chain broken at entry #{firstBad}. An entry was changed after it was written.</span>
        )}
      </p>
      <p className="ms2-inv-meta m-0">{LOCAL_NOTE}</p>
      {entries.length > 0 && (
        <div className="ms2-inv-scroll mt-2">
          <table className="ms2-table" data-testid="local-audit-table">
            <caption className="sr-only">Audit entries, oldest first</caption>
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">Time (UTC)</th>
                <th scope="col">Who</th>
                <th scope="col">Action</th>
                <th scope="col">About</th>
                <th scope="col">Hash</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.seq} id={`audit-${e.seq}`} data-testid="local-audit-row" data-action={e.action}>
                  <td className="ms-num">{e.seq}</td>
                  <td className="ms-num">{e.ts.slice(0, 19)}</td>
                  <td>{e.actor}</td>
                  <td>{e.action}</td>
                  <td className="ms-code">{e.entity_id}</td>
                  <td className="ms-code">{e.entry_hash.slice(0, 12)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export function BoardPage({ data, onInvestigate, onValidation }: { data: WorkspaceData; onInvestigate: () => void; onValidation?: () => void }) {
  const audit = useAudit()
  const flagged = useMemo(() => flaggedFromData(data), [data])
  const rows = useMemo(() => boardRows(flagged, audit.entries), [flagged, audit.entries])
  const [open, setOpen] = useState<string | null>(null)
  const [, setTick] = useState(0)
  const asOf = storedAsOf(data.manifest)
  return (
    <div data-testid="board-page">
      <header className="ms2-pagehead">
        <h1 className="ms2-h1">PMS board</h1>
        <p className="ms2-lead">Flagged FDA product codes, who owns them and what a person decided.</p>
      </header>
      <p className="ms-banner ms-banner--warn" role="note" data-testid="board-not-qms">
        <span>
          <strong>{NOT_A_QMS}</strong> Nothing is filed with FDA. CAPA need, reportability and recalls are decided by a named person in your own QMS.
        </span>
      </p>
      <DataAsOfBanner asOf={asOf} testid="board-asof" />
      <p className="ms2-inv-meta m-0">
        Rows: real FDA alerts only (AI device sweep and the stored brief); simulated devices are never on this board. Build {buildLine()}.{' '}
        {onValidation && (
          <button type="button" className="ms2-link" style={BTN} onClick={onValidation}>
            What is and is not validated
          </button>
        )}
      </p>
      <div className="ms2-inv-scroll mt-3">
        <table className="ms2-table ms2-board" data-testid="board-table">
          <caption className="sr-only">PMS board</caption>
          <thead>
            <tr>
              <th scope="col">Flagged code</th>
              <th scope="col">Why flagged</th>
              <th scope="col">Status</th>
              <th scope="col">Owner</th>
              <th scope="col">Due date (MDR clock, advisory)</th>
              <th scope="col">Decision / audit</th>
              <th scope="col">
                <span className="sr-only">Open</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.code} data-testid="board-row" data-code={r.code} data-status={r.status}>
                <th scope="row">
                  <span className="ms-code">{r.code}</span>
                </th>
                <td className="ws-wrap">{r.why}</td>
                <td data-testid={`board-status-${r.code}`}>
                  <span className="ms2-tag">{STATUS_LABELS[r.status]}</span>
                </td>
                <td>{r.owner ?? <span className="ms2-muted">—</span>}</td>
                <td>
                  {r.due ? (
                    <>
                      <span className="ms-num">{r.due}</span>
                      <span className="ms2-muted block text-[14px]">{r.due_basis}</span>
                    </>
                  ) : (
                    <span className="ms2-muted">no awareness date typed</span>
                  )}
                </td>
                <td>
                  {r.decision ? <>{DECISIONS[r.decision as Decision] ?? r.decision} · </> : null}
                  {r.audit_seq ? (
                    <a className="ms2-a" href={`#audit-${r.audit_seq}`} data-testid={`board-audit-${r.code}`}>
                      audit #{r.audit_seq}
                    </a>
                  ) : (
                    <span className="ms2-muted">no entry yet</span>
                  )}
                </td>
                <td>
                  <button type="button" className="ms-btn ms-btn--sm" style={BTN} aria-expanded={open === r.code} onClick={() => setOpen((o) => (o === r.code ? null : r.code))} data-testid={`board-open-${r.code}`}>
                    {open === r.code ? 'Close' : 'Review'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length === 0 && <p className="ms2-muted">No real FDA alert is stored.</p>}
      {open &&
        (() => {
          const r = rows.find((x) => x.code === open)
          const f = flagged.find((x) => x.code === open)
          if (!r) return null
          return (
            <div className="mt-4 space-y-4" data-testid="board-detail">
              <section className="ms2-card" aria-label={`Status of ${r.code}`}>
                <h2 className="ms2-h2">
                  {r.code} · <span data-testid="board-detail-status">{STATUS_LABELS[r.status]}</span>
                </h2>
                <StatusForm key={`${r.code}-${r.status}-${r.audit_seq}`} row={r} onDone={() => setTick((t) => t + 1)} />
              </section>
              {f && <EvidencePackPanel pack={packFromAlert(f.alert, storedAsOf(data.manifest))} />}
              <button type="button" className="ms2-link" style={BTN} onClick={onInvestigate}>
                Investigate a complaint for another code →
              </button>
            </div>
          )
        })()}
      <AuditList entries={audit.entries} ok={audit.ok} firstBad={audit.firstBad} />
    </div>
  )
}
