// "Make it yours": the bar above Our devices (switch between the simulated company and yours) and the editor where a person
// types a company name and adds devices by product code, K-number, CSV or a confirmed label-photo match. Their data is kept in
// this browser only; nothing here is sent anywhere except a single K-number to the look-up tool when an API address and a
// demo key exist.
import { useId, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { fetchConnect } from '../connect'
import {
  checkCode,
  exportJson,
  isKNumber,
  isProductCode,
  MINE_BANNER,
  lookupKNumber,
  MAX_JSON_BYTES,
  MEMORY_NOTE,
  normalizeK,
  parseCsv,
  UNKNOWN_CODE_NOTE,
  validateImport,
  type CsvResult,
  type KLookup,
  type MineCompany,
  type NewDevice,
} from '../myCompany'
import { useMine, type MineApi } from '../useMyCompany'
import { Icon } from '../icons'
import type { Candidate } from '../live/api'
import { CameraPanel } from './CameraPanel'

const INPUT = 'mt-1 block h-11 w-full max-w-sm rounded-xs border border-rule-strong bg-surface px-3 text-[17px] text-ink placeholder:text-ink-2'
const BTN2 = 'ms-btn ms-btn--secondary'

function Field({ label, children, hint }: { label: string; children: (id: string) => ReactNode; hint?: string }) {
  const id = useId()
  return (
    <div className="mt-3">
      <label htmlFor={id} className="block text-[17px] text-ink">
        {label}
      </label>
      {children(id)}
      {hint && <p className="m-0 mt-1 text-[15px] text-ink-2">{hint}</p>}
    </div>
  )
}

/** The two-way switch and the Make it yours button, above the Our devices table. */
export function MineBar({ onOpen, open }: { onOpen: () => void; open: boolean }) {
  const mine = useMine()
  if (!mine) return null
  const seg = (on: boolean) =>
    [
      'min-h-11 px-3 text-[17px] leading-tight border',
      on ? 'border-ink bg-inverse font-semibold text-on-inverse' : 'border-rule-strong bg-surface text-ink hover:bg-sunk',
    ].join(' ')
  return (
    <div className="space-y-2" data-testid="mine-bar">
      <div role="group" aria-label="Which company to show" className="flex flex-wrap gap-2">
        <button type="button" className={seg(mine.mode === 'demo')} aria-pressed={mine.mode === 'demo'} onClick={() => mine.setMode('demo')} data-testid="mode-demo">
          Demo MedTech Co. (simulated)
        </button>
        <button type="button" className={seg(mine.mode === 'mine')} aria-pressed={mine.mode === 'mine'} onClick={() => mine.setMode('mine')} data-testid="mode-mine">
          Your company
        </button>
        <button
          type="button"
          className="ms-btn ws-btn-primary"
          style={{ height: 44 }}
          aria-expanded={open}
          aria-controls="make-it-yours"
          onClick={onOpen}
          data-testid="make-it-yours"
        >
          <Icon name="plus" size={18} /> Make it yours
        </button>
      </div>
      {mine.mode === 'mine' && !mine.persisted && (
        <p className="ms-banner ms-banner--warn m-0" role="status" data-testid="memory-note">
          <span className="ws-wrap">{MEMORY_NOTE}</span>
        </p>
      )}
    </div>
  )
}

type Method = 'code' | 'k' | 'csv' | 'label'
const METHODS: { id: Method; label: string }[] = [
  { id: 'code', label: 'Product code' },
  { id: 'k', label: 'K-number' },
  { id: 'csv', label: 'CSV file' },
  { id: 'label', label: 'Label photo' },
]

function ByCode({ mine, onDone }: { mine: MineApi; onDone: (msg: string) => void }) {
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    const r = checkCode(code, mine.known)
    if (!r.ok) return setErr(r.error)
    setErr(null)
    mine.add([{ name: name.trim() || `Product code ${r.code}`, product_code: r.code, k_number: null, source: 'code', note: r.note }])
    setCode('')
    setName('')
    onDone(r.note ? `Added with a note: ${r.note}` : `Added ${r.code}.`)
  }
  return (
    <form onSubmit={submit} noValidate aria-label="Add by product code">
      <Field label="Product code (3 letters)" hint="For example LLZ. A code this site has no stored data for is accepted with a note.">
        {(id) => (
          <input
            id={id}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/[^a-zA-Z]/g, '').slice(0, 3))}
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            className={`${INPUT} w-44 uppercase`}
            data-testid="in-code"
            aria-invalid={err ? true : undefined}
            aria-describedby={err ? 'code-err' : undefined}
          />
        )}
      </Field>
      <Field label="Device name (optional)">
        {(id) => <input id={id} value={name} maxLength={120} onChange={(e) => setName(e.target.value)} className={INPUT} data-testid="in-code-name" />}
      </Field>
      {err && (
        <p id="code-err" role="alert" className="ms-banner ms-banner--err mt-2" data-testid="code-error">
          <span className="ws-wrap">{err}</span>
        </p>
      )}
      <button type="submit" className="ms-btn ws-btn-primary mt-3" style={{ height: 44 }} data-testid="add-code">
        Add device
      </button>
    </form>
  )
}

