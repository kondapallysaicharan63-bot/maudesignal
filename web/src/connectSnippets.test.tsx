// @vitest-environment jsdom
// DOM tests: the copy-paste config snippets and the example questions on the Connect page.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ConnectView } from './components/ConnectView'
import { configSnippets, FALLBACK_INFO, KEY_PLACEHOLDER, EXAMPLE_QUESTIONS } from './connect'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const URL_MCP = 'https://maudesignal-api.vercel.app/mcp'
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
const q = (id: string) => host.querySelector(`[data-testid="${id}"]`)
const tick = async () => {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0))
  })
}

describe('config snippets', () => {
  it('without a demo key: the placeholder, valid JSON, right URL and header', () => {
    act(() => root.render(<ConnectView apiBase={null} />))
    const desktop = JSON.parse(q('code-claude-desktop')!.textContent!)
    expect(desktop.mcpServers.maudesignal.command).toBe('npx')
    expect(desktop.mcpServers.maudesignal.args).toEqual(['mcp-remote', URL_MCP, '--header', `X-API-Key:${KEY_PLACEHOLDER}`])
    const cursor = JSON.parse(q('code-cursor')!.textContent!)
    expect(cursor.mcpServers.maudesignal.url).toBe(URL_MCP)
    expect(cursor.mcpServers.maudesignal.headers).toEqual({ 'X-API-Key': KEY_PLACEHOLDER })
    const muse = q('code-muse')!.textContent!
    expect(muse).toContain(`MCP URL: ${URL_MCP}`)
    expect(muse).toContain('Header: X-API-Key')
    expect(muse).toContain(`Value: ${KEY_PLACEHOLDER}`)
  })
  it('each snippet has a one-line where-to-paste note and a Copy button', () => {
    act(() => root.render(<ConnectView apiBase={null} />))
    for (const id of ['claude-desktop', 'cursor', 'muse']) {
      expect(q(`where-${id}`)!.textContent!.length).toBeGreaterThan(20)
    }
    expect(q('where-claude-desktop')!.textContent).toContain('claude_desktop_config.json')
    expect(q('where-cursor')!.textContent).toContain('.cursor/mcp.json')
    expect(host.querySelectorAll('[data-testid=config-snippets] button')).toHaveLength(3)
  })
  it('with the demo key from /v1/connect: it fills the key in all three, still valid JSON', async () => {
    const f = vi.fn(async () => new Response(JSON.stringify({ demo_key: 'demo-123', auth_header: 'X-API-Key' }), { status: 200 }))
    act(() => root.render(<ConnectView apiBase="https://a.test" fetcher={f} />))
    await tick()
    expect(JSON.parse(q('code-claude-desktop')!.textContent!).mcpServers.maudesignal.args[3]).toBe('X-API-Key:demo-123')
    expect(JSON.parse(q('code-cursor')!.textContent!).mcpServers.maudesignal.headers['X-API-Key']).toBe('demo-123')
    expect(q('code-muse')!.textContent).toContain('Value: demo-123')
    expect(host.textContent).not.toContain(KEY_PLACEHOLDER)
  })
  it('Copy puts exactly the snippet text on the clipboard', async () => {
    const copy = vi.fn(async () => undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: copy }, configurable: true })
    act(() => root.render(<ConnectView apiBase={null} />))
    for (const [id, tid] of [['claude-desktop', 'copy-claude-desktop-config'], ['cursor', 'copy-cursor-config'], ['muse', 'copy-meta-muse-config']]) {
      await act(async () => (q(tid) as HTMLButtonElement).click())
      expect(copy).toHaveBeenLastCalledWith(q(`code-${id}`)!.textContent)
    }
    expect(q('copy-claude-desktop-config')!.textContent).toBe('Copied')
  })
  it('keeps the steps, status line, limits note, privacy and terms links; lists the example questions', () => {
    act(() => root.render(<ConnectView apiBase={null} />))
    expect(host.querySelectorAll('[data-testid=connect-steps] li')).toHaveLength(3)
    expect(q('connect-status')!.textContent).toContain("Submitted to Meta's Muse Connector Program — pending review.")
    expect(q('no-demo-key')!.textContent).toContain('rate-limited')
    expect(q('link-privacy')).not.toBeNull()
    expect(q('link-terms')).not.toBeNull()
    expect(EXAMPLE_QUESTIONS.map((p) => p.title)).toEqual(['What changed this week for LLZ?', 'Check product code QAS on openFDA.', 'Show recalls for LLZ.'])
    expect(host.querySelectorAll('[data-testid=example-questions] li')).toHaveLength(3)
  })
  it('configSnippets marks JSON ones', () => {
    expect(configSnippets(FALLBACK_INFO).map((s) => s.isJson)).toEqual([true, true, false])
  })
})
