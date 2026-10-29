import { useEffect, useState } from 'react'
import { ArtifactsPane } from './components/ArtifactsPane'
import { ChatPane, type View } from './components/ChatPane'
import { CommandPalette } from './components/CommandPalette'
import { Header } from './components/Header'
import { Sidebar } from './components/Sidebar'
import { useWorkspaceData } from './data'
import { useReadBriefs, useTheme } from './storage'
import type { WorkflowId } from './types'

const isDesktop = () => window.matchMedia('(min-width: 1024px)').matches

export default function App() {
  const { data, error } = useWorkspaceData()
  const { theme, next } = useTheme()
  const { isRead, markRead } = useReadBriefs()
  const [view, setView] = useState<View>({ kind: 'new' })
  const [briefDate, setBriefDate] = useState<string | null>(null)
  const [drawer, setDrawer] = useState(false) // phone sidebar drawer
  const [collapsed, setCollapsed] = useState(false) // desktop sidebar
  const [artifacts, setArtifacts] = useState(isDesktop)
  const [palette, setPalette] = useState(false)

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

  const toggleSidebar = () => {
    if (window.matchMedia('(min-width: 768px)').matches) setCollapsed((c) => !c)
    else setDrawer((o) => !o)
  }
  const openWorkflow = (id: WorkflowId) => {
    setView({ kind: 'workflow', id })
    setDrawer(false)
  }
  const openBrief = (date: string) => {
    setBriefDate(date)
    markRead(date)
    setArtifacts(true)
    setDrawer(false)
  }

  if (error)
    return (
      <div className="p-6">
        <p className="ms-banner ms-banner--err">
          The stored data could not be loaded ({error}). Run <code>python3 scripts/export_web_data.py</code>.
        </p>
      </div>
    )

  const brief = data?.briefs.find((b) => b.date === briefDate) ?? null
  const recordedRuns = data?.investigations.investigations.length ?? 0
  const activeWorkflow: WorkflowId | null =
    view.kind === 'workflow'
      ? view.id
      : view.kind === 'thread'
        ? ((data?.threads.threads.find((t) => t.id === view.id)?.workflow as WorkflowId | undefined) ?? null)
        : null

  return (
    <div className="flex h-full flex-col">
      <Header
        manifest={data?.manifest ?? null}
        theme={theme}
        sidebarOpen={drawer}
        artifactsOpen={artifacts}
        onToggleSidebar={toggleSidebar}
        onToggleArtifacts={() => setArtifacts((o) => !o)}
        onTheme={next}
        onPalette={() => setPalette(true)}
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
            recordedRuns={recordedRuns}
            activeWorkflow={activeWorkflow}
            activeBrief={briefDate}
            isRead={isRead}
            onNewChat={() => {
              setView({ kind: 'new' })
              setDrawer(false)
            }}
            onWorkflow={openWorkflow}
            onBrief={openBrief}
            onClose={() => setDrawer(false)}
          />
          <ChatPane
            view={view}
            threads={data.threads}
            investigationNotes={data.investigations.notes}
            recordedRuns={recordedRuns}
            onWorkflow={openWorkflow}
            onThread={(id) => setView({ kind: 'thread', id })}
          />
          <ArtifactsPane open={artifacts} brief={brief} onClose={() => setArtifacts(false)} />
        </div>
      )}
      <CommandPalette open={palette} onClose={() => setPalette(false)} onWorkflow={openWorkflow} />
    </div>
  )
}
