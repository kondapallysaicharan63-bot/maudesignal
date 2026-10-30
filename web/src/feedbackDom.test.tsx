// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it, vi } from 'vitest'
import { stripRef } from './analytics'
import { FeedbackDialog } from './components/FeedbackDialog'
import { EMPTY_FORM, submitFeedback } from './feedback'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

describe('analytics url', () => {
  it('drops only the personal ref code', () => {
    expect(stripRef('https://x.app/?r=dr-smith&a=1#v')).toBe('https://x.app/?a=1#v')
    expect(stripRef('https://x.app/')).toBe('https://x.app/')
    expect(stripRef('not a url')).toBe('not a url')
  })
})

describe('422 message', () => {
  const form = { ...EMPTY_FORM, rating: 3 }
  const run = (json: () => Promise<unknown>) =>
    submitFeedback('https://api.example', form, null, 'home', async () => ({ ok: false, status: 422, json }))

  it('shows the short server message', async () => {
    const r = await run(async () => ({ detail: 'comment looks like it has a patient name' }))
    expect(r.ok).toBe(false)
    expect(r.ok === false && r.message).toBe('comment looks like it has a patient name')
  })

  it('falls back when the body is missing, long or not JSON', async () => {
    for (const j of [
      async () => ({ detail: 'x'.repeat(500) }),
      async () => ({ detail: [{ msg: 'obj' }] }),
      async () => {
        throw new Error('bad json')
      },
    ]) {
      const r = await run(j)
      expect(r.ok === false && r.message).toMatch(/patient details/)
    }
  })
})

describe('mounted dialog', () => {
  it('closes on Escape even when focus is outside the dialog', async () => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    const outside = document.createElement('button')
    document.body.appendChild(outside)
    const onClose = vi.fn()
    const root = createRoot(host)
    await act(async () => {
      root.render(<FeedbackDialog open onClose={onClose} apiBase={null} refCode={null} page="home" />)
    })
    expect(document.querySelector('[role=dialog]')).not.toBeNull()
    outside.focus()
    await act(async () => {
      outside.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    })
    expect(onClose).toHaveBeenCalledTimes(1)
    await act(async () => root.unmount())
    host.remove()
    outside.remove()
  })
})
