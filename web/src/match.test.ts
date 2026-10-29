import { describe, expect, it } from 'vitest'
import threadsJson from '../public/data/threads.json'
import { closestThread, tokens } from './match'
import type { Thread } from './types'

const threads = threadsJson.threads as unknown as Thread[]
const best = (q: string) => closestThread(q, threads)?.thread.id ?? null

describe('closestThread over the recorded questions', () => {
  it('opens the recorded question that was typed, ignoring case and punctuation', () => {
    expect(best('WHAT CHANGED THIS WEEK')).toBe('01-what-changed')
    expect(best('how many qih reports are on file?')).toBe('07-qih-count')
  })

  it('finds the closest one for a rephrasing', () => {
    expect(best('are there recalls for LLZ')).toBe('10-recalls')
    expect(best('what does K261677 clear')).toBe('11-510k')
    expect(best('MHRA alerts about imaging software')).toBe('23-mhra')
    expect(best('prepare a CAPA-need evidence pack')).toBe('05-capa-need-evidence')
  })

  it('returns nothing when no recorded question is close', () => {
    expect(best('what is the weather in Paris')).toBeNull()
    expect(best('tell me a story about a dragon')).toBeNull()
    expect(best('')).toBeNull()
    expect(best('   ?? ')).toBeNull()
  })

  it('does not match a question that shares only one word of several', () => {
    expect(best('which devices does Medtronic make in Ireland')).toBeNull()
  })

  it('never opens a greeting clip', () => {
    for (const q of ['good evening Alistair', 'welcome we are glad you stopped by'])
      expect(best(q)).toBeNull()
  })

  it('tokenises without stop words and plural endings', () => {
    expect(tokens('Are there FDA recalls on file?')).toEqual(['fda', 'recall', 'file'])
  })
})
