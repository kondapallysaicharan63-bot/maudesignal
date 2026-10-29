import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { chipState, resolveClaim, sentenceResolves, sortReports } from './claims'
import type { Evidence, Threads } from './types'

const dir = resolve(__dirname, '../public/data')
const load = <T>(f: string): T => JSON.parse(readFileSync(resolve(dir, f), 'utf8')) as T
const threads = load<Threads>('threads.json')
const ev = load<Evidence>('evidence.json')

describe('claim chips resolve against the built data', () => {
  it('has threads', () => {
    expect(threads.threads.length).toBeGreaterThan(0)
  })

  it('every final sentence resolves to evidence.json or a withheld reason', () => {
    const bad: string[] = []
    for (const t of threads.threads)
      for (const s of t.sentences) if (!sentenceResolves(s, ev)) bad.push(`${t.id}: ${s.text.slice(0, 50)}`)
    expect(bad).toEqual([])
  })

  it('every repaired answer keeps its first pass, and blocked first-pass sentences carry a reason', () => {
    for (const t of threads.threads.filter((x) => x.repaired)) {
      expect(t.first_pass).not.toBeNull()
      for (const s of t.first_pass?.sentences ?? []) {
        if (s.status === 'block') expect(s.reasons.length).toBeGreaterThan(0)
      }
    }
  })

  it('has at least one withheld sentence and each has a gate reason', () => {
    const withheld = threads.threads.flatMap((t) => t.sentences).filter((s) => chipState(s) === 'withheld')
    expect(withheld.length).toBeGreaterThan(0)
    for (const s of withheld) expect(s.reasons.length).toBeGreaterThan(0)
  })

  it('no claim lists an id that is missing from evidence', () => {
    for (const t of threads.threads)
      for (const s of t.sentences) for (const c of s.claims) expect(resolveClaim(c, ev).missing).toEqual([])
  })
})

describe('evidence order', () => {
  it('sorts severity first, then newest date', () => {
    const row = (event_type: string, date_received: string) => ({
      product_code: 'X',
      date_received,
      event_type,
      report_source: 'm',
      brand: '',
      excerpt: '',
      maude_url: '',
    })
    const out = sortReports([
      { id: 'a', row: row('Malfunction', '20260901') },
      { id: 'b', row: row('Injury', '20260101') },
      { id: 'c', row: row('Malfunction', '20260905') },
    ])
    expect(out.map((r) => r.id)).toEqual(['b', 'c', 'a'])
  })
})
