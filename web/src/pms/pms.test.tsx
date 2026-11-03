// @vitest-environment jsdom
// PMS board, evidence pack, note to file, exports, browser audit chain, data-as-of banner, validation page (2026-11-03).
// Expected values are read from the stored exports (alerts.json, manifest.json, sweep.json), not typed in.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import alertsFile from '../../public/data/alerts.json'
import manifest from '../../public/data/manifest.json'
import sweep from '../../public/data/sweep.json'
import example from '../fixtures/investigateExample.json'
import { parseAlerts, type AlertDetail } from '../alerts'
import { parseInvestigation, type Investigation } from '../investigate/api'
import { InvestigatePage } from '../investigate/InvestigatePage'
import type { Manifest, WorkspaceData } from '../types'
import { appendAudit, AUDIT_KEY, entryHash, loadAudit, pyJson, pyTs, resetAuditMemory, verifyAudit, type AuditEntry } from './audit'
import { boardRows, changeStatus, mdrDue, TRANSITIONS } from './board'
import { BoardPage, flaggedFromData } from './BoardPage'
import { asOfText, DELAY_SENTENCE, inDelayWindow, investigationAsOf, storedAsOf, sweepAsOf } from './DataAsOf'
import { packFiles } from './EvidencePackPanel'
import { BLANK_FIELD, escalationChecklist, hasDecisionSentence, NOTE_LABEL, noteMarkdown, packFromAlert, packFromInvestigation, recallCheck, reportsCsv, severityMix, type Note } from './pack'
import { pdfText, renderPdf } from './pdf'
import { KNOWN_LIMITS, NOT_VALIDATED, ValidationPage } from './ValidationPage'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const ALERTS = parseAlerts(alertsFile)!
const MIX = ALERTS.alerts.find((a) => a.rule === 'report mix changed') as AlertDetail
const M = manifest as unknown as Manifest
const INV = parseInvestigation((example as { answer: unknown }).answer) as Investigation
const DATA = { alerts: ALERTS, manifest: M } as unknown as WorkspaceData

let host: HTMLDivElement
let root: Root
beforeEach(() => {
  window.localStorage.clear()
  resetAuditMemory()
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})
afterEach(() => {
  act(() => root.unmount())
  host.remove()
  vi.restoreAllMocks()
})
const q = (id: string) => document.querySelector(`[data-testid="${id}"]`) as HTMLElement | null
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 30)) })
const click = (el: Element | null) => act(async () => { (el as HTMLElement).click() })
function typeInto(el: HTMLElement | null, value: string) {
  return act(async () => {
    const e = el as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
    const proto = e instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : e instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype
    Object.getOwnPropertyDescriptor(proto, 'value')?.set?.call(e, value)
    e.dispatchEvent(new Event(e instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }))
  })
}

describe('browser audit chain', () => {
  it('hashes exactly like the Python trail (vector from Database.audit_entry_hash)', async () => {
    const p1 = pyJson({ from: 'new', to: 'under_review', why: 'Report mix changed — 20% ✓', owner: 'Ana Ruiz' })
    expect(p1).toBe('{"from": "new", "owner": "Ana Ruiz", "to": "under_review", "why": "Report mix changed \\u2014 20% \\u2713"}')
    const h1 = await entryHash('GENESIS', '2026-11-03T09:12:03.123000', 'Ana Ruiz', 'board_status', 'board:DSI', p1)
    expect(h1).toBe('4f72d5e7cc988b29c9f7048055a70fa6d6534016ff6fc76822781484b70097a7')
    const p2 = pyJson({ decision: 'note_to_file', report_ids: ['1', '2'], n: 3 })
    const h2 = await entryHash(h1, '2026-11-03T09:13:00', 'Ana Ruiz', 'note_to_file', 'board:DSI', p2)
    expect(h2).toBe('0cbadf8ddb416bcff25312a3bbf000e203ea301b513f0ccac346cd6142c2d11e')
    expect(pyTs(new Date('2026-11-03T09:13:00.000Z'))).toBe('2026-11-03T09:13:00')
    expect(pyTs(new Date('2026-11-03T09:12:03.123Z'))).toBe('2026-11-03T09:12:03.123000')
  })

  it('verifies, and a single edited entry breaks the chain at that entry', async () => {
    for (const a of ['one', 'two', 'three']) await appendAudit({ actor: 'Ana Ruiz', action: a, entity_id: 'board:LLZ', payload: { a } })
    const all = loadAudit()
    expect(all.map((e) => e.seq)).toEqual([1, 2, 3])
    expect(await verifyAudit(all)).toEqual({ ok: true, firstBad: null })
    const copy: AuditEntry[] = JSON.parse(window.localStorage.getItem(AUDIT_KEY)!)
    copy[1] = { ...copy[1], actor: 'Someone Else' }
    expect(await verifyAudit(copy)).toEqual({ ok: false, firstBad: 2 })
  })
})