function ByK({ mine, onDone }: { mine: MineApi; onDone: (msg: string) => void }) {
  const [k, setK] = useState('')
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const kn = normalizeK(k)
    if (!isKNumber(kn)) return setErr('A K-number is the letter K and 6 digits, for example K123456.')
    const pc = code.trim().toUpperCase()
    if (pc && !isProductCode(pc)) return setErr('A product code is exactly 3 letters, or leave it empty.')
    setErr(null)
    setBusy(true)
    let found: KLookup | null = null
    if (mine.apiBase) {
      const info = await fetchConnect(mine.apiBase)
      found = await lookupKNumber(kn, mine.apiBase, info.demo_key ? { header: info.key_header, value: info.demo_key } : null)
    }
    setBusy(false)
    const product = pc || found?.product_code || null
    const codeNote = product && !mine.known.has(product) ? UNKNOWN_CODE_NOTE : null
    const dev: NewDevice = {
      name: name.trim() || found?.device_name || `Device ${kn}`,
      product_code: product,
      k_number: kn,
      source: 'k_number',
      note: codeNote,
      k_check: found?.text ?? 'not checked yet',
    }
    mine.add([dev])
    setK('')
    setName('')
    setCode('')
    onDone(found?.checked ? `Added ${kn}: ${found.text}.` : `Added ${kn}. K-number: not checked yet.`)
  }
  return (
    <form onSubmit={(e) => void submit(e)} noValidate aria-label="Add by K-number">
      <Field
        label="K-number"
        hint={mine.apiBase ? 'Looked up once through the MaudeSignal API (only the K-number is sent). If that is not available it is stored as "not checked yet".' : 'Stored as "not checked yet": this build is not connected to the API.'}
      >
        {(id) => (
          <input
            id={id}
            value={k}
            onChange={(e) => setK(e.target.value.replace(/[^a-zA-Z0-9]/g, '').slice(0, 7))}
            autoComplete="off"
            spellCheck={false}
            className={`${INPUT} w-44 uppercase`}
            data-testid="in-k"
            aria-invalid={err ? true : undefined}
          />
        )}
      </Field>
      <Field label="Device name (optional)">
        {(id) => <input id={id} value={name} maxLength={120} onChange={(e) => setName(e.target.value)} className={INPUT} data-testid="in-k-name" />}
      </Field>
      <Field label="Product code (optional, 3 letters)">
        {(id) => <input id={id} value={code} onChange={(e) => setCode(e.target.value.replace(/[^a-zA-Z]/g, '').slice(0, 3))} className={`${INPUT} w-44 uppercase`} data-testid="in-k-code" />}
      </Field>
      {err && (
        <p role="alert" className="ms-banner ms-banner--err mt-2" data-testid="k-error">
          <span className="ws-wrap">{err}</span>
        </p>
      )}
      <button type="submit" disabled={busy} className="ms-btn ws-btn-primary mt-3" style={{ height: 44 }} data-testid="add-k">
        {busy ? 'Looking up…' : 'Add device'}
      </button>
    </form>
  )
}

