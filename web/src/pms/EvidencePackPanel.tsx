// The evidence pack a person reviews (PRD-20/21/25): reports NOT filed by a manufacturer first, the counts, reports
// and recalls, then the escalation checklist, risk inputs and recall check (each ends with a human decision), then
// Accept / Reject of the evidence and the Note to file with its exports. Every decision is written to the browser
// audit trail before anything changes on screen. Nothing is filed with FDA.
import { useState } from 'react'
import { appendAudit, LOCAL_NOTE, validName, type AuditEntry } from './audit'
import { BUILD_COMMIT, BUILD_VERSION } from './build'
import { asOfText, DataAsOfBanner } from './DataAsOf'
import {
  BLANK_FIELD,
  DECISIONS,
  DETECTABILITY_QUESTION,
  escalationChecklist,
  hasDecisionSentence,
  HUMAN_DECIDES,
  NOTE_LABEL,
  noteMarkdown,
  OCCURRENCE_NOTE,
  recallCheck,
  reportsCsv,
  severityMix,
  type Decision,
  type EvidencePack,
  type Note,
} from './pack'
import { download, markdownParas, pdfText, renderPdf } from './pdf'
import { useAudit } from './useAudit'

const BTN = { minHeight: 44 }

function Field({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <div className="ms2-pms-field">
      <label htmlFor={id} className="ms2-inv-label">
        {label}
      </label>
      {children}
    </div>
  )
}

export function packFiles(note: Note, audit: AuditEntry[]): { name: string; data: string | Uint8Array; type: string }[] {
  const md = noteMarkdown(note)
  const stamp = note.decided_utc.slice(0, 10).replace(/-/g, '')
  const base = `${note.pack.product_code}-${stamp}`
  const auditDoc = {
    build: { version: note.version, commit: note.commit },
    data_as_of: asOfText(note.pack.as_of),
    company_complaint_or_capa_number: '',
    note: LOCAL_NOTE,
    entries: audit,
  }
  return [
    { name: `${base}-note-to-file.md`, data: md, type: 'text/markdown;charset=utf-8' },
    { name: `${base}-evidence-pack.pdf`, data: renderPdf(`Note to file ${note.pack.product_code}`, markdownParas(md), `${NOTE_LABEL} MaudeSignal ${note.version} (${note.commit.slice(0, 12)})`), type: 'application/pdf' },
    { name: `${base}-reports.csv`, data: reportsCsv(note), type: 'text/csv;charset=utf-8' },
    { name: `${base}-audit.json`, data: JSON.stringify(auditDoc, null, 2), type: 'application/json' },
  ]
}