describe('board', () => {
  it('moves only by a named person along allowed moves, with an advisory MDR clock', async () => {
    await expect(changeStatus({ code: 'DSI', why: 'w', current: 'new', to: 'under_review', actor: '' })).rejects.toThrow(/named person/)
    await expect(changeStatus({ code: 'DSI', why: 'w', current: 'new', to: 'closed', actor: 'Ana Ruiz' })).rejects.toThrow(/cannot move/)
    await changeStatus({ code: 'DSI', why: 'w', current: 'new', to: 'under_review', actor: 'Ana Ruiz', owner: 'Ben Okafor', awareness: '2026-11-03' })
    const rows = boardRows([{ code: 'DSI', why: 'w' }], loadAudit())
    expect(rows[0]).toMatchObject({ status: 'under_review', owner: 'Ben Okafor', due: '2026-12-03', audit_seq: 1 })
    expect(mdrDue('2026-11-06', true)?.due).toBe('2026-11-13')
    expect(mdrDue('2026-02-31')).toBeNull()
    expect(TRANSITIONS.new).toEqual(['under_review'])
  })

  it('lists the real flagged alerts only (no simulated company), one row per code', () => {
    const f = flaggedFromData(DATA)
    const expected = [...new Set(ALERTS.alerts.filter((a) => a.source.kind !== 'company' && a.rule).map((a) => a.product_code))]
    expect(f.map((x) => x.code)).toEqual(expected)
    expect(f.find((x) => x.code === MIX.product_code)?.why).toContain(MIX.mix_sentence!)
  })

  it('page: status change by a named person appears as an audit row, and the chain re-verifies on display', async () => {
    act(() => root.render(<BoardPage data={DATA} onInvestigate={() => undefined} />))
    await flush()
    expect(q('board-not-qms')?.textContent).toContain('This is not a QMS')
    expect(q('board-asof')?.textContent).toContain(`Data as of: ${M.data_as_of!.sweep.week_end! > M.data_as_of!.stored.latest! ? M.data_as_of!.sweep.week_end : M.data_as_of!.stored.latest}`)
    const code = MIX.product_code
    await click(q(`board-open-${code}`))
    await click(q(`board-submit-${code}`))
    expect(q(`board-error-${code}`)?.textContent).toMatch(/named person/)
    await typeInto(q(`board-actor-${code}`), 'Ana Ruiz')
    await typeInto(q(`board-owner-${code}`), 'Ben Okafor')
    await click(q(`board-submit-${code}`))
    await flush()
    expect(q(`board-status-${code}`)?.textContent).toBe('Under review')
    const rows = [...document.querySelectorAll('[data-testid=local-audit-row]')]
    expect(rows).toHaveLength(1)
    expect(rows[0].textContent).toContain('Ana Ruiz')
    expect(rows[0].getAttribute('data-action')).toBe('board_status')
    expect(q('local-audit-status')?.textContent).toMatch(/Chain verified: 1 entry/)
  })
})

