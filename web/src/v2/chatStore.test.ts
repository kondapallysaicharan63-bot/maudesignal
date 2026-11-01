// Saved chats (v2): save, restore, rename, delete, the caps, and storage that is corrupt or blocked.
import { describe, expect, it } from 'vitest'
import type { AskResponse } from '../live/api'
import type { LiveTurn } from '../live/useLiveChat'
import {
  autoTitle,
  capChats,
  CHATS_KEY,
  chatText,
  deleteChat,
  loadChats,
  MAX_CHATS,
  newChatId,
  parseChats,
  patchTurn,
  PENDING_NOTE,
  renameChat,
  saveChats,
  searchChats,
  storableTurn,
  trimTitle,
  upsertChat,
  type SavedChat,
} from './chatStore'

const resp = (text: string, mode: 'recorded' | 'live' = 'live'): AskResponse => ({
  mode,
  not_medical_advice: true,
  trace: [],
  cost_usd: null,
  limits: null,
  answer: { speakable: [{ text, links: [{ label: 'openFDA', url: 'https://api.fda.gov/device/event.json' }] }], withheld: [], spoken_text: text },
  suggestions: ['Next question?'],
  research: { label: 'Web research', items: [{ title: 'A page', url: 'https://example.org/a', snippet: 's' }] } as unknown as AskResponse['research'],
})

const turn = (id: number, q: string, a = 'An answer.', extra: Partial<LiveTurn> = {}): LiveTurn => ({
  id,
  via: 'text',
  question: q,
  status: 'done',
  resp: resp(a),
  ...extra,
})

function memStore(initial: Record<string, string> = {}) {
  const m = new Map(Object.entries(initial))
  return {
    m,
    read: (k: string) => m.get(k) ?? null,
    write: (k: string, v: string) => void m.set(k, v),
  }
}

describe('titles', () => {
  it('uses the first question, cut near 48 characters at a word', () => {
    expect(autoTitle([turn(1, 'Short question?')])).toBe('Short question?')
    const long = 'What changed this week? Did reports suddenly increase for any device in the sweep?'
    const t = autoTitle([turn(1, long)])
    expect(t.length).toBeLessThanOrEqual(49)
    expect(t.endsWith('…')).toBe(true)
    expect(long.startsWith(t.slice(0, -1))).toBe(true)
  })
  it('names a photo or a voice turn without a question', () => {
    expect(autoTitle([{ id: 1, via: 'photo', question: null, status: 'pending' }])).toBe('Photo of a device label')
    expect(autoTitle([{ id: 1, via: 'voice', question: null, status: 'pending' }])).toBe('Spoken question')
  })
  it('collapses white space', () => {
    expect(trimTitle('  a \n  b  ')).toBe('a b')
  })
})

describe('save and restore', () => {
  it('saves a chat and reads back exactly the same turns (answers, chips, research, recorded label)', () => {
    const store = memStore()
    const turns = [turn(1, 'First?', 'One.'), { ...turn(2, 'Second?', 'Two.'), resp: resp('Two.', 'recorded') }]
    saveChats(upsertChat([], 'c1', turns, 1000), store)
    const back = loadChats(store)
    expect(back).toHaveLength(1)
    expect(back[0].id).toBe('c1')
    expect(back[0].title).toBe('First?')
    expect(back[0].turns).toEqual(turns)
    expect(back[0].turns[1].resp?.mode).toBe('recorded')
    expect(back[0].turns[0].resp?.suggestions).toEqual(['Next question?'])
    expect(back[0].turns[0].resp?.research).toBeTruthy()
  })
  it('does not keep a photo object URL, and a pending turn comes back as not answered', () => {
    const store = memStore()
    const photo: LiveTurn = { id: 3, via: 'photo', question: null, status: 'pending', image: 'blob:http://x/1' }
    expect(storableTurn(photo).image).toBeUndefined()
    saveChats(upsertChat([], 'c1', [turn(1, 'Q?'), { ...turn(2, 'Waiting?'), status: 'pending', resp: undefined }, photo], 5), store)
    expect(store.m.get(CHATS_KEY)).not.toContain('blob:')
    const back = loadChats(store)[0].turns
    expect(back[1].status).toBe('error')
    expect(back[1].error).toBe(PENDING_NOTE)
    expect(back[2].image).toBeUndefined()
  })
  it('newest first; an unchanged chat keeps its place', () => {
    let chats = upsertChat([], 'a', [turn(1, 'A?')], 1)
    chats = upsertChat(chats, 'b', [turn(2, 'B?')], 2)
    expect(chats.map((c) => c.id)).toEqual(['b', 'a'])
    const same = upsertChat(chats, 'a', [turn(1, 'A?')], 3)
    expect(same).toBe(chats)
    chats = upsertChat(chats, 'a', [turn(1, 'A?'), turn(4, 'More?')], 4)
    expect(chats.map((c) => c.id)).toEqual(['a', 'b'])
    expect(chats[0].updatedAt).toBe(4)
  })
  it('an empty conversation is never saved', () => {
    expect(upsertChat([], 'a', [], 1)).toEqual([])
  })
  it('a late answer is saved into its own chat', () => {
    let chats = upsertChat([], 'a', [{ ...turn(7, 'Slow?'), status: 'pending', resp: undefined }], 1)
    chats = upsertChat(chats, 'b', [turn(8, 'Other?')], 2)
    chats = patchTurn(chats, 'a', 7, { status: 'done', resp: resp('Late.') }, 3)
    const a = chats.find((c) => c.id === 'a')!
    expect(a.turns[0].status).toBe('done')
    expect(a.turns[0].resp?.answer.speakable[0].text).toBe('Late.')
    expect(patchTurn(chats, 'a', 99, { status: 'error' }, 4)).toBe(chats)
  })
})

