import { describe, expect, it } from 'vitest'
import { approveLocally, capaDrafts, flaggedRows, producedTabs, protocolFor } from './artifacts'
import type { Audit, Sweep, Thread } from './types'

const thread = (names: string[]): Thread => ({
  id: 't',
  workflow: 'ask-copilot',
  question: 'q',
  voice: null,
  recorded_at_utc: '',
  model: 'm',
  tool_steps: names.map((name) => ({ name, arguments: {}, summary: '' })),
  sentences: [],
  first_pass: null,
  repaired: false,
})

describe('producedTabs', () => {
  it('opens CAPA first for a thread that drafted one', () => {
    expect(producedTabs(thread(['weekly_signals', 'draft_capa']))).toEqual([
      'capa',
      'dossier',
      'brief',
      'digest',
      'protocol',
      'audit',
    ])
  })
  it('has only the audit tab when no tool ran', () => {
    expect(producedTabs(thread([]))).toEqual(['audit'])
    expect(producedTabs(null)).toEqual([])
  })
})

describe('flaggedRows', () => {
  it('drops stable rows and sorts by this week count', () => {
    const row = (product_code: string, classification: string, current_count: number) => ({
      product_code,
      classification,
      current_count,
      baseline_count: 0,
      baseline_weekly_mean: 0,
      spike_ratio: null,
      current_severe_count: 0,
    })
    const sweep = { rows: [row('A', 'stable', 9), row('B', 'spike', 2), row('C', 'new_signal', 5)] } as unknown as Sweep
    expect(flaggedRows(sweep).map((r) => r.product_code)).toEqual(['C', 'B'])
  })
})

describe('capaDrafts', () => {
  it('reads capa.draft entries only', () => {
    const audit: Audit = {
      notes: [],
      runs: [
        {
          run_label: 'typed',
          chain_ok: true,
          first_bad_seq: null,
          entries: [
            { seq: 1, ts: 't', actor: 'a', action: 'copilot.answer', entity_id: 'Q', payload: {}, prev_hash: 'GENESIS', entry_hash: 'h' },
            {
              seq: 2,
              ts: 't',
              actor: 'a',
              action: 'capa.draft',
              entity_id: 'CAPA-1',
              payload: { title: 'T', product_code: 'LLZ', report_ids: ['1', 2] },
              prev_hash: 'h',
              entry_hash: 'h2',
            },
          ],
        },
      ],
    }
    const d = capaDrafts(audit)
    expect(d).toHaveLength(1)
    expect(d[0]).toMatchObject({ id: 'CAPA-1', title: 'T', productCode: 'LLZ', reportIds: ['1', '2'] })
  })
})

describe('approveLocally', () => {
  it('needs a name', () => {
    expect(approveLocally('  ')).toBeNull()
    expect(approveLocally(' Dr A ')).toEqual({ status: 'approved', by: 'Dr A' })
  })
})

describe('protocolFor', () => {
  it('is empty for an unknown thread', () => {
    expect(protocolFor({ protocols: {} }, 'x')).toEqual([])
    expect(protocolFor({ protocols: {} }, null)).toEqual([])
  })
})