describe('evidence pack, checklists, note to file, exports', () => {
  const asOf = storedAsOf(M)
  const pack = packFromAlert(MIX, asOf)

  it('severity mix is counts + shares of the listed reports, and no section decides', () => {
    const mix = severityMix(pack)
    const injury = MIX.reports.filter((r) => /injury/i.test(r.event_type ?? '')).length
    expect(mix.find((m) => m.event_type === 'injury')).toMatchObject({ count: injury, of: MIX.reports.length })
    const esc = escalationChecklist(pack)
    expect(esc.map((c) => c.item)).toEqual(['MDR reportability assessment', 'Recall / correction-and-removal assessment', 'Field safety action assessment'])
    expect(esc[0].basis).toMatch(/803\.50.*803\.53/)
    expect(esc[1].basis).toMatch(/21 CFR 806; 21 CFR 7 Subpart C/)
    const blob = JSON.stringify([esc, mix, recallCheck(pack)])
    expect(hasDecisionSentence(blob)).toBe(false)
    expect(hasDecisionSentence('A recall needed now.')).toBe(true)
    expect(hasDecisionSentence('This is a change in report mix, not proof of increased device risk.')).toBe(false)
  })

  it('note to file carries every PRD-20/25 field, and the PDF and CSV print them', () => {
    const note: Note = { pack, decision: 'escalate', rationale: 'Two injury reports; escalate to RA.', approver: 'Ana Ruiz', decided_utc: '2026-11-03T09:13:00Z', audit_seq: 7, version: '0.1.0', commit: 'abc123' }
    const md = noteMarkdown(note)
    for (const must of [
      NOTE_LABEL,
      `Product code: ${MIX.product_code}`,
      `Data as of: ${asOf.latest}`,
      MIX.mix_sentence!,
      MIX.reports[0].report_id,
      MIX.recalls[0].id,
      'Decision: Escalate',
      'Rationale (typed by the approver): Two injury reports; escalate to RA.',
      'Approver: Ana Ruiz',
      'browser audit entry #7',
      `Company complaint / CAPA number: ${BLANK_FIELD}`,
      'Build: MaudeSignal 0.1.0 · commit abc123',
      'Does this meet your recall procedure?',
      DELAY_SENTENCE,
    ])
      expect(md).toContain(must)
    expect(hasDecisionSentence(md)).toBe(false)
    const files = packFiles(note, [])
    expect(files.map((f) => f.name.split('-').slice(2).join('-'))).toEqual(['note-to-file.md', 'evidence-pack.pdf', 'reports.csv', 'audit.json'])
    const pdf = files[1].data as Uint8Array
    expect(String.fromCharCode(...pdf.slice(0, 8))).toBe('%PDF-1.4')
    const t = pdfText(pdf)
    expect(t).toContain('Approver: Ana Ruiz')
    expect(t).toContain('Page 1 of')
    const csv = reportsCsv(note)
    expect(csv.split('\r\n')[0]).toBe('# Build: MaudeSignal 0.1.0 · commit abc123')
    expect(csv).toContain(`# Company complaint / CAPA number: ${BLANK_FIELD}`)
    const audit = JSON.parse(files[3].data as string)
    expect(audit.company_complaint_or_capa_number).toBe('')
    expect(audit.build).toEqual({ version: '0.1.0', commit: 'abc123' })
  })

  it('a long text paginates and escapes brackets', () => {
    const pdf = renderPdf('t', Array.from({ length: 120 }, (_, i) => ['body', `line (${i})`] as ['body', string]), 'f')
    const t = pdfText(pdf)
    expect(t).toContain('line (119)')
    expect(t).toMatch(/Page 3 of 3/)
  })

  it('Investigate (recorded): non-manufacturer section first, pack accept/reject writes an audit row, note export opens', async () => {
    act(() => root.render(<InvestigatePage apiBase={null} />))
    await flush()
    const ids = [...document.querySelectorAll('[data-testid=inv-results] > section')].map((s) => s.getAttribute('data-testid'))
    expect(ids[0]).toBe('inv-sources')
    expect(q('inv-sources')?.textContent).toContain('Reports NOT filed by a manufacturer — check these against your complaint log')
    expect(q('inv-asof')?.textContent).toContain(DELAY_SENTENCE)
    expect(q('inv-pms-link')?.getAttribute('href')).toMatch(/pms-workflow/)
    const p = packFromInvestigation(INV, investigationAsOf(INV))
    expect(q('pack-nonmfr')?.querySelectorAll('li').length ?? 0).toBe(p.non_manufacturer.length)
    await click(q('pack-accept'))
    expect(q('pack-error')?.textContent).toMatch(/Type your name/)
    await typeInto(q('pack-reviewer'), 'Ana Ruiz')
    await typeInto(q('pack-reason'), 'Complete for this complaint')
    await click(q('pack-accept'))
    await flush()
    expect(q('pack-decided')?.textContent).toMatch(/Evidence accepted by Ana Ruiz · audit entry #1/)
    await typeInto(q('note-rationale'), 'No new failure mode; file a note.')
    await typeInto(q('note-approver'), 'Ana Ruiz')
    await click(q('note-record'))
    await flush()
    expect(q('note-seq')?.textContent).toBe('2')
    expect(q('note-preview')?.textContent).toContain(NOTE_LABEL)
    expect(q('note-preview')?.textContent).toContain('Approver: Ana Ruiz')
    expect(q('note-pdf-check')?.textContent).toContain('contains the approver and decision')
    const log = loadAudit()
    expect(log.map((e) => e.action)).toEqual(['pack_accept', 'note_to_file'])
    expect(JSON.parse(log[1].payload_json).decision).toBe('note_to_file')
    expect((await verifyAudit(log)).ok).toBe(true)
  })
})

describe('data-as-of banner', () => {
  it('stored dates come from the manifest, the sweep from the sweep file; never today', () => {
    const a = storedAsOf(M)
    expect(a.snapshot).toContain(`${M.data_as_of!.stored.earliest} to ${M.data_as_of!.stored.latest}`)
    const s = sweepAsOf(sweep.meta)
    expect(s.latest).toBe(sweep.meta.window.current_end)
    expect(s.snapshot).toContain(`checked ${sweep.meta.generated_utc.slice(0, 10)}`)
    const t = asOfText(a)
    expect(t).toContain('not because risk is zero')
    expect(t).not.toContain(new Date().toISOString().slice(0, 10) + '.')
  })
  it('a recent month is tagged as reporting delay, an old one is not', () => {
    expect(inDelayWindow('2026-10', '2026-11-03T00:00:00Z')).toBe(true)
    expect(inDelayWindow('2026-09', '2026-11-03T00:00:00Z')).toBe(true)
    expect(inDelayWindow('2026-06', '2026-11-03T00:00:00Z')).toBe(false)
  })
})

describe('validation page', () => {
  it('says not validated, lists the limits, and reads the lifecycle file', async () => {
    const lifecycle = { build: { version: '0.1.0', commit: 'x' }, models: { chat_and_vision: 'muse-spark-1.3' }, skills: { 'safety-copilot': '1.3.6' }, gate_cfr_sections: ['803.50'], gate_superseded_sections: ['820.198'], sweep: { checked_utc: sweep.meta.generated_utc, window: sweep.meta.window }, revalidation_trigger: 'Re-run.' }
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(lifecycle), { status: 200 }))
    act(() => root.render(<ValidationPage data={DATA} />))
    await flush()
    expect(q('not-validated')?.textContent).toContain(NOT_VALIDATED)
    expect(document.body.textContent).not.toMatch(/FDA validated|FDA approved|AI validated/)
    expect(q('validation-limits')?.querySelectorAll('li').length).toBe(KNOWN_LIMITS.length)
    expect(q('validation-skills')?.textContent).toContain('safety-copilot 1.3.6')
    expect(q('validation-sweep')?.textContent).toContain(sweep.meta.generated_utc.slice(0, 10))
  })
})

