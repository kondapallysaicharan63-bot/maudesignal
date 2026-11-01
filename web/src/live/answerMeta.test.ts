// The v2 answer turn's plain functions: model chip mapping, copy text, read-aloud text and voice choice, the rating
// payload and the layout flag. No DOM.
import { describe, expect, it } from 'vitest'
import { ANSWER_REASON_MAX, buildAnswerRating } from '../feedback'
import { isV2, layoutMode } from '../layoutFlag'
import type { AskResponse, LiveTraceStep } from './api'
import { answeredAt, chipFor, copyText, fmtClock, fmtDate, labelChip, modelName, modelsUsed, newAnswerId, readableText, recordedDate, stepNote, tierLabel } from './answerMeta'
import { pickVoice, readKey, sentencesOf, voiceScore } from './readAloud'

const step = (model: string | null, status: LiveTraceStep['status'] = 'ok'): LiveTraceStep => ({ step: 's', model, ms: 10, status })
const SPARK = step('muse-spark-1.3')

describe('layoutMode', () => {
  it('reads ?layout= first, then the build default, then classic', () => {
    expect(layoutMode('?layout=v2', undefined)).toBe('v2')
    expect(layoutMode('?layout=classic', 'v2')).toBe('classic')
    expect(layoutMode('?layout=V2 ', 'classic')).toBe('v2')
    expect(layoutMode('', 'v2')).toBe('v2')
    expect(layoutMode('?layout=other', 'v2')).toBe('v2')
    expect(layoutMode('?layout=other', 'weird')).toBe('classic')
    expect(layoutMode('', undefined)).toBe('classic')
    expect(layoutMode('?x=1&layout=v2', '')).toBe('v2')
    expect(isV2('?layout=v2')).toBe(true)
    expect(isV2('?layout=classic')).toBe(false)
  })
})

describe('model chip', () => {
  it('names only known Meta model ids', () => {
    expect(modelName('muse-spark-1.3')).toBe('Muse Spark 1.3')
    expect(modelName('muse-spark-2.0')).toBe('Muse Spark 2.0')
    expect(modelName('muse-voice-transcribe-1.0')).toBe('Muse Voice Transcribe')
    expect(modelName('muse-voice-transcribe-2.1')).toBe('Muse Voice Transcribe')
    expect(modelName('sam-3.1')).toBe('SAM 3.1')
    expect(modelName('muse-wonder-1.0')).toBe('Muse Wonder')
    expect(modelName('muse-wonder')).toBe('Muse Wonder')
    expect(modelName('gpt-4o')).toBeNull()
    expect(modelName(null)).toBeNull()
    expect(modelName('')).toBeNull()
  })

  it('a live typed answer: "Muse Spark 1.3 · Live"; the id the server reports is the one named', () => {
    expect(chipFor({ mode: 'live', tier: 'live', trace: [SPARK, step(null)] })).toEqual({ kind: 'live', text: 'Muse Spark 1.3 · Live' })
    expect(chipFor({ mode: 'live', trace: [SPARK] }).text).toBe('Muse Spark 1.3 · Live')
    expect(chipFor({ mode: 'live', trace: [step('muse-spark-1.4')] }).text).toBe('Muse Spark 1.4 · Live')
  })

  it('a voice turn names Muse Voice Transcribe, in the order the steps ran', () => {
    expect(chipFor({ mode: 'live', trace: [step('muse-voice-transcribe-1.0'), SPARK] }).text).toBe('Muse Voice Transcribe + Muse Spark 1.3 · Live')
  })

  it('a label photo names SAM 3.1 and Muse Spark', () => {
    expect(labelChip({ mode: 'live', trace: [step(null), step('sam-3.1'), SPARK, step(null)] }).text).toBe('SAM 3.1 + Muse Spark 1.3 · Live')
  })

  it('an evidence review names Muse Wonder', () => {
    expect(chipFor({ mode: 'live', trace: [step('muse-wonder-1.0')] }).text).toBe('Muse Wonder · Live')
  })

  it('never guesses: unknown ids and steps that did not run are left out', () => {
    expect(chipFor({ mode: 'live', trace: [step('some-other-model')] }).text).toBe('Live')
    expect(chipFor({ mode: 'live', trace: [] }).text).toBe('Live')
    expect(modelsUsed([step('muse-spark-1.3', 'skipped'), step('sam-3.1', 'failed')])).toEqual([])
  })

  it('tiers 1 and 2 are an instant answer, tier 3 is cached', () => {
    expect(chipFor({ mode: 'canned', tier: 'canned', trace: [step(null)] })).toEqual({ kind: 'instant', text: 'Instant answer' })
    expect(chipFor({ mode: 'direct', tier: 'direct', trace: [] })).toEqual({ kind: 'instant', text: 'Instant answer' })
    expect(chipFor({ mode: 'live', tier: 'cache', trace: [SPARK] })).toEqual({ kind: 'cached', text: 'Cached' })
  })

  it('a recorded run carries its date: its own field, else the note, else none', () => {
    expect(chipFor({ mode: 'recorded', trace: [], recorded_at: '2026-10-28T09:00:00Z' })).toEqual({ kind: 'recorded', text: 'Recorded · Oct 28, 2026' })
    expect(chipFor({ mode: 'recorded', trace: [], recorded_note: 'Shown instead: a recorded run (recorded 2026-10-30).' }).text).toBe('Recorded · Oct 30, 2026')
    expect(chipFor({ mode: 'recorded', trace: [step('muse-spark-1.3', 'skipped')], recorded_note: 'No stored run is close.' }).text).toBe('Recorded')
    expect(recordedDate({})).toBeNull()
    expect(fmtDate('not a date')).toBeNull()
  })

  it("reads the note's own date, never one inside the quoted question", () => {
    const note = 'No live model call was made. Shown instead: a recorded run that answered "What was recorded 2025-01-02 for LLZ?" (recorded 2026-10-28).'
    expect(recordedDate({ recorded_note: note })).toBe('Oct 28, 2026')
    expect(recordedDate({ recorded_note: 'Shown instead: a recorded run that answered "Was it recorded 2025-01-02?".' })).toBeNull()
    expect(recordedDate({ recorded_at: '2026-10-27T08:00:00Z', recorded_note: note })).toBe('Oct 27, 2026')
  })

  it('Details names each route in plain words', () => {
    expect(tierLabel({ tier: 'canned', mode: 'canned' })).toBe('Instant reply, no model call')
    expect(tierLabel({ tier: 'direct', mode: 'direct' })).toBe('Direct FDA lookup, no model call')
    expect(tierLabel({ tier: 'cache', mode: 'live' })).toBe('Earlier answer reused, no model call')
    expect(tierLabel({ tier: 'live', mode: 'live' })).toBe('Live model answer')
    expect(tierLabel({ mode: 'live' })).toBe('Live model answer')
    expect(tierLabel({ mode: 'recorded' })).toBe('Recorded answer, no live model call')
  })

  it('test-mock notes are never shown outside a dev build', () => {
    expect(stepNote('e2e route mock', false)).toBeNull()
    expect(stepNote('smoke-test route mock', false)).toBeNull()
    expect(stepNote('e2e route mock', true)).toBe('e2e route mock')
    expect(stepNote('1 tool call(s): what_changed_this_week', false)).toBe('1 tool call(s): what_changed_this_week')
    expect(stepNote(undefined, false)).toBeNull()
  })
})

