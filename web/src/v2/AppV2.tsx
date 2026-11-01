// The v2 layout (?layout=v2): a calm chat-app shell around the existing views. One top bar, a sidebar with the
// sections and the saved chats, Home, four sections with subtabs, and the chat screen. Every view inside is the
// existing component; the classic layout (App.tsx) is not touched by this file.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertPanelContext } from '../alertPanelContext'
import { chatQuestion, findAlert, type AlertDetail } from '../alerts'
import type { CaptureMode } from '../capture'
import { withheldSentences } from '../claims'
import { NEEDS_REVIEW } from '../dashboard'
import { useWorkspaceData, visibleWorkflows } from '../data'
import { apiBaseOrNull, resolveRef, sendVisit, sessionStore } from '../feedback'
import type { OpenView } from '../live/api'
import { useLiveChat, type LiveChat, type LiveTurn } from '../live/useLiveChat'
import { closestThread } from '../match'
import { storedMentions } from '../mentions'
import { buildMyCompany, flaggedCodes, knownCodes } from '../myCompany'
import type { WorkflowId } from '../types'
import { MineContext, useMineState, type MineApi } from '../useMyCompany'
import { AlertPanel } from '../components/AlertPanel'
import { ArtifactsPane } from '../components/ArtifactsPane'
import { ChatPane, type View, type WithheldNav } from '../components/ChatPane'
import { FeedbackDialog } from '../components/FeedbackDialog'
import { PanelNav } from '../components/PanelBar'
import type { VisionSel } from '../components/VisionWorkflow'
import type { TabId } from '../artifacts'
import { newChatId, useChatStore } from './chatStore'
import { ChatBoundary, ChatScreen, ComposerNote, questionsLeft } from './ChatScreen'
import type { TabHow } from './SubTabs'
import { HomeV2 } from './HomeV2'
import { PmsWorkflow } from './PmsWorkflow'
import { RoiPage } from './RoiPage'
import { devicesToReview, realAlertItems } from './realAlerts'
import { InvestigateEntry } from '../investigate/entry'
import { InvestigatePage } from '../investigate/InvestigatePage'
import { hrefFor, routeName, useRoute, type Route, type Section } from './router'
import { pageItems, SearchPalette, type SearchItem } from './SearchPalette'
import { ConnectPage, DevicesPage, EvidencePage, SignalsPage } from './Sections'
import { DeviceProfilePage } from './DeviceProfile'
import { useProfiles } from './profiles'
import { SchedulesDialog } from './SchedulesDialog'
import { SidebarV2, type NavId } from './SidebarV2'
import { TopBarV2 } from './TopBarV2'
import { useThemeV2 } from './theme'
import './v2.css'

const API_BASE = apiBaseOrNull(import.meta.env.VITE_MAUDESIGNAL_API_BASE)

/** True from 768px up (sidebar beside the page; below that it is a drawer). */
function useIsDesktop(): boolean {
  const q = '(min-width: 768px)'
  const [on, setOn] = useState(() => window.matchMedia(q).matches)
  useEffect(() => {
    const mq = window.matchMedia(q)
    const h = () => setOn(mq.matches)
    h()
    mq.addEventListener('change', h)
    return () => mq.removeEventListener('change', h)
  }, [])
  return on
}

/** Where an existing workflow lives in the v2 layout (sections first; the others keep their own page). */
export function routeForWorkflow(id: WorkflowId, code?: string): Route {
  if (id === 'ai-sweep') return { page: 'signals', tab: 'alerts' }
  if (id === 'our-devices') return code ? { page: 'devices', tab: 'apply', device: code } : { page: 'devices', tab: 'apply' }
  if (id === 'capa-need-evidence') return { page: 'evidence', tab: 'capa' }
  return code ? { page: 'workflow', id, code } : { page: 'workflow', id }
}