function ByCsv({ mine, onDone }: { mine: MineApi; onDone: (msg: string) => void }) {
  const [text, setText] = useState('')
  const [res, setRes] = useState<CsvResult | null>(null)
  const run = (t: string) => {
    setText(t)
    setRes(t.trim() ? parseCsv(t, mine.mine.devices) : null)
  }
  const onFile = async (f: File | undefined) => {
    if (!f) return
    if (f.size > 200_000) return setRes({ rows: [], errors: [{ line: 0, message: 'The file is larger than 200 KB.' }] })
    run(await f.text())
  }
  const room = Math.max(0, 200 - mine.mine.devices.length)
  const importRows = () => {
    if (!res) return
    const rows = res.rows.slice(0, room)
    const inputs: NewDevice[] = rows.map((r) => ({
      name: r.name,
      product_code: r.product_code,
      k_number: r.k_number,
      source: 'csv',
      note: r.product_code && !mine.known.has(r.product_code) ? UNKNOWN_CODE_NOTE : null,
    }))
    mine.add(inputs)
    setText('')
    setRes(null)
    onDone(`Imported ${inputs.length} ${inputs.length === 1 ? 'device' : 'devices'} from the CSV.${res.errors.length ? ` ${res.errors.length} problem${res.errors.length === 1 ? '' : 's'} skipped.` : ''}`)
  }
  return (
    <div>
      <p className="m-0 mt-3 text-[16px] text-ink-2">
        Columns: <span className="ms-code">name</span>, <span className="ms-code">product_code</span>, <span className="ms-code">k_number</span>. Nothing is imported until you press
        Import. K-numbers in a file are stored as "not checked yet".
      </p>
      <Field label="Choose a CSV file">
        {(id) => (
          <input id={id} type="file" accept=".csv,text/csv" onChange={(e) => { void onFile(e.target.files?.[0]); e.target.value = '' }} className="mt-1 block min-h-11 text-[17px]" data-testid="in-csv-file" />
        )}
      </Field>
      <Field label="Or paste CSV text">
        {(id) => (
          <textarea
            id={id}
            value={text}
            onChange={(e) => run(e.target.value)}
            rows={5}
            spellCheck={false}
            className="mt-1 block w-full max-w-xl rounded-xs border border-rule-strong bg-surface p-2 font-mono text-[15px] text-ink"
            data-testid="in-csv-text"
          />
        )}
      </Field>
      {res && (
        <div className="mt-3" data-testid="csv-preview">
          <p className="m-0 text-[17px] font-semibold">
            <span className="ms-num" data-testid="csv-valid">{res.rows.length}</span> valid, <span className="ms-num" data-testid="csv-bad">{res.errors.length}</span> with problems
          </p>
          {res.errors.length > 0 && (
            <ul className="m-0 mt-1 list-disc pl-5 text-[16px] text-critical" data-testid="csv-errors">
              {res.errors.slice(0, 10).map((e, i) => (
                <li key={i} className="ws-wrap">{e.message}</li>
              ))}
              {res.errors.length > 10 && <li>and {res.errors.length - 10} more</li>}
            </ul>
          )}
          {res.rows.length > 0 && (
            <div className="mt-2 overflow-x-auto rounded-md border border-rule">
              <table className="w-full border-collapse text-left text-[16px]" aria-label="CSV preview">
                <thead>
                  <tr className="bg-sunk text-ink-2">
                    <th className="px-2 py-1">Name</th>
                    <th className="px-2 py-1">Code</th>
                    <th className="px-2 py-1">K-number</th>
                  </tr>
                </thead>
                <tbody>
                  {res.rows.slice(0, 8).map((r) => (
                    <tr key={r.line} className="border-t border-rule">
                      <td className="ws-wrap px-2 py-1">{r.name}</td>
                      <td className="ms-code px-2 py-1">{r.product_code ?? '—'}</td>
                      <td className="ms-code px-2 py-1">{r.k_number ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {res.rows.length > 8 && <p className="m-0 px-2 py-1 text-[15px] text-ink-2">Showing 8 of {res.rows.length}.</p>}
            </div>
          )}
          <button type="button" className="ms-btn ws-btn-primary mt-3" style={{ height: 44 }} disabled={res.rows.length === 0} onClick={importRows} data-testid="csv-import">
            Import {Math.min(res.rows.length, room)} {res.rows.length === 1 ? 'device' : 'devices'}
          </button>
        </div>
      )}
    </div>
  )
}

function ByLabel({ mine, onDone }: { mine: MineApi; onDone: (msg: string) => void }) {
  if (!mine.apiBase)
    return (
      <p className="m-0 mt-3 text-[17px] text-ink-2" data-testid="label-off">
        Reading a label photo needs the live service, which is not connected in this build. Add a device by product code, K-number or CSV instead.
      </p>
    )
  const add = (c: Candidate) => {
    const code = c.product_code.toUpperCase()
    const dev: NewDevice = {
      name: c.device_name || `Device ${c.k_number}`,
      product_code: isProductCode(code) ? code : null,
      k_number: isKNumber(c.k_number) ? c.k_number : null,
      source: 'label',
      note: isProductCode(code) && !mine.known.has(code) ? UNKNOWN_CODE_NOTE : null,
      k_check: 'matched on a label photo; you confirmed the match',
    }
    mine.add([dev])
    onDone(`Added ${dev.name} (only the match you confirmed).`)
  }
  return (
    <div>
      <p className="m-0 mt-3 text-[16px] text-ink-2">
        Take or upload a photo of the device label. Possible matches from openFDA are listed; confirm one and only that match is added.
      </p>
      <CameraPanel apiBase={mine.apiBase} onAdd={add} addLabel="Add to your company" />
    </div>
  )
}

/** Export, import and clear. */
function Data({ mine }: { mine: MineApi }) {
  const [msg, setMsg] = useState<{ ok: boolean; lines: string[] } | null>(null)
  const [pending, setPending] = useState<MineCompany | null>(null)
  const [confirmClear, setConfirmClear] = useState(false)
  const file = useRef<HTMLInputElement>(null)
  const doExport = () => {
    const blob = new Blob([exportJson(mine.mine)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'maudesignal-my-company.json'
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    setMsg({ ok: true, lines: [`Exported ${mine.mine.devices.length} devices to maudesignal-my-company.json.`] })
  }
  const onFile = async (f: File | undefined) => {
    if (!f) return
    setPending(null)
    if (f.size > MAX_JSON_BYTES) return setMsg({ ok: false, lines: [`The file is larger than ${MAX_JSON_BYTES / 1000} KB.`] })
    let raw: unknown
    try {
      raw = JSON.parse(await f.text())
    } catch {
      return setMsg({ ok: false, lines: ['The file is not valid JSON.'] })
    }
    const r = validateImport(raw)
    if (!r.ok) return setMsg({ ok: false, lines: r.errors })
    if (mine.mine.devices.length === 0) {
      mine.replace(r.company)
      return setMsg({ ok: true, lines: [`Imported ${r.company.devices.length} devices.`] })
    }
    setMsg(null)
    setPending(r.company)
  }
  return (
    <div className="mt-6 border-t border-rule pt-4" data-testid="mine-data">
      <h4 className="m-0 font-serif text-[20px] font-semibold">Your data</h4>
      <p className="m-0 mt-1 text-[16px] text-ink-2">A file you export is plain JSON on your computer. Nothing leaves this browser.</p>
      <div className="mt-2 flex flex-wrap gap-2">
        <button type="button" className={BTN2} style={{ height: 44 }} onClick={doExport} data-testid="export-json">
          Export JSON
        </button>
        <button type="button" className={BTN2} style={{ height: 44 }} onClick={() => file.current?.click()} data-testid="import-json">
          Import JSON
        </button>
        <input
          ref={file}
          type="file"
          accept="application/json,.json"
          className="sr-only"
          tabIndex={-1}
          aria-label="Import a company JSON file"
          data-testid="import-json-file"
          onChange={(e) => {
            void onFile(e.target.files?.[0])
            e.target.value = ''
          }}
        />
        <button type="button" className={BTN2} style={{ height: 44 }} onClick={() => setConfirmClear(true)} disabled={mine.mine.devices.length === 0 && !mine.mine.company} data-testid="clear-company">
          Clear
        </button>
      </div>
      {confirmClear && (
        <div role="alertdialog" aria-label="Confirm clear" className="mt-3 rounded-md border-2 border-warning bg-warning-soft p-3" data-testid="clear-confirm">
          <p className="m-0 text-[17px] font-semibold">Remove your company name and all {mine.mine.devices.length} devices from this browser? This cannot be undone. Export first to keep a copy.</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button type="button" className="ms-btn ws-btn-primary" style={{ height: 44 }} onClick={() => { mine.clear(); setConfirmClear(false); setMsg({ ok: true, lines: ['Cleared.'] }) }} data-testid="clear-yes">
              Yes, clear it
            </button>
            <button type="button" className={BTN2} style={{ height: 44 }} onClick={() => setConfirmClear(false)}>
              Keep it
            </button>
          </div>
        </div>
      )}
      {pending && (
        <div role="alertdialog" aria-label="Confirm import" className="mt-3 rounded-md border-2 border-warning bg-warning-soft p-3" data-testid="import-confirm">
          <p className="m-0 text-[17px] font-semibold">
            Replace your {mine.mine.devices.length} devices with the {pending.devices.length} in the file?
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button type="button" className="ms-btn ws-btn-primary" style={{ height: 44 }} onClick={() => { mine.replace(pending); setMsg({ ok: true, lines: [`Imported ${pending.devices.length} devices.`] }); setPending(null) }} data-testid="import-yes">
              Replace
            </button>
            <button type="button" className={BTN2} style={{ height: 44 }} onClick={() => setPending(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}
      {msg && (
        <div role={msg.ok ? 'status' : 'alert'} className={`ms-banner ${msg.ok ? 'ms-banner--ok' : 'ms-banner--err'} mt-3`} data-testid={msg.ok ? 'data-ok' : 'import-errors'}>
          <ul className="m-0 list-none p-0">
            {msg.lines.map((l, i) => (
              <li key={i} className="ws-wrap">{l}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

/** The editor: company name, the four ways to add a device, and export / import / clear. */
export function MakeItYours({ onClose }: { onClose: () => void }) {
  const mine = useMine()
  const [method, setMethod] = useState<Method>('code')
  const [done, setDone] = useState<string | null>(null)
  if (!mine) return null
  const note = (m: string) => setDone(m)
  const tab = (on: boolean) =>
    ['min-h-11 border px-3 text-[17px]', on ? 'border-ink bg-inverse font-semibold text-on-inverse' : 'border-rule-strong bg-surface text-ink hover:bg-sunk'].join(' ')
  return (
    <section id="make-it-yours" aria-label="Make it yours" className="rounded-md border border-rule-strong bg-surface p-4" data-testid="make-it-yours-panel">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="m-0 font-serif text-[24px] font-semibold leading-tight">Make it yours</h2>
          <p className="m-0 mt-1 text-[16px] text-ink-2">{MINE_BANNER}. Never uploaded, never counted, never sent with a page view.</p>
        </div>
        <button type="button" className="ws-icon-btn min-h-11 min-w-11" onClick={onClose} aria-label="Close Make it yours">
          <Icon name="close" />
        </button>
      </div>
      <Field label="Company name">
        {(id) => <input id={id} value={mine.mine.company} maxLength={80} onChange={(e) => mine.setCompany(e.target.value)} className={INPUT} data-testid="in-company" autoComplete="off" />}
      </Field>
      <div role="group" aria-label="How to add a device" className="mt-4 flex flex-wrap gap-2">
        {METHODS.map((m) => (
          <button key={m.id} type="button" className={tab(method === m.id)} aria-pressed={method === m.id} onClick={() => { setMethod(m.id); setDone(null) }} data-testid={`method-${m.id}`}>
            {m.label}
          </button>
        ))}
      </div>
      {method === 'code' && <ByCode mine={mine} onDone={note} />}
      {method === 'k' && <ByK mine={mine} onDone={note} />}
      {method === 'csv' && <ByCsv mine={mine} onDone={note} />}
      {method === 'label' && <ByLabel mine={mine} onDone={note} />}
      {done && (
        <p role="status" className="ms-banner ms-banner--ok mt-3" data-testid="added-msg">
          <span className="ws-wrap">{done}</span>
        </p>
      )}
      <Data mine={mine} />
    </section>
  )
}