const ANSWER: Pick<AskResponse, 'answer'> = {
  answer: {
    speakable: [
      { text: '33 reports were stored for the week (report 50426770).', links: [{ label: 'Report 50426770', url: 'https://www.accessdata.fda.gov/r?id=50426770' }] },
      { text: 'The 510(k) is K123456 (K123456), see https://api.fda.gov/device/510k.json for it.', links: [{ label: 'openFDA 510(k)', url: 'https://api.fda.gov/device/510k.json' }] },
      { text: 'Two device types had more serious reports than usual.', links: [] },
    ],
    withheld: [{ reason: 'a number did not match' }],
    spoken_text: '',
  },
}

describe('copy text', () => {
  it('holds every sentence and its FDA links as plain text, and never the question', () => {
    const t = copyText({ ...ANSWER, mode: 'live', tier: 'live' })
    expect(t.startsWith('33 reports were stored for the week')).toBe(true)
    expect(t).toContain('Two device types had more serious reports than usual.')
    expect(t).toContain('Report 50426770: https://www.accessdata.fda.gov/r?id=50426770')
    expect(t).toContain('openFDA 510(k): https://api.fda.gov/device/510k.json')
    expect(t).toContain('FDA sources:')
    expect(t).toContain('Not medical advice')
    expect(t).not.toContain('What changed this week')
    expect(t).not.toContain('a number did not match') // held-back sentences are not copied
  })

  it('a recorded answer is labelled with its date and carries its note, including the substitute note', () => {
    const note = 'No live model call was made. Shown instead: a recorded run that answered "What changed this week?" (recorded 2026-10-28).'
    const t = copyText({ ...ANSWER, mode: 'recorded', recorded_note: note })
    expect(t.split('\n')[0]).toBe('Recorded answer · Oct 28, 2026')
    expect(t.split('\n')[1]).toBe(note)
    expect(t.indexOf(note)).toBeLessThan(t.indexOf('33 reports'))
    const none = copyText({ ...ANSWER, mode: 'recorded', recorded_note: 'The live service could not be reached.' })
    expect(none.startsWith('Recorded answer\nThe live service could not be reached.')).toBe(true)
    expect(copyText({ ...ANSWER, mode: 'recorded', recorded_at: '2026-10-27T01:00:00Z' }).startsWith('Recorded answer · Oct 27, 2026\n\n')).toBe(true)
  })

  it('a cached answer says when it was first answered (UTC), when the response carries it', () => {
    expect(copyText({ ...ANSWER, mode: 'live', tier: 'cache', answered_at: '2026-11-01T10:15:00Z' }).startsWith('First answered 10:15 UTC\n\n')).toBe(true)
    expect(copyText({ ...ANSWER, mode: 'live', tier: 'cache' }).startsWith('33 reports')).toBe(true)
    expect(copyText({ ...ANSWER, mode: 'live', tier: 'live', answered_at: '2026-11-01T10:15:00Z' })).not.toContain('First answered')
  })
})

