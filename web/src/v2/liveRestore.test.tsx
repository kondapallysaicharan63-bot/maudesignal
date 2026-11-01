// @vitest-environment jsdom
// The live conversation can show a saved chat (restore), and an answer that arrives after another chat was opened is
// handed to onBackground instead of being lost or landing in the wrong chat.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { NO_LIVE, useLiveChat, type LiveChat, type LiveTurn } from '../live/useLiveChat'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let host: HTMLDivElement
let root: Root
beforeEach(() => {
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})
afterEach(() => {
  act(() => root.unmount())
  host.remove()
})

const BODY = {
  mode: 'live',
  trace: [],
  cost_usd: null,
  limits: { remaining_today: 3 },
  answer: { speakable: [{ text: 'Late answer.', links: [] }], withheld: [], spoken_text: 'Late answer.' },
}

it('restore shows saved turns; a late answer goes to onBackground; new ids follow the restored ones', async () => {
  let release: (r: Response) => void = () => undefined
  const fetcher = vi.fn(() => new Promise<Response>((res) => (release = res)))
  const background = vi.fn()
  let chat: LiveChat = NO_LIVE
  function H() {
    chat = useLiveChat({ apiBase: 'https://api.example', ref: null, threads: [], evidence: { reports: {}, other: {} }, fetcher, onBackground: background })
    return null
  }
  act(() => root.render(<H />))
  act(() => {
    chat.ask('Is this slow?')
  })
  expect(chat.turns).toHaveLength(1)
  const pendingId = chat.turns[0].id
  const saved: LiveTurn[] = [{ id: 500, via: 'text', question: 'Saved?', status: 'done' }]
  act(() => chat.restore(saved))
  expect(chat.turns).toEqual(saved)
  await act(async () => {
    release(new Response(JSON.stringify(BODY), { status: 200, headers: { 'content-type': 'application/json' } }))
    await new Promise((r) => setTimeout(r, 0))
  })
  expect(chat.turns).toEqual(saved)
  expect(background).toHaveBeenCalledTimes(1)
  expect(background.mock.calls[0][0]).toBe(pendingId)
  expect(background.mock.calls[0][1].status).toBe('done')
  act(() => {
    chat.ask('Next question?')
  })
  expect(chat.turns.at(-1)!.id).toBeGreaterThan(500)
  act(() => chat.restore([], 9000))
  act(() => {
    chat.ask('After reserve?')
  })
  expect(chat.turns.at(-1)!.id).toBeGreaterThan(9000)
})

it('the switched-off conversation has restore too', () => {
  expect(() => NO_LIVE.restore([])).not.toThrow()
})