export function EvidencePackPanel({ pack, onDecided }: { pack: EvidencePack; onDecided?: (n: Note) => void }) {
  const audit = useAudit()
  const [reviewer, setReviewer] = useState('')
  const [reason, setReason] = useState('')
  const [packErr, setPackErr] = useState<string | null>(null)
  const [decision, setDecision] = useState<Decision>('note_to_file')
  const [rationale, setRationale] = useState('')
  const [approver, setApprover] = useState('')
  const [noteErr, setNoteErr] = useState<string | null>(null)
  const [note, setNote] = useState<Note | null>(null)
  const [busy, setBusy] = useState(false)
  const entity = `board:${pack.product_code}`
  const packEntries = audit.entries.filter((e) => e.entity_id === entity && (e.action === 'pack_accept' || e.action === 'pack_reject'))
  const lastPack = packEntries[packEntries.length - 1]
  const mix = severityMix(pack)
  const rc = recallCheck(pack)

  const decidePack = async (accept: boolean) => {
    if (!validName(reviewer)) return setPackErr('Type your name: only a named person can accept or reject evidence.')
    if (reason.trim().length < 5) return setPackErr('Type a short reason (5 characters or more).')
    setPackErr(null)
    setBusy(true)
    await appendAudit({
      actor: reviewer.trim(),
      action: accept ? 'pack_accept' : 'pack_reject',
      entity_id: entity,
      payload: { pack: pack.id, reason: reason.trim(), report_ids: pack.reports.map((r) => r.report_id), data_as_of: pack.as_of.latest ?? '' },
    })
    setBusy(false)
  }
  const recordNote = async () => {
    if (!validName(approver)) return setNoteErr('Type the approver name: only a named person can record a decision.')
    if (rationale.trim().length < 10) return setNoteErr('Type a rationale (10 characters or more).')
    if (hasDecisionSentence(pack.why)) return setNoteErr('The evidence text contains a tool-made decision sentence; it cannot be exported.')
    setNoteErr(null)
    setBusy(true)
    const row = await appendAudit({
      actor: approver.trim(),
      action: 'note_to_file',
      entity_id: entity,
      payload: {
        decision,
        rationale: rationale.trim().slice(0, 2000),
        report_ids: pack.reports.map((r) => r.report_id),
        recall_ids: pack.recalls.map((r) => r.id),
        data_as_of: pack.as_of.latest ?? '',
        build: { version: BUILD_VERSION, commit: BUILD_COMMIT },
      },
    })
    const n: Note = {
      pack,
      decision,
      rationale: rationale.trim(),
      approver: approver.trim(),
      decided_utc: `${row.ts.slice(0, 19)}Z`,
      audit_seq: row.seq,
      version: BUILD_VERSION,
      commit: BUILD_COMMIT,
    }
    setNote(n)
    setBusy(false)
    onDecided?.(n)
  }
  const files = note ? packFiles(note, audit.entries) : []
  const md = files[0]?.data as string | undefined

  return (
    <section className="ms2-card ms2-pms" aria-labelledby={`pack-h-${pack.product_code}`} data-testid="evidence-pack">
      <h2 id={`pack-h-${pack.product_code}`} className="ms2-h2">
        Evidence pack · <span className="ms-code">{pack.product_code}</span>
        {pack.device_type ? <span className="ms2-muted"> · {pack.device_type}</span> : null}
      </h2>
      <DataAsOfBanner asOf={pack.as_of} testid="pack-asof" />
      <p className="m-0 mt-2" data-testid="pack-why">
        {pack.why}
      </p>

      <h3 className="ms2-h3 mt-4">Reports NOT filed by a manufacturer — check these against your complaint log</h3>
      {pack.non_manufacturer.length > 0 ? (
        <ul className="ms2-inv-plain" data-testid="pack-nonmfr">
          {pack.non_manufacturer.map((r) => (
            <li key={r.report_id}>
              <span className="ms-num">{r.report_id}</span> · {r.date_received ?? 'date not stated'} · {r.source} ·{' '}
              <a className="ms2-a" href={r.url} target="_blank" rel="noreferrer">
                FDA record
              </a>
            </li>
          ))}
        </ul>
      ) : (
        <p className="ms2-inv-meta m-0" data-testid="pack-nonmfr-none">
          {pack.origin === 'alert' ? 'Filer type is not listed per report in this alert; see the who-filed counts on Signals.' : 'None listed in this answer.'}
        </p>
      )}

      <h3 className="ms2-h3 mt-4">Counts</h3>
      <ul className="ms2-inv-plain" data-testid="pack-counts">
        {pack.counts.map((c) => (
          <li key={c.label}>
            {c.label}:{' '}
            {c.url ? (
              <a className="ms2-a ms-num" href={c.url} target="_blank" rel="noreferrer">
                {c.value}
              </a>
            ) : (
              <span className="ms-num">{c.value}</span>
            )}
          </li>
        ))}
      </ul>

      <details className="mt-3">
        <summary className="ms2-smalllink cursor-pointer" style={BTN}>
          Reports ({pack.reports.length}) and recalls ({pack.recalls.length}
          {pack.recalls_total != null && pack.recalls_total > pack.recalls.length ? ` of ${pack.recalls_total}` : ''})
        </summary>
        <ul className="ms2-inv-plain" data-testid="pack-reports">
          {pack.reports.map((r) => (
            <li key={r.report_id}>
              <span className="ms-num">{r.report_id}</span> · {r.date_received ?? 'date not stated'} · {r.event_type ?? 'event type not in this answer'} ·{' '}
              <a className="ms2-a" href={r.url} target="_blank" rel="noreferrer">
                FDA record
              </a>
            </li>
          ))}
        </ul>
        <ul className="ms2-inv-plain mt-2" data-testid="pack-recalls">
          {pack.recalls.map((r) => (
            <li key={r.id}>
              <span className="ms-num">{r.id}</span> · {r.date ?? 'date not stated'} · {r.reason ?? 'reason not stored'}
              {r.url && (
                <>
                  {' · '}
                  <a className="ms2-a" href={r.url} target="_blank" rel="noreferrer">
                    FDA record
                  </a>
                </>
              )}
            </li>
          ))}
        </ul>
      </details>

      <h3 className="ms2-h3 mt-4">Escalation checklist — never filed by this tool</h3>
      <ol className="ms2-pms-check" data-testid="pack-escalation">
        {escalationChecklist(pack).map((c) => (
          <li key={c.item}>
            <strong>{c.item}</strong> <span className="ms2-muted">({c.basis})</span>
            <br />
            {c.question} <span className="ms2-muted">Evidence: {c.evidence.join(', ') || 'none listed'}.</span>
            <br />
            <span className="ms2-tag">{HUMAN_DECIDES}</span>
          </li>
        ))}
      </ol>

      <h3 className="ms2-h3 mt-4">Risk inputs (ISO 14971 framing)</h3>
      <div data-testid="pack-risk">
        {pack.event_types_known ? (
          <table className="ms2-table">
            <caption className="sr-only">Severity mix of the listed reports</caption>
            <thead>
              <tr>
                <th scope="col">Event type</th>
                <th scope="col" className="ms2-num">
                  Reports
                </th>
                <th scope="col" className="ms2-num">
                  Share of listed
                </th>
              </tr>
            </thead>
            <tbody>
              {mix.map((m) => (
                <tr key={m.event_type}>
                  <th scope="row">{m.event_type}</th>
                  <td className="ms2-num">
                    {m.count} of {m.of}
                  </td>
                  <td className="ms2-num">{m.share === null ? 'n/a' : `${Math.round(m.share * 100)}%`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="ms2-inv-meta m-0">Event types are not in this answer; open the openFDA queries for the Death / Injury / Malfunction split.</p>
        )}
        <p className="ms2-inv-meta m-0 mt-2">Occurrence: {OCCURRENCE_NOTE}</p>
        <p className="m-0 mt-1">{DETECTABILITY_QUESTION}</p>
        <p className="m-0 mt-1">
          <span className="ms2-tag">{HUMAN_DECIDES}</span> No risk rating is computed by this tool.
        </p>
      </div>

      <h3 className="ms2-h3 mt-4">Recall check (question, not answer)</h3>
      <div data-testid="pack-recallcheck">
        <p className="m-0">{rc.summary}</p>
        <p className="m-0 mt-1">
          <strong>Does this meet your recall procedure?</strong> <span className="ms2-tag">{HUMAN_DECIDES}</span>
        </p>
      </div>

      <h3 className="ms2-h3 mt-5">Accept or reject this evidence</h3>
      <p className="ms2-inv-meta m-0">Accepting says the evidence is complete enough to decide on; it does not decide CAPA need, reportability or a recall.</p>
      <div className="ms2-pms-form">
        <Field id={`rev-${pack.product_code}`} label="Your name">
          <input id={`rev-${pack.product_code}`} className="ms2-inv-input" value={reviewer} onChange={(e) => setReviewer(e.target.value)} autoComplete="name" data-testid="pack-reviewer" />
        </Field>
        <Field id={`why-${pack.product_code}`} label="Reason">
          <input id={`why-${pack.product_code}`} className="ms2-inv-input" value={reason} onChange={(e) => setReason(e.target.value)} data-testid="pack-reason" />
        </Field>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="ms-btn" style={BTN} disabled={busy} onClick={() => void decidePack(true)} data-testid="pack-accept">
            Accept evidence
          </button>
          <button type="button" className="ms-btn" style={BTN} disabled={busy} onClick={() => void decidePack(false)} data-testid="pack-reject">
            Reject evidence
          </button>
        </div>
      </div>
      {packErr && (
        <p role="alert" className="ms-banner ms-banner--err m-0 mt-2" data-testid="pack-error">
          {packErr}
        </p>
      )}
      {lastPack && (
        <p role="status" className="m-0 mt-2" data-testid="pack-decided">
          {lastPack.action === 'pack_accept' ? 'Evidence accepted' : 'Evidence rejected'} by <strong>{lastPack.actor}</strong> · audit entry #
          <span className="ms-num" data-testid="pack-decided-seq">
            {lastPack.seq}
          </span>{' '}
          · {lastPack.ts.slice(0, 19)}Z
        </p>
      )}

      <h3 className="ms2-h3 mt-5">Note to file</h3>
      <p className="m-0">
        <strong>{NOTE_LABEL}</strong>
      </p>
      <fieldset className="ms2-pms-fieldset mt-2">
        <legend className="ms2-inv-label">Decision (yours)</legend>
        {(Object.keys(DECISIONS) as Decision[]).map((d) => (
          <label key={d} className="ms2-pms-radio" style={BTN}>
            <input type="radio" name={`dec-${pack.product_code}`} value={d} checked={decision === d} onChange={() => setDecision(d)} data-testid={`note-decision-${d}`} /> {DECISIONS[d]}
          </label>
        ))}
      </fieldset>
      <div className="ms2-pms-form">
        <Field id={`rat-${pack.product_code}`} label="Rationale (typed by you)">
          <textarea id={`rat-${pack.product_code}`} className="ms2-inv-input" rows={3} value={rationale} onChange={(e) => setRationale(e.target.value)} data-testid="note-rationale" />
        </Field>
        <Field id={`app-${pack.product_code}`} label="Approver name">
          <input id={`app-${pack.product_code}`} className="ms2-inv-input" value={approver} onChange={(e) => setApprover(e.target.value)} autoComplete="name" data-testid="note-approver" />
        </Field>
        <p className="ms2-inv-meta m-0">
          Company complaint / CAPA number: <span className="ms-num">{BLANK_FIELD}</span> — left blank for your QMS; never filled in by this tool.
        </p>
        <button type="button" className="ms-btn" style={BTN} disabled={busy} onClick={() => void recordNote()} data-testid="note-record">
          Record decision and export note to file
        </button>
      </div>
      {noteErr && (
        <p role="alert" className="ms-banner ms-banner--err m-0 mt-2" data-testid="note-error">
          {noteErr}
        </p>
      )}
      {note && md && (
        <div className="mt-3" data-testid="note-export">
          <p role="status" className="m-0">
            Recorded by <strong>{note.approver}</strong> · audit entry #<span className="ms-num" data-testid="note-seq">{note.audit_seq}</span> · {note.decided_utc}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {files.map((f) => (
              <button key={f.name} type="button" className="ms-btn" style={BTN} onClick={() => download(f.name, f.data, f.type)} data-testid={`export-${f.name.split('-').pop()?.split('.')[0]}`}>
                Download {f.name.split('.').pop()?.toUpperCase()}
                {f.name.endsWith('-audit.json') ? ' (audit)' : f.name.endsWith('.csv') ? ' (reports)' : ''}
              </button>
            ))}
          </div>
          <pre className="ms2-inv-evidence is-open mt-2" tabIndex={0} aria-label="Note to file (Markdown)" data-testid="note-preview">
            {md}
          </pre>
          <p className="ms2-inv-meta m-0" data-testid="note-pdf-check">
            PDF: {pdfText(files[1].data as Uint8Array).includes(`Approver: ${note.approver}`) ? 'contains the approver and decision' : 'check failed'} · {LOCAL_NOTE}
          </p>
        </div>
      )}
      <p className="ms2-inv-meta m-0 mt-3">{LOCAL_NOTE} The browser audit uses the same SHA-256 chain as the Python trail, so an export re-verifies there.</p>
    </section>
  )
}