describe('read-aloud text and voice', () => {
  it('reads only the answer: no web addresses, no report ids or K-numbers in parentheses', () => {
    const t = readableText(ANSWER)
    expect(t).not.toMatch(/https?:/)
    expect(t).not.toContain('(report 50426770)')
    expect(t).not.toContain('(K123456)')
    expect(t).toContain('33 reports were stored for the week.')
    expect(t).toContain('The 510(k) is K123456, see for it.')
    expect(readableText({ answer: { speakable: [], withheld: [], spoken_text: 'Hello there.' } })).toBe('Hello there.')
  })

  it('on-device Natural / Neural voices first, then other on-device voices, then cloud Natural / Online', () => {
    const davidLocal = { name: 'Microsoft David - English (United States)', lang: 'en-US', default: true, localService: true }
    const ariaCloud = { name: 'Microsoft Aria Online (Natural) - English (United States)', lang: 'en-US', localService: false }
    const jennyLocal = { name: 'Microsoft Jenny (Natural) - English (United States)', lang: 'en-US', localService: true }
    const googleCloud = { name: 'Google US English', lang: 'en-US', localService: false }
    const french = { name: 'Thomas', lang: 'fr-FR', localService: true }
    expect(pickVoice([davidLocal, ariaCloud, jennyLocal, googleCloud, french])).toBe(jennyLocal)
    expect(pickVoice([davidLocal, ariaCloud, googleCloud])).toBe(davidLocal)
    expect(pickVoice([ariaCloud, googleCloud, french])).toBe(ariaCloud)
    expect(pickVoice([googleCloud, french])).toBe(googleCloud)
    expect(pickVoice([{ name: 'Daniel', lang: 'en-GB', localService: true }, { name: 'Alex', lang: 'en-US', localService: true }])?.name).toBe('Alex')
    expect(pickVoice([french])).toBeNull()
    expect(pickVoice([])).toBeNull()
    expect(voiceScore({ name: 'Jenny Neural', lang: 'en_US', localService: true })).toBeGreaterThan(voiceScore({ name: 'Ava Online (Natural)', lang: 'en-US' }))
  })

  it('splits the text into one utterance per sentence', () => {
    expect(sentencesOf('33 reports were stored. Two had injuries! Is that new? "Yes." 4 more.')).toEqual([
      '33 reports were stored.',
      'Two had injuries!',
      'Is that new?',
      '"Yes."',
      '4 more.',
    ])
    expect(sentencesOf('The 510(k) is K123456, see it.')).toEqual(['The 510(k) is K123456, see it.'])
    expect(sentencesOf('   ')).toEqual([])
    expect(readKey(7)).toBe('turn-7')
  })
})

describe('answer rating payload', () => {
  const now = () => new Date('2026-11-01T23:42:00Z')
  it('thumbs down carries the answer id and an optional reason, never question or answer text', () => {
    const p = buildAnswerRating('a-1234567890', 'down', '  The count looked off.  ', 'TEST-0', now)
    expect(p).toEqual({
      kind: 'answer_rating',
      answer_id: 'a-1234567890',
      rating: 1,
      comment: 'The count looked off.',
      consent: 'no_quote',
      ref: 'TEST-0',
      page: 'live-answer',
      client_ts: '2026-11-01T23:42:00.000Z',
    })
    expect(Object.keys(p)).not.toContain('question')
    expect(Object.keys(p)).not.toContain('answer')
  })
  it('the reason is cut to 300 characters; thumbs up sends none', () => {
    expect(buildAnswerRating('a-1234567890', 'down', 'x'.repeat(400), null, now).comment).toHaveLength(ANSWER_REASON_MAX)
    const up = buildAnswerRating('a-1234567890', 'up', 'ignored', null, now)
    expect(up.rating).toBe(5)
    expect(up.comment).toBe('')
  })
  it('answer ids match the API pattern and hold nothing from the answer', () => {
    for (let i = 0; i < 20; i++) expect(newAnswerId()).toMatch(/^[A-Za-z0-9_-]{8,64}$/)
    expect(newAnswerId(() => 'abc/def 12345')).toBe('a-abcdef12345')
  })
})

describe('clock', () => {
  it('shows a local time like 11:42 PM', () => {
    expect(fmtClock(new Date(2026, 10, 1, 23, 42))).toBe('11:42 PM')
    expect(fmtClock(new Date(2026, 10, 1, 9, 5))).toBe('9:05 AM')
  })
  it("uses the response's answered_at when it carries a valid time", () => {
    const fallback = new Date(2026, 10, 1, 12, 0)
    expect(answeredAt({ answered_at: '2026-11-01T10:15:00Z' }, fallback).toISOString()).toBe('2026-11-01T10:15:00.000Z')
    expect(answeredAt({ answered_at: 'garbage' }, fallback)).toBe(fallback)
    expect(answeredAt({}, fallback)).toBe(fallback)
  })
})