describe('rename and delete', () => {
  it('rename sticks; later questions do not overwrite it', () => {
    let chats = upsertChat([], 'a', [turn(1, 'Original?')], 1)
    chats = renameChat(chats, 'a', '  My   name ')
    expect(chats[0].title).toBe('My name')
    expect(chats[0].titleEdited).toBe(true)
    chats = upsertChat(chats, 'a', [turn(1, 'Original?'), turn(2, 'Another?')], 2)
    expect(chats[0].title).toBe('My name')
    expect(renameChat(chats, 'a', '   ')).toBe(chats)
  })
  it('delete removes only that chat', () => {
    let chats = upsertChat([], 'a', [turn(1, 'A?')], 1)
    chats = upsertChat(chats, 'b', [turn(2, 'B?')], 2)
    expect(deleteChat(chats, 'a').map((c) => c.id)).toEqual(['b'])
  })
})

describe('caps', () => {
  it(`keeps at most ${MAX_CHATS} chats, dropping the oldest`, () => {
    let chats: SavedChat[] = []
    for (let i = 0; i < MAX_CHATS + 5; i++) chats = upsertChat(chats, `c${i}`, [turn(i + 1, `Q${i}?`)], i)
    const kept = capChats(chats)
    expect(kept).toHaveLength(MAX_CHATS)
    expect(kept.some((c) => c.id === 'c0')).toBe(false)
    expect(kept[0].id).toBe(`c${MAX_CHATS + 4}`)
  })
  it('keeps the list under the size cap, dropping the oldest', () => {
    const big = 'x'.repeat(4000)
    let chats: SavedChat[] = []
    for (let i = 0; i < 10; i++) chats = upsertChat(chats, `c${i}`, [turn(i + 1, `Q${i}?`, big)], i)
    const kept = capChats(chats, 50, 20_000)
    expect(kept.length).toBeLessThan(10)
    expect(kept.length).toBeGreaterThan(0)
    expect(kept[0].id).toBe('c9')
    expect(JSON.stringify({ v: 1, chats: kept }).length).toBeLessThanOrEqual(20_000)
  })
  it('a single chat larger than the cap loses its oldest turns', () => {
    const big = 'y'.repeat(3000)
    const turns = Array.from({ length: 10 }, (_, i) => turn(i + 1, `Q${i}?`, big))
    const kept = capChats(upsertChat([], 'a', turns, 1), 50, 10_000)
    expect(kept).toHaveLength(1)
    expect(kept[0].turns.length).toBeLessThan(10)
    expect(kept[0].turns.at(-1)?.id).toBe(10)
  })
})

describe('corrupt or blocked storage', () => {
  it.each([
    ['not JSON', '{oops'],
    ['wrong version', JSON.stringify({ v: 2, chats: [] })],
    ['not an object', JSON.stringify([1, 2])],
    ['chats not a list', JSON.stringify({ v: 1, chats: 'x' })],
  ])('%s gives an empty list', (_, raw) => {
    expect(parseChats(raw)).toEqual([])
  })
  it('drops broken chats and broken turns, keeps the good ones', () => {
    const good = upsertChat([], 'ok', [turn(1, 'Fine?')], 1)[0]
    const raw = JSON.stringify({
      v: 1,
      chats: [
        good,
        { id: 'no-turns', title: 't', turns: [] },
        { id: 7, title: 't', turns: [turn(2, 'x')] },
        { id: 'half', title: 'Half', createdAt: 1, updatedAt: 1, turns: [turn(3, 'Kept?'), { id: 'x' }, { id: 4, via: 'text', status: 'done', question: 'no answer' }] },
        good,
      ],
    })
    const out = parseChats(raw)
    expect(out.map((c) => c.id).sort()).toEqual(['half', 'ok'])
    expect(out.find((c) => c.id === 'half')!.turns.map((t) => t.id)).toEqual([3])
  })
  it('an empty store reads as no chats', () => {
    expect(loadChats(memStore())).toEqual([])
  })
  it('the real localStorage wrapper survives a throwing localStorage', () => {
    const g = globalThis as unknown as { window?: unknown }
    const had = 'window' in g
    const prev = g.window
    g.window = {
      get localStorage(): Storage {
        throw new Error('blocked')
      },
    }
    try {
      expect(loadChats()).toEqual([])
      expect(() => saveChats(upsertChat([], 'a', [turn(1, 'Q?')], 1))).not.toThrow()
    } finally {
      if (had) g.window = prev
      else delete g.window
    }
  })
})

describe('search', () => {
  const chats = [
    ...upsertChat([], 'a', [turn(1, 'Recalls for LLZ?', 'Three recalls were found: Z-0186-2027 and two more.')], 1),
    ...upsertChat([], 'b', [turn(2, 'MHRA alerts?', 'One alert about imaging software.')], 2),
  ]
  it('finds titles and text, case-insensitive', () => {
    expect(searchChats(chats, 'llz').map((h) => h.chat.id)).toEqual(['a'])
    const hit = searchChats(chats, 'imaging software')
    expect(hit.map((h) => h.chat.id)).toEqual(['b'])
    expect(hit[0].snippet.toLowerCase()).toContain('imaging software')
    expect(searchChats(chats, 'z-0186')[0].chat.id).toBe('a')
    expect(searchChats(chats, 'nothing like this')).toEqual([])
    expect(searchChats(chats, '  ')).toHaveLength(2)
  })
  it('chat text holds the title, questions and answer sentences', () => {
    expect(chatText(chats[0])).toContain('Three recalls')
  })
})

it('chat ids are URL-safe and different each time', () => {
  const a = newChatId()
  const b = newChatId()
  expect(a).toMatch(/^[a-z0-9]+$/)
  expect(a).not.toBe(b)
})
