import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { producedTabs, relatedTabs, type TabId } from './artifacts'
import { alertItems, type AlertItem } from './dashboard'
import { ArtifactsPane } from './components/ArtifactsPane'
import { ChatPane, type View, type WithheldNav } from './components/ChatPane'
import { CommandPalette } from './components/CommandPalette'
import { Header } from './components/Header'
import { MiniPane, miniTitle } from './components/MiniDashboard'
import { PanelNav } from './components/PanelBar'
import { Sidebar } from './components/Sidebar'
import type { VisionSel } from './components/VisionWorkflow'
import { withheldSentences } from './claims'
import { useWorkspaceData, visibleWorkflows } from './data'
import { useReadBriefs, useTheme } from './storage'
import { collapseOnEscape, toggleExpanded, type PanelId } from './layout'
import type { WorkflowId } from './types'

// A thread opens the artifacts pane by itself only on a wide screen; on a narrower one the chat keeps the room.
const isWide = () => window.matchMedia('(min-width: 1600px)').matches

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

  const withheldRefs = useMemo(() => (data ? withheldSentences(data.threads.threads) : []), [data])

  const toggleSidebar = () => {
    if (window.matchMedia('(min-width: 768px)').matches) setCollapsed((c) => !c)
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

  const openAlert = (a: AlertItem) => {
    if (a.source === 'brief') openBrief(a.date)
    else openWorkflow('ai-sweep')
  }
  const goHome = () => {
    setExpanded(null)
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
    <PanelNav.Provider value={{ onHome: goHome, workflow: activeWorkflow ? miniTitle(activeWorkflow) : null }}>
    <div className="flex h-full flex-col">
      <Header
        manifest={data?.manifest ?? null}
        theme={theme}
        sidebarOpen={window.matchMedia('(min-width: 768px)').matches ? !collapsed : drawer}
        alerts={data ? alertItems(data.sweep, data.briefs) : []}
        onAlert={openAlert}
        artifactsOpen={artifacts}
        onToggleSidebar={toggleSidebar}
        onToggleArtifacts={() => setArtifacts((o) => !o)}
        onTheme={next}
        onPalette={() => setPalette(true)}
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
          <div className="flex min-h-0 min-w-0 flex-1 flex-col xl:flex-row">
            {activeWorkflow && (
              <MiniPane
                key={activeWorkflow}
                workflow={activeWorkflow}
                data={data}
                expanded={expanded === 'mini'}
                onToggleExpand={() => toggle('mini')}
                onThread={openThread}
                onRun={openRun}
              />
            )}
            <ChatPane
              view={view}
              data={data}
              withheld={withheld}
              onWorkflow={openWorkflow}
              onThread={openThread}
              onRun={openRun}
              onVision={openVision}
              onBrief={openBrief}
              onAlert={openAlert}
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
      <CommandPalette
        open={palette}
        onClose={() => setPalette(false)}
        onWorkflow={openWorkflow}
        workflows={visibleWorkflows(runs)}
      />
    </div>
    </PanelNav.Provider>
  )
}