const SECTION_HOME: Record<Section, Route> = {
  signals: { page: 'signals', tab: 'ranked' },
  devices: { page: 'devices', tab: 'apply' },
  evidence: { page: 'evidence', tab: 'capa' },
  connect: { page: 'connect', tab: 'muse' },
}

/** The sidebar entry a page belongs to (null for a chat). */
export function navOf(r: Route): NavId | null {
  if (r.page === 'home' || r.page === 'pms' || r.page === 'roi') return 'home'
  if (r.page === 'signals' || r.page === 'devices' || r.page === 'evidence' || r.page === 'connect') return r.page
  if (r.page === 'profile') return 'devices'
  if (r.page === 'workflow') {
    if (r.id === 'vision') return 'evidence'
    return 'signals'
  }
  return null
}

export default function AppV2() {
  const { data: rawData, error } = useWorkspaceData()
  const my = useMineState()
  const data = useMemo(
    () => (rawData && my.mode === 'mine' ? { ...rawData, company: buildMyCompany(my.mine, rawData.company, rawData.sweep) } : rawData),
    [rawData, my.mode, my.mine],
  )
  const mineApi = useMemo<MineApi | null>(() => {
    if (!rawData) return null
    const flagged = flaggedCodes(rawData.sweep)
    return {
      mode: my.mode,
      setMode: my.setMode,
      mine: my.mine,
      persisted: my.persisted,
      known: knownCodes(rawData.sweep, rawData.briefs, rawData.company),
      flagged,
      apiBase: API_BASE,
      setCompany: my.setCompany,
      add: (inputs) => {
        my.setMode('mine')
        my.add(inputs, flagged)
      },
      move: my.move,
      remove: my.remove,
      replace: my.replace,
      clear: my.clear,
    }
  }, [rawData, my])
  const { theme, setTheme } = useThemeV2()
  const profiles = useProfiles()
  const { route, navigate } = useRoute()
  const desktop = useIsDesktop()
  const [drawer, setDrawer] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const [search, setSearch] = useState(false)
  const [schedules, setSchedules] = useState(false)
  const closeSchedules = useCallback(() => setSchedules(false), [])
  const [feedback, setFeedback] = useState(false)
  const [refCode] = useState(() => resolveRef(window.location.search, sessionStore()))
  const page = routeName(route)
  const [panel, setPanel] = useState<{ id: string; code?: string } | null>(null)
  const panelReturn = useRef<HTMLElement | null>(null)
  const [deviceFilter, setDeviceFilter] = useState<string | null>(null)
  const [briefDate, setBriefDate] = useState<string | null>(null)
  const [wIdx, setWIdx] = useState<number | null>(null)
  const [artifacts, setArtifacts] = useState(false)
  const [tab, setTab] = useState<TabId>('vision')
  const [visionSel, setVisionSel] = useState<(VisionSel & { nonce: number }) | null>(null)
  const [recording, setRecording] = useState(false)

  // Saved chats. `chatId` is the chat whose turns are in the live conversation (null: a new chat, not saved yet).
  const store = useChatStore()
  const [chatId, setChatId] = useState<string | null>(null)
  const chatIdRef = useRef<string | null>(null)
  chatIdRef.current = chatId
  /** Which chat each turn of this page belongs to, so a late answer is saved to its own chat. */
  const owner = useRef(new Map<number, string>())
  const live = useLiveChat({
    apiBase: API_BASE,
    ref: refCode,
    threads: data?.threads.threads ?? [],
    evidence: data?.evidence ?? { reports: {}, other: {} },
    onBackground: (id, p) => {
      const c = owner.current.get(id)
      if (c) store.patch(c, id, p)
    },
  })
  const liveRef = useRef(live)
  liveRef.current = live
  // New turns are numbered after every saved one, so a late answer can never land in the wrong chat.
  useEffect(() => {
    let max = 0
    for (const c of store.chats) for (const t of c.turns) max = Math.max(max, t.id)
    if (max > 0) liveRef.current.restore(liveRef.current.turns, max)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    sendVisit(API_BASE, refCode, page, sessionStore(), { fetcher: (u, init) => fetch(u, init) })
  }, [page, refCode])

  // The address decides which chat is on screen (Recents, Back / Forward, a refresh on /chat/<id>).
  const [missing, setMissing] = useState(false)
  const routeChat = route.page === 'chat' ? route.id : undefined
  useEffect(() => {
    if (routeChat === undefined) return
    if (routeChat === null) {
      // Only a saved chat is cleared away here; a new chat's first turn (asked a moment ago) stays.
      if (chatIdRef.current !== null) {
        liveRef.current.restore([])
        chatIdRef.current = null
        setChatId(null)
      }
      setMissing(false)
      return
    }
    if (routeChat === chatIdRef.current) {
      setMissing(false)
      return
    }
    const saved = store.get(routeChat)
    if (saved) {
      for (const t of saved.turns) owner.current.set(t.id, saved.id)
      liveRef.current.restore(saved.turns)
      chatIdRef.current = saved.id
      setChatId(saved.id)
      setMissing(false)
    } else {
      liveRef.current.restore([])
      chatIdRef.current = null
      setChatId(null)
      setMissing(true)
    }
  }, [routeChat]) // eslint-disable-line react-hooks/exhaustive-deps

  // Every change to the conversation is saved; the first question gives a new chat its id and its address.
  useEffect(() => {
    const turns: LiveTurn[] = live.turns
    if (turns.length === 0) return
    let id = chatIdRef.current
    if (!id) {
      id = newChatId()
      chatIdRef.current = id
      setChatId(id)
      setMissing(false)
      navigate({ page: 'chat', id }, { replace: route.page === 'chat' })
    }
    for (const t of turns) if (!owner.current.has(t.id)) owner.current.set(t.id, id)
    store.upsert(id, turns)
  }, [live.turns]) // eslint-disable-line react-hooks/exhaustive-deps

  const go = useCallback(
    (r: Route, o?: { replace?: boolean }) => {
      setDrawer(false)
      setWIdx(null)
      navigate(r, o)
    },
    [navigate],
  )
  /** A subtab change: arrow keys replace the history entry, a click or the View menu adds one. */
  const tabGo = (r: Route, how?: TabHow) => go(r, { replace: how === 'key' })
  const newChat = useCallback(() => {
    // The chat on screen is already saved; a new one starts empty.
    liveRef.current.restore([])
    chatIdRef.current = null
    setChatId(null)
    setMissing(false)
    go({ page: 'chat', id: null })
  }, [go])
  /** Off the chat screen, a question starts a new chat (the one before stays in Recents). */
  const toChat = useCallback(() => {
    if (route.page !== 'chat') {
      liveRef.current.restore([])
      chatIdRef.current = null
      setChatId(null)
      setMissing(false)
      go({ page: 'chat', id: null })
    }
  }, [route.page, go])
  const chatLive: LiveChat = useMemo(
    () => ({
      ...live,
      ask: (q, o) => {
        if (route.page !== 'chat') {
          toChat()
        }
        return liveRef.current.ask(q, o)
      },
      askPhoto: (img, f) => {
        toChat()
        liveRef.current.askPhoto(img, f)
      },
      askVoice: async (wav) => {
        toChat()
        await liveRef.current.askVoice(wav)
      },
    }),
    [live, route.page, toChat],
  )

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setSearch((o) => !o)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const withheldRefs = useMemo(() => (data ? withheldSentences(data.threads.threads) : []), [data])
  const openWithheld = (i: number) => {
    const ref = withheldRefs[i]
    if (!ref) return
    setDrawer(false)
    navigate({ page: 'thread', id: ref.threadId })
    setWIdx(i)
  }
  const openAlertPanel = useCallback((id: string, code?: string) => {
    const el = document.activeElement
    panelReturn.current = el instanceof HTMLElement && el !== document.body ? el : null
    setPanel({ id, code })
  }, [])
  const closeAlertPanel = useCallback(() => {
    setPanel(null)
    const el = panelReturn.current
    panelReturn.current = null
    window.setTimeout(() => {
      const target = el && el.isConnected ? el : document.querySelector<HTMLElement>('[data-testid="alert-bell"]')
      target?.focus()
    }, 0)
  }, [])
  const panelApi = useMemo(
    () => ({ openAlert: openAlertPanel, apiBase: API_BASE, mentionsFor: (code: string) => storedMentions(data?.mentions, code) }),
    [openAlertPanel, data?.mentions],
  )
  const showAlertById = (id: string) => {
    const [kind, a] = id.split(':')
    if (kind === 'brief' && a) {
      setBriefDate(a)
      go({ page: 'signals', tab: 'alerts' })
    } else if (kind === 'company' && a) go({ page: 'devices', tab: 'apply', device: a })
    else go({ page: 'signals', tab: 'ranked' })
  }
  const openInChat = (a: Pick<AlertDetail, 'product_code' | 'rule'>) => {
    const q = chatQuestion(a)
    setPanel(null)
    panelReturn.current = null
    setDrawer(false)
    if (live.enabled) {
      chatLive.ask(q, { productCode: a.product_code })
      return
    }
    const m = data ? closestThread(q, data.threads.threads) : null
    if (m) go({ page: 'thread', id: m.thread.id })
  }
  const investigateApi = useMemo(() => ({ open: (code?: string) => go(code ? { page: 'investigate', code } : { page: 'investigate' }) }), [go])
  const openWorkflow = (id: WorkflowId) => go(routeForWorkflow(id))
  const openDevice = (id: string | null) => go(id ? { page: 'devices', tab: 'apply', device: id } : { page: 'devices', tab: 'apply' })
  const filterDevices = (label: string | null) => {
    setDeviceFilter(label)
    go({ page: 'devices', tab: 'apply' })
  }
  const openCapture = (mode: CaptureMode) => go({ page: 'capture', mode })
  const openVision = (sel: VisionSel) => {
    setVisionSel((cur) => ({ ...sel, nonce: (cur?.nonce ?? 0) + 1 }))
    setTab('vision')
    setArtifacts(true)
  }
  const onOpenView = (o: OpenView) => {
    if (o.view === 'check-device') go({ page: 'workflow', id: 'check-device', ...(o.code ? { code: o.code } : {}) })
    else if (o.view === 'our-devices') openDevice(null)
    else if (o.view === 'ai-sweep') go({ page: 'signals', tab: 'ranked' })
  }
  const pickSearch = (it: SearchItem) => {
    if (it.kind === 'chat') go({ page: 'chat', id: it.id })
    else if (it.kind === 'page') go(it.route)
    else openWorkflow(it.id)
  }
  const deleteChat = (id: string) => {
    store.remove(id)
    if (id === chatIdRef.current) {
      liveRef.current.restore([])
      chatIdRef.current = null
      setChatId(null)
      if (route.page === 'chat') navigate({ page: 'chat', id: null }, { replace: true })
    }
  }

  // While the phone drawer is open, the page behind it (top bar and main) is inert: focus and clicks stay in the drawer.
  const drawerOpen = drawer && !desktop
  useEffect(() => {
    const els = [document.querySelector('.ms2-topbar'), document.getElementById('main-v2')]
    for (const el of els) {
      if (!el) continue
      if (drawerOpen) el.setAttribute('inert', '')
      else el.removeAttribute('inert')
    }
  }, [drawerOpen])
  // The artifacts pane (vision readings) belongs to the workflow pages only.
  useEffect(() => {
    if (route.page !== 'workflow' && route.page !== 'thread' && route.page !== 'capture') setArtifacts(false)
  }, [route.page])
  // A new page starts at the top, and keyboard focus moves to its heading (screen readers hear the new page).
  const mainRef = useRef<HTMLDivElement>(null)
  const first = useRef(true)
  // Moving between subtabs keeps focus on the tab (arrow keys keep working); only a new page or chat moves it.
  const pageKey =
    route.page === 'chat' || route.page === 'signals' || route.page === 'evidence' || route.page === 'connect'
      ? route.page
      : route.page === 'devices'
        ? `devices:${route.device ?? ''}`
        : route.page === 'profile'
          ? `profile:${route.id}`
          : page
  useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    const t = window.setTimeout(() => {
      const h = document.querySelector<HTMLElement>('#main-v2 h1')
      if (h) {
        h.setAttribute('tabindex', '-1')
        h.focus({ preventScroll: false })
      }
    }, 0)
    return () => window.clearTimeout(t)
  }, [pageKey])

  if (error)
    return (
      <div className="p-6">
        <p className="ms-banner ms-banner--err">
          The stored data could not be loaded ({error}). Run <code>python3 scripts/export_web_data.py</code>.
        </p>
      </div>
    )

  const real = data ? realAlertItems(data) : []
  const toReview = data ? devicesToReview(data) : 0
  const devicesLabel = data?.company.mine === true ? 'Our devices (yours)' : 'Our devices (simulated)'
  const runs = data?.investigations.investigations ?? []
  const pages = pageItems(visibleWorkflows(runs), devicesLabel)
  const withheld: WithheldNav | null =
    wIdx !== null && withheldRefs[wIdx]
      ? {
          highlight: withheldRefs[wIdx],
          pos: wIdx + 1,
          total: withheldRefs.length,
          onNext: () => openWithheld((wIdx + 1) % withheldRefs.length),
        }
      : null

  // The pages with the message box use ChatPane (the existing page frame); sections are plain pages.
  let view: View | null = null
  if (route.page === 'home') view = { kind: 'new' }
  else if (route.page === 'chat') view = { kind: 'live' }
  else if (route.page === 'workflow') view = route.code ? { kind: 'workflow', id: route.id, code: route.code } : { kind: 'workflow', id: route.id }
  else if (route.page === 'thread') view = { kind: 'thread', id: route.id }
  else if (route.page === 'run') view = { kind: 'run', id: route.id }
  else if (route.page === 'capture') view = { kind: 'capture', mode: route.mode }

  const thread = route.page === 'thread' ? (data?.threads.threads.find((t) => t.id === route.id) ?? null) : null
  const left = route.page === 'chat' ? questionsLeft(live) : null

  let content: JSX.Element | null = null
  if (data && view) {
    const body =
      route.page === 'home' ? (
        <HomeV2
          data={data}
          onAlert={openAlertPanel}
          onViewAll={() => go({ page: 'signals', tab: 'alerts' })}
          onDevices={() => {
            setDeviceFilter(null)
            go({ page: 'devices', tab: 'apply' })
          }}
          onAudit={() => go({ page: 'evidence', tab: 'audit' })}
          onPms={() => go({ page: 'pms' })}
          onRoi={() => go({ page: 'roi' })}
          onInvestigate={() => go({ page: 'investigate' })}
        />
      ) : route.page === 'chat' ? (
        <ChatBoundary resetKey={chatId ?? 'new'} onDelete={chatId ? () => deleteChat(chatId) : null} onNewChat={newChat}>
        <ChatScreen
          chat={chatLive}
          threads={data.threads.threads}
          missing={missing}
          onAsk={(q) => {
            if (live.enabled) chatLive.ask(q)
            else {
              const m = closestThread(q, data.threads.threads)
              if (m) go({ page: 'thread', id: m.thread.id })
            }
          }}
          onNewChat={newChat}
          onRecordedVoice={() => openCapture('voice')}
          onRecordedLabel={() => openCapture('label')}
          onOpen={onOpenView}
        />
        </ChatBoundary>
      ) : undefined
    content = (
      <ChatPane
        key={route.page === 'chat' ? 'chat' : 'page'}
        view={view}
        data={data}
        bare
        body={body}
        withheld={withheld}
        onWorkflow={openWorkflow}
        onThread={(id) => go({ page: 'thread', id })}
        onRun={(id) => go({ page: 'run', id })}
        onVision={openVision}
        onCode={(code) => go({ page: 'workflow', id: 'check-device', code })}
        onDevice={openDevice}
        deviceFilter={deviceFilter}
        onDeviceFilter={filterDevices}
        onCapture={openCapture}
        live={chatLive}
        onLive={() => {
          if (route.page !== 'chat') go({ page: 'chat', id: chatIdRef.current })
        }}
        onBrief={(d) => {
          setBriefDate(d)
          go({ page: 'signals', tab: 'alerts' })
        }}
        onAlert={(a) => openAlertPanel(a.id, a.productCode)}
        apiBase={API_BASE}
        expanded={false}
        onToggleExpand={() => undefined}
        onRecording={setRecording}
        aboveComposer={<ComposerNote left={left} recording={recording} />}
      />
    )
  } else if (data) {
    let sectionBody: JSX.Element | null = null
    if (route.page === 'signals')
      sectionBody = (
        <SignalsPage
          data={data}
          tab={route.tab}
          onTab={(t, how) => tabGo({ page: 'signals', tab: t }, how)}
          onWorkflow={openWorkflow}
          onThread={(id) => go({ page: 'thread', id })}
          briefDate={briefDate}
          onBriefDate={setBriefDate}
        />
      )
    else if (route.page === 'devices')
      sectionBody = (
        <DevicesPage
          data={data}
          tab={route.tab}
          onTab={(t, how) => tabGo({ page: 'devices', tab: t }, how)}
          device={route.device ?? null}
          onDevice={openDevice}
          filter={deviceFilter}
          onFilter={(l) => setDeviceFilter(l)}
          onProfile={(id) => go({ page: 'profile', id, tab: 'overview' })}
        />
      )
    else if (route.page === 'profile')
      sectionBody = (
        <DeviceProfilePage
          file={profiles}
          company={data.company}
          id={route.id}
          tab={route.tab}
          onTab={(t, how) => tabGo({ page: 'profile', id: route.id, tab: t }, how)}
          onBack={() => go({ page: 'devices', tab: 'apply' })}
          onEvidence={(id) => go({ page: 'devices', tab: 'apply', device: id })}
        />
      )
    else if (route.page === 'evidence')
      sectionBody = (
        <EvidencePage
          data={data}
          tab={route.tab}
          onTab={(t, how) => tabGo({ page: 'evidence', tab: t }, how)}
          onThread={(id) => go({ page: 'thread', id })}
          onWorkflow={openWorkflow}
        />
      )
    else if (route.page === 'investigate')
      sectionBody = <InvestigatePage key={`${route.code ?? ''}|${route.device ?? ''}`} apiBase={API_BASE} code={route.code} device={route.device} />
    else if (route.page === 'connect') sectionBody = <ConnectPage tab={route.tab} onTab={(t, how) => tabGo({ page: 'connect', tab: t }, how)} apiBase={API_BASE} />
    else if (route.page === 'pms') sectionBody = <PmsWorkflow onRoi={() => go({ page: 'roi' })} onHome={() => go({ page: 'home' })} />
    else if (route.page === 'roi') sectionBody = <RoiPage onHome={() => go({ page: 'home' })} />
    const sectionLabel = route.page === 'profile' ? 'Device profile' : route.page === 'pms' ? 'PMS workflow' : route.page === 'roi' ? 'Time and cost' : route.page[0].toUpperCase() + route.page.slice(1)
    content = (
      <main className="ms2-section" aria-label={sectionLabel}>
        <div className="ms2-section-inner">{sectionBody}</div>
      </main>
    )
  }

  const navActive = navOf(route)
  return (
    <MineContext.Provider value={mineApi}>
      <InvestigateEntry.Provider value={investigateApi}>
      <AlertPanelContext.Provider value={panelApi}>
        <PanelNav.Provider value={{ onHome: () => go({ page: 'home' }), workflow: null }}>
          <div className="ms2-shell" data-layout="v2">
            <button
              type="button"
              className="ms2-skip"
              onClick={() => document.getElementById('main-v2')?.focus()}
              data-testid="skip-link"
            >
              Skip to content
            </button>
            <TopBarV2
              desktop={desktop}
              homeHref={hrefFor({ page: 'home' })}
              sidebarOpen={desktop ? !collapsed : drawer}
              onToggleSidebar={() => (desktop ? setCollapsed((c) => !c) : setDrawer((o) => !o))}
              onHome={() => go({ page: 'home' })}
              onSearch={() => setSearch(true)}
              alerts={real}
              onAlert={(a) => openAlertPanel(a.id, a.productCode)}
              onViewAll={() => go({ page: 'signals', tab: 'alerts' })}
              devicesLabel={devicesLabel}
              devicesToReview={toReview}
              onDevices={() => {
                setDeviceFilter(NEEDS_REVIEW)
                go({ page: 'devices', tab: 'apply' })
              }}
              onFeedback={() => setFeedback(true)}
            />
            <div className="ms2-body">
              <SidebarV2
                open={drawer}
                collapsed={collapsed}
                active={navActive}
                activeChat={route.page === 'chat' ? chatId : null}
                chats={store.chats}
                saved={store.saved}
                chatHref={(id) => hrefFor({ page: 'chat', id })}
                devicesLabel={devicesLabel}
                devicesToReview={toReview}
                theme={theme}
                onTheme={setTheme}
                onNewChat={newChat}
                onSearch={() => {
                  setDrawer(false)
                  setSearch(true)
                }}
                onNav={(n) => {
                  if (n === 'devices') setDeviceFilter(null)
                  go(n === 'home' ? { page: 'home' } : SECTION_HOME[n])
                }}
                onChat={(id) => go({ page: 'chat', id })}
                onRename={store.rename}
                onDelete={deleteChat}
                onSchedules={() => {
                  setDrawer(false)
                  setSchedules(true)
                }}
                onClose={() => setDrawer(false)}
              />
              <div id="main-v2" ref={mainRef} className="ms2-main" tabIndex={-1}>
                {data ? content : <p className="ms2-muted p-6" role="status">Loading stored data…</p>}
              </div>
              {data && (route.page === 'workflow' || route.page === 'thread' || route.page === 'capture') && (
                <ArtifactsPane
                  open={artifacts}
                  data={data}
                  tab={tab}
                  onTab={setTab}
                  thread={thread}
                  produced={[]}
                  briefDate={briefDate}
                  onBriefDate={setBriefDate}
                  vision={visionSel}
                  onClose={() => setArtifacts(false)}
                  expanded={false}
                  onToggleExpand={() => undefined}
                />
              )}
            </div>
            <FeedbackDialog open={feedback} onClose={() => setFeedback(false)} apiBase={API_BASE} refCode={refCode} page={page} />
            <SearchPalette open={search} onClose={() => setSearch(false)} chats={store.chats} pages={pages} onPick={pickSearch} />
            {data && <SchedulesDialog open={schedules} onClose={closeSchedules} schedules={data.schedules} sources={data.sources} />}
          </div>
          {panel && (
            <div className="ms2-scope">
            <AlertPanel
              detail={findAlert(data?.alerts, panel.id, panel.code)}
              fallbackCode={panel.code}
              onClose={closeAlertPanel}
              onShow={() => {
                const p = panel
                setPanel(null)
                panelReturn.current = null
                showAlertById(p.id)
              }}
              onOpenInChat={openInChat}
              apiBase={API_BASE}
              mentions={storedMentions(data?.mentions, findAlert(data?.alerts, panel.id, panel.code)?.product_code ?? panel.code ?? '')}
            />
            </div>
          )}
        </PanelNav.Provider>
      </AlertPanelContext.Provider>
      </InvestigateEntry.Provider>
    </MineContext.Provider>
  )
}