// ── F. live Q&A failure: forced 504 / 500 / network / cap, deterministic fallback, audit ─────────────────────────
import evidenceFile from '../../public/data/evidence.json'
import threadsFile from '../../public/data/threads.json'
import { FallbackData, FallbackPanel, productSummary, searchStored, storedRecalls, type Fallback } from './FallbackPanel'
import type { Evidence, Threads } from '../types'

describe('F. live-model fallback', () => {
  const FB_DATA = { evidence: evidenceFile as unknown as Evidence, alerts: ALERTS, threads: threadsFile as unknown as Threads }
  const code = MIX.product_code
  for (const kind of ['timeout', 'failure', 'cap'] as const) {
    it(`${kind}: no invented answer; four no-model buttons return stored data; retry; audit`, async () => {
      const fetchSpy = vi.spyOn(globalThis, 'fetch')
      const retry = vi.fn()
      const live = vi.fn()
      const fb: Fallback = { kind, reason: 'forced', productCode: code }
      act(() =>
        root.render(
          <FallbackData.Provider value={FB_DATA}>
            <FallbackPanel fb={fb} question={`What changed for ${code} this week?`} recordedShown={false} onRetry={retry} onLive={live} />
          </FallbackData.Provider>,
        ),
      )
      await flush()
      expect(q('fallback-recorded')?.textContent).toBe('No recorded answer is stored for this question.')
      await click(q('fallback-recalls'))
      const r = storedRecalls(FB_DATA, code)!
      expect(q('fallback-out-recalls')?.textContent).toContain(`${r.total} recall records for ${code}`)
      expect(q('fallback-out-recalls')?.textContent).toContain(r.items[0].id)
      await click(q('fallback-summary'))
      const p = productSummary(FB_DATA, code)
      expect(q('fallback-out-summary')?.textContent).toContain(`${p.reports} stored reports`)
      expect(q('fallback-out-summary')?.textContent).toContain(MIX.mix_sentence!)
      await click(q('fallback-reports'))
      expect(q('fallback-out-reports')).not.toBeNull()
      await click(q('fallback-live'))
      expect(live).toHaveBeenCalledWith(code)
      await click(q('fallback-retry'))
      if (kind === 'cap') expect(retry).not.toHaveBeenCalled()
      else expect(retry).toHaveBeenCalledTimes(1)
      expect(fetchSpy).not.toHaveBeenCalled() // no model call, no network call from any lookup
      await flush()
      const log = loadAudit()
      expect(log[0]).toMatchObject({ action: 'live_failure', actor: 'system' })
      expect(JSON.parse(log[0].payload_json).kind).toBe(kind)
      expect(log.filter((e) => e.action === 'fallback_choice').map((e) => JSON.parse(e.payload_json).choice)).toEqual(
        kind === 'cap' ? ['recalls', 'summary', 'reports', 'live'] : ['recalls', 'summary', 'reports', 'live', 'retry'],
      )
      expect((await verifyAudit(log)).ok).toBe(true)
    })
  }
  it('stored search is a text match over the stored reports of that code', () => {
    const s = searchStored(FB_DATA, 'LLZ', 'error loading images')
    const all = Object.values(FB_DATA.evidence.reports).filter((r) => r.product_code === 'LLZ')
    expect(s.total).toBe(all.length)
    expect(s.matched).toBe(all.filter((r) => ['error', 'loading', 'images'].some((w) => r.excerpt.toLowerCase().includes(w))).length)
  })
})
