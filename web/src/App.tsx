import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { producedTabs, relatedTabs, type TabId } from './artifacts'
import { alertItems, NEEDS_REVIEW, sweepRowId } from './dashboard'
import { ArtifactsPane } from './components/ArtifactsPane'
import { ChatPane, type View, type WithheldNav } from './components/ChatPane'
import type { CaptureMode } from './capture'
import { CommandPalette } from './components/CommandPalette'
import { AlertPanel } from './components/AlertPanel'
import { FeedbackDialog } from './components/FeedbackDialog'
import { Header } from './components/Header'
import { MiniPane, miniTitle } from './components/MiniDashboard'
import { PanelNav } from './components/PanelBar'
import { Sidebar } from './components/Sidebar'
import type { VisionSel } from './components/VisionWorkflow'
import { AlertPanelContext } from './alertPanelContext'
import { findAlert, chatQuestion, type AlertDetail } from './alerts'
import { withheldSentences } from './claims'
import { closestThread } from './match'
import { storedMentions } from './mentions'
import { useWorkspaceData, visibleWorkflows } from './data'
import { apiBaseOrNull, resolveRef, sendVisit, sessionStore } from './feedback'
import { useReadBriefs, useTheme } from './storage'
import { useLiveChat } from './live/useLiveChat'
import { collapseOnEscape, toggleExpanded, type PanelId } from './layout'
import type { WorkflowId } from './types'

const API_BASE = apiBaseOrNull(import.meta.env.VITE_MAUDESIGNAL_API_BASE)

/** A short name for the open view, e.g. "thread:06-trap"; sent with feedback and visit pings. */
export function pageName(view: View): string {
  if (view.kind === 'new') return 'new'
  if (view.kind === 'capture') return `capture:${view.mode}`
  if (view.kind === 'live') return 'live'
  if (view.kind === 'connect') return 'connect'
  return `${view.kind}:${view.id}`
}

// A thread opens the artifacts pane by itself only on a wide screen; on a narrower one the chat keeps the room.
const isWide = () => window.matchMedia('(min-width: 1600px)').matches

/** True from 768px up (desktop sidebar collapses; below that it is a drawer). Follows resize and rotation. */
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

