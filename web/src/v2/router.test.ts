// v2 addresses: every page round-trips, the app folder is found, the query string is kept, and the layout switch.
import { describe, expect, it } from 'vitest'
import { isV2Path, layoutMode } from '../layoutFlag'
import { stripChatId, stripRef } from '../analytics'
import { appRoot, formatRoute, hrefFor, parseRoute, routeName, type Route } from './router'

const ALL: Route[] = [
  { page: 'home' },
  { page: 'chat', id: null },
  { page: 'chat', id: 'c123abc' },
  { page: 'signals', tab: 'ranked' },
  { page: 'signals', tab: 'trend' },
  { page: 'signals', tab: 'unfiled' },
  { page: 'signals', tab: 'alerts' },
  { page: 'devices', tab: 'apply' },
  { page: 'devices', tab: 'apply', device: 'DMC-03' },
  { page: 'devices', tab: 'yours' },
  { page: 'evidence', tab: 'capa' },
  { page: 'evidence', tab: 'review' },
  { page: 'evidence', tab: 'approve' },
  { page: 'evidence', tab: 'audit' },
  { page: 'connect', tab: 'muse' },
  { page: 'connect', tab: 'claude' },
  { page: 'connect', tab: 'api' },
  { page: 'workflow', id: 'check-device' },
  { page: 'workflow', id: 'check-device', code: 'LLZ' },
  { page: 'workflow', id: 'vision' },
  { page: 'thread', id: '06-trap' },
  { page: 'run', id: 'sample-weekly-LLZ' },
  { page: 'capture', mode: 'label' },
  { page: 'capture', mode: 'voice' },
]

describe('routes', () => {
  it.each(ALL.map((r) => [formatRoute(r) || '(home)', r] as const))('%s round-trips', (_, r) => {
    expect(parseRoute(`/${formatRoute(r)}`)).toEqual(r)
    expect(parseRoute(`/app/sub/${formatRoute(r)}`)).toEqual(r)
  })
  it('unknown addresses are Home; unknown tabs open the first tab', () => {
    expect(parseRoute('/')).toEqual({ page: 'home' })
    expect(parseRoute('/index.html')).toEqual({ page: 'home' })
    expect(parseRoute('/nope/x')).toEqual({ page: 'home' })
    expect(parseRoute('/signals')).toEqual({ page: 'signals', tab: 'ranked' })
    expect(parseRoute('/signals/zzz')).toEqual({ page: 'signals', tab: 'ranked' })
    expect(parseRoute('/workflow/not-a-workflow')).toEqual({ page: 'home' })
    expect(parseRoute('/chat/')).toEqual({ page: 'chat', id: null })
  })
  it('finds the app folder', () => {
    expect(appRoot('/')).toBe('/')
    expect(appRoot('/chat/abc')).toBe('/')
    expect(appRoot('/preview/chat/abc')).toBe('/preview/')
    expect(appRoot('/preview/index.html')).toBe('/preview/')
    expect(appRoot('/signals/trend')).toBe('/')
  })
  it('keeps the query string (?layout=v2, ?r=CODE, ?composer=classic) on every move', () => {
    const loc = { pathname: '/signals/trend', search: '?layout=v2&r=TEST1&composer=classic' }
    expect(hrefFor({ page: 'chat', id: 'c1' }, loc)).toBe('/chat/c1?layout=v2&r=TEST1&composer=classic')
    expect(hrefFor({ page: 'home' }, loc)).toBe('/?layout=v2&r=TEST1&composer=classic')
  })
  it('page names never carry a chat id (feedback and visit pings)', () => {
    expect(routeName({ page: 'chat', id: 'secret-id' })).toBe('chat')
    expect(routeName({ page: 'signals', tab: 'trend' })).toBe('signals:trend')
  })
  it('analytics gets /chat without the id, and no ref code', () => {
    expect(stripChatId(stripRef('https://x.app/chat/c1abc?layout=v2&r=TEST1'))).toBe('https://x.app/chat?layout=v2')
    expect(stripChatId('https://x.app/?r=1')).toBe('https://x.app/?r=1')
  })
})

describe('layout switch', () => {
  it('defaults to classic; the build flag can make v2 the default', () => {
    expect(layoutMode(undefined, '', '/')).toBe('classic')
    expect(layoutMode('classic', '', '/')).toBe('classic')
    expect(layoutMode('v2', '', '/')).toBe('v2')
    expect(layoutMode(' V2 ', '', '/')).toBe('v2')
    expect(layoutMode('something', '', '/')).toBe('classic')
  })
  it('?layout= in the address wins over the build flag', () => {
    expect(layoutMode('classic', '?layout=v2', '/')).toBe('v2')
    expect(layoutMode('v2', '?layout=classic', '/')).toBe('classic')
    expect(layoutMode('v2', '?layout=classic', '/chat/abc')).toBe('classic')
    expect(layoutMode('classic', '?r=TEST1&layout=v2', '/')).toBe('v2')
  })
  it('a v2 page address opens v2 even when the default is classic (refresh on /chat/<id>)', () => {
    expect(isV2Path('/chat/abc')).toBe(true)
    expect(isV2Path('/sub/signals')).toBe(true)
    expect(isV2Path('/')).toBe(false)
    expect(isV2Path('/chatter')).toBe(false)
    expect(layoutMode('classic', '', '/chat/abc')).toBe('v2')
    expect(layoutMode(undefined, '?r=TEST1', '/')).toBe('classic')
  })
})