export default function App() {
  const { data, error } = useWorkspaceData()
  const { theme, next } = useTheme()
  const { isRead, markRead } = useReadBriefs()
  const [view, setView] = useState<View>({ kind: 'new' })
  const [briefDate, setBriefDate] = useState<string | null>(null)
  const [drawer, setDrawer] = useState(false) // phone sidebar drawer
  const [collapsed, setCollapsed] = useState(false) // desktop sidebar
  const [artifacts, setArtifacts] = useState(false) // home is a full dashboard; a thread opens the pane
  const [expanded, setExpanded] = useState<PanelId | null>(null) // the one panel shown full screen
  const [palette, setPalette] = useState(false)
  const [feedback, setFeedback] = useState(false)
  // ?r=CODE from the person's link, kept for the session (other URL parameters are left alone).
  const [refCode] = useState(() => resolveRef(window.location.search, sessionStore()))
  const page = pageName(view)
  // The open alert panel (side sheet / full screen) and the element that had focus when it opened.
  const [panel, setPanel] = useState<{ id: string; code?: string } | null>(null)
  const panelReturn = useRef<HTMLElement | null>(null)
  // The live conversation lives here so it survives opening other screens. Without an API address it is switched off.
  const live = useLiveChat({
    apiBase: API_BASE,
    ref: refCode,
    threads: data?.threads.threads ?? [],
    evidence: data?.evidence ?? { reports: {}, other: {} },
  })
  useEffect(() => {
    sendVisit(
      API_BASE,
      refCode,
      page,
      sessionStore(),
      {
        fetcher: (u, init) => fetch(u, init),
      },
    )
  }, [page, refCode])
  const desktop = useIsDesktop()
  // The sweep row an alert link points at (nonce so the same row can be opened again).
  const [sweepFocus, setSweepFocus] = useState<{ code: string; nonce: number } | null>(null)
  // The newest real data (the AI device sweep) is what the artifacts pane opens on.
  const [tab, setTab] = useState<TabId>('digest')
  // Which withheld sentence the top strip opened (index into the list of all withheld sentences).
  const [wIdx, setWIdx] = useState<number | null>(null)
  const [visionSel, setVisionSel] = useState<(VisionSel & { nonce: number }) | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPalette((o) => !o)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (view.kind === 'new') setExpanded((c) => (c === 'mini' ? null : c)) // the mini-dashboard only exists inside a workflow
  }, [view.kind])

  useEffect(() => {
    if (!expanded) return
    const onKey = (e: KeyboardEvent) => {
      // Esc closes an open popover (bell list) first; the panel collapses on the next Esc.
      if (e.key === 'Escape' && document.querySelector('[data-popover-open]')) return
      setExpanded((cur) => collapseOnEscape(cur, e.key))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expanded])

  // The browser's Back button collapses an expanded panel (one history entry per expansion).
  const wasExpanded = useRef(false)
  useEffect(() => {
    const onPop = () => setExpanded(null)
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  useEffect(() => {
    if (expanded && !wasExpanded.current) window.history.pushState({ msExpanded: true }, '')
    else if (!expanded && wasExpanded.current && (window.history.state as { msExpanded?: boolean } | null)?.msExpanded)
      window.history.back()
    wasExpanded.current = !!expanded
  }, [expanded])

  useEffect(() => {
    if (!sweepFocus) return
    const id = window.setTimeout(() => {
      const el = document.getElementById(sweepRowId(sweepFocus.code))
      el?.scrollIntoView({ block: 'center' })
      el?.focus({ preventScroll: true })
    }, 50)
    return () => window.clearTimeout(id)
  }, [sweepFocus, expanded])

  const withheldRefs = useMemo(() => (data ? withheldSentences(data.threads.threads) : []), [data])

  const toggleSidebar = () => {
    if (desktop) setCollapsed((c) => !c)
    else setDrawer((o) => !o)
  }
  const openThread = useCallback((id: string) => {
    setWIdx(null)
    setView({ kind: 'thread', id })
  }, [])
  const openWorkflow = (id: WorkflowId) => {
    setWIdx(null)
    // A workflow with stored threads opens its first thread; the others open their own page.
    const first = data?.threads.workflows.find((w) => w.id === id)?.thread_ids[0]
    setView(first ? { kind: 'thread', id: first } : { kind: 'workflow', id })
    if (id === 'vision') setTab('vision')
    if (id === 'ai-sweep') setTab('digest')
    setDrawer(false)
  }
  const openCode = (code: string) => {
    setWIdx(null)
    setView({ kind: 'workflow', id: 'check-device', code })
    setDrawer(false)
  }
  // Our devices: the status the table is filtered to (null: all). Set from the chips, the left column, the bars and the bell.
  const [deviceFilter, setDeviceFilter] = useState<string | null>(null)
  /** Shows the table filtered to one status (from anywhere in the workflow, or from the bell). */
  const filterDevices = (label: string | null) => {
    setDeviceFilter(label)
    setExpanded((c) => (c === 'mini' ? null : c))
    setWIdx(null)
    setView({ kind: 'workflow', id: 'our-devices' })
    setDrawer(false)
  }
  const openDevice = (id: string | null) => {
    setWIdx(null)
    setView(id ? { kind: 'workflow', id: 'our-devices', code: id } : { kind: 'workflow', id: 'our-devices' })
    setDrawer(false)
  }
  const openCapture = (mode: CaptureMode) => {
    setWIdx(null)
    setView({ kind: 'capture', mode })
    setDrawer(false)
  }
  const openRun = (id: string) => {
    setWIdx(null)
    setView({ kind: 'run', id })
  }
  const openWithheld = (i: number) => {
    const ref = withheldRefs[i]
    if (!ref) return
    setWIdx(i)
    setView({ kind: 'thread', id: ref.threadId })
    setDrawer(false)
  }
  const openBrief = (date: string) => {
    setBriefDate(date)
    setTab('brief')
    markRead(date)
    setArtifacts(true)
    setDrawer(false)
  }
  const openVision = (sel: VisionSel) => {
    setVisionSel((cur) => ({ ...sel, nonce: (cur?.nonce ?? 0) + 1 }))
    setTab('vision')
    setArtifacts(true)
  }

  /** Where an alert lives in the workspace, from its id: the sweep row, the brief or the device. */
  const showAlertById = (id: string, code?: string) => {
    const [kind, a, b] = id.split(':')
    if (kind === 'brief' && a) openBrief(a)
    else if (kind === 'company' && a) openDevice(a)
    else {
      openWorkflow('ai-sweep')
      setExpanded('mini')
      setSweepFocus((cur) => ({ code: a ?? code ?? b ?? '', nonce: (cur?.nonce ?? 0) + 1 }))
    }
  }
  /** Opens the detail panel of an alert and remembers what had focus so it can be given back. */
  const openAlertPanel = useCallback((id: string, code?: string) => {
    const el = document.activeElement
    panelReturn.current = el instanceof HTMLElement && el !== document.body ? el : null
    setPanel({ id, code })
  }, [])
  const closeAlertPanel = useCallback(() => {
    setPanel(null)
    const el = panelReturn.current
    panelReturn.current = null
    // The list the click came from may be gone (the bell closes itself): fall back to the bell.
    window.setTimeout(() => {
      const target = el && el.isConnected ? el : document.querySelector<HTMLElement>('[data-testid="alert-bell"]')
      target?.focus()
    }, 0)
  }, [])
  const openInChat = (a: Pick<AlertDetail, 'product_code' | 'rule'>) => {
    const q = chatQuestion(a)
    setPanel(null)
    panelReturn.current = null
    setWIdx(null)
    setDrawer(false)
    if (live.enabled) {
      const refused = live.ask(q, { productCode: a.product_code })
      setView(refused ? { kind: 'new' } : { kind: 'live' })
      return
    }
    // No API: the closest stored run answers (recorded fallback).
    const m = data ? closestThread(q, data.threads.threads) : null
    if (m) setView({ kind: 'thread', id: m.thread.id })
    else setView({ kind: 'new' })
  }
  const openConnect = () => {
    setWIdx(null)
    setView({ kind: 'connect' })
    setDrawer(false)
  }
  const panelApi = useMemo(
    () => ({ openAlert: openAlertPanel, apiBase: API_BASE, mentionsFor: (code: string) => storedMentions(data?.mentions, code) }),
    [openAlertPanel, data?.mentions],
  )
  const goHome = () => {
    setExpanded(null)
    setSweepFocus(null)
    setWIdx(null)
    setView({ kind: 'new' })
    setDrawer(false)
  }
  const toggle = (p: PanelId) => setExpanded((cur) => toggleExpanded(cur, p))

  const thread = (view.kind === 'thread' && data?.threads.threads.find((t) => t.id === view.id)) || null
  const produced = useMemo(() => producedTabs(thread), [thread])

  const related = useMemo(() => relatedTabs(thread), [thread])

  // A thread opens the artifact most related to it (on desktop; on a phone the sheet stays closed and the tab gets a dot).
  const threadKey = thread?.id ?? null
  useEffect(() => {
    if (!threadKey) return
    const first = related[0]
    if (first) {
      setTab(first)
      if (isWide()) setArtifacts(true)
    }
  }, [threadKey]) // eslint-disable-line react-hooks/exhaustive-deps

  if (error)
    return (
      <div className="p-6">
        <p className="ms-banner ms-banner--err">
          The stored data could not be loaded ({error}). Run <code>python3 scripts/export_web_data.py</code>.
        </p>
      </div>
    )

  const runs = data?.investigations.investigations ?? []
  const activeWorkflow: WorkflowId | null =
    view.kind === 'workflow'
      ? view.id
      : view.kind === 'run'
        ? (runs.find((r) => r.id === view.id)?.kind ?? null)
        : view.kind === 'thread'
          ? ((data?.threads.threads.find((t) => t.id === view.id)?.workflow as WorkflowId | undefined) ?? null)
          : null

  const withheld: WithheldNav | null =
    wIdx !== null && withheldRefs[wIdx]
      ? {
          highlight: withheldRefs[wIdx],
          pos: wIdx + 1,
          total: withheldRefs.length,
          onNext: () => openWithheld((wIdx + 1) % withheldRefs.length),
        }
      : null

  return (
    <AlertPanelContext.Provider value={panelApi}>
    <PanelNav.Provider value={{ onHome: goHome, workflow: activeWorkflow ? miniTitle(activeWorkflow) : null }}>
    <div className="flex h-full flex-col">
      <Header
        manifest={data?.manifest ?? null}
        theme={theme}
        sidebarOpen={desktop ? !collapsed : drawer}
        alerts={data ? alertItems(data.sweep, data.briefs, data.company) : []}
        companyBanner={data?.company.banner}
        onAlert={(a) => openAlertPanel(a.id, a.productCode)}
        onViewAll={(group) => (group === 'devices' ? filterDevices(NEEDS_REVIEW) : openWorkflow('ai-sweep'))}
        artifactsOpen={artifacts}
        onToggleSidebar={toggleSidebar}
        onToggleArtifacts={() => setArtifacts((o) => !o)}
        onTheme={next}
        onPalette={() => setPalette(true)}
        onFeedback={() => setFeedback(true)}
        onConnect={openConnect}
        onWithheld={withheldRefs.length > 0 ? () => openWithheld(0) : undefined}
      />
      {data && (
        <div className="flex min-h-0 flex-1">
          <Sidebar
            open={drawer}
            collapsed={collapsed}
            threads={data.threads}
            briefs={data.briefs}
            sources={data.sources}
            schedules={data.schedules}
            runs={runs}
            vision={data.vision}
            sweep={data.sweep}
            company={data.company}
            activeWorkflow={activeWorkflow}
            activeBrief={briefDate}
            isRead={isRead}
            onNewChat={() => {
              setWIdx(null)
              setView({ kind: 'new' })
              setDrawer(false)
            }}
            onWorkflow={openWorkflow}
            onBrief={openBrief}
            onClose={() => setDrawer(false)}
          />
          <div className="flex min-h-0 min-w-0 flex-1 flex-col lg:flex-row">
            {activeWorkflow && (
              <div className={artifacts ? 'contents lg:max-2xl:hidden' : 'contents'} data-testid="mini-wrap">
              <MiniPane
                key={activeWorkflow}
                workflow={activeWorkflow}
                data={data}
                expanded={expanded === 'mini'}
                onToggleExpand={() => toggle('mini')}
                onThread={openThread}
                onRun={openRun}
                focusCode={sweepFocus?.code ?? null}
                deviceFilter={deviceFilter}
                onDeviceFilter={filterDevices}
                activeId={view.kind === 'thread' || view.kind === 'run' ? view.id : null}
              />
              </div>
            )}
            <ChatPane
              view={view}
              data={data}
              withheld={withheld}
              onWorkflow={openWorkflow}
              onThread={openThread}
              onRun={openRun}
              onVision={openVision}
              onCode={openCode}
              onDevice={openDevice}
              deviceFilter={deviceFilter}
              onDeviceFilter={filterDevices}
              onCapture={openCapture}
              live={live}
              onLive={() => {
                setWIdx(null)
                setView({ kind: 'live' })
                setDrawer(false)
              }}
              onBrief={openBrief}
              onAlert={(a) => openAlertPanel(a.id, a.productCode)}
              apiBase={API_BASE}
              expanded={expanded === 'main'}
              onToggleExpand={() => toggle('main')}
            />
          </div>
          <ArtifactsPane
            open={artifacts}
            data={data}
            tab={tab}
            onTab={setTab}
            thread={thread}
            produced={produced}
            briefDate={briefDate}
            onBriefDate={setBriefDate}
            vision={visionSel}
            onClose={() => {
              setArtifacts(false)
              setExpanded((c) => (c === 'artifacts' ? null : c))
            }}
            expanded={expanded === 'artifacts'}
            onToggleExpand={() => toggle('artifacts')}
          />
        </div>
      )}
      <FeedbackDialog
        open={feedback}
        onClose={() => setFeedback(false)}
        apiBase={API_BASE}
        refCode={refCode}
        page={page}
      />
      <CommandPalette
        open={palette}
        onClose={() => setPalette(false)}
        onWorkflow={openWorkflow}
        workflows={visibleWorkflows(runs)}
      />
    </div>
      {panel && (
        <AlertPanel
          detail={findAlert(data?.alerts, panel.id, panel.code)}
          fallbackCode={panel.code}
          onClose={closeAlertPanel}
          onShow={() => {
            const p = panel
            setPanel(null)
            panelReturn.current = null
            showAlertById(p.id, p.code)
          }}
          onOpenInChat={openInChat}
          apiBase={API_BASE}
          mentions={storedMentions(data?.mentions, findAlert(data?.alerts, panel.id, panel.code)?.product_code ?? panel.code ?? '')}
        />
      )}
    </PanelNav.Provider>
    </AlertPanelContext.Provider>
  )
}
