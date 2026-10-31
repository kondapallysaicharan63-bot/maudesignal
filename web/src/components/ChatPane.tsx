import { useMemo, useState } from 'react'
import type { CaptureMode } from '../capture'
import { knownCodes } from '../typeahead'
import { DEMO_WORKFLOWS, demoSnapshotLabel, WORKFLOWS } from '../data'
import type { AlertItem } from '../dashboard'
import { FULLSCREEN } from '../layout'
import { Icon } from '../icons'
import type { WorkflowDef, WorkflowId, WorkspaceData } from '../types'
import { ConnectView } from './ConnectView'
import { CaptureView } from './CaptureView'
import { Composer } from './Composer'
import { LiveChatView } from './LiveChat'
import { NO_LIVE, type LiveChat } from '../live/useLiveChat'
import { useRecorder } from '../live/useRecorder'
import { Dashboard } from './Dashboard'
import { RunList, RunView } from './InvestigationViews'
import { LiveCheckView } from './LiveCheckView'
import { OurDevices } from './OurDevices'
import { PanelBar } from './PanelBar'
import { SweepCard } from './SweepCard'
import { ThreadView } from './ThreadView'
import { VisionWorkflow, type VisionSel } from './VisionWorkflow'

export type View =
  | { kind: 'new' }
  | { kind: 'workflow'; id: WorkflowId; code?: string }
  | { kind: 'thread'; id: string }
  | { kind: 'run'; id: string }
  | { kind: 'capture'; mode: CaptureMode }
  | { kind: 'live' }
  | { kind: 'connect' }

/** Stable identity of the screen shown (used to scope the composer's messages). */
export const viewKey = (v: View): string =>
  v.kind === 'new' ? 'new' : v.kind === 'live' ? 'live' : v.kind === 'connect' ? 'connect' : v.kind === 'capture' ? `capture:${v.mode}` : `${v.kind}:${v.id}${v.kind === 'workflow' && v.code ? `:${v.code}` : ''}`

export interface WithheldNav {
  /** Sentence to highlight in the open thread. */
  highlight: { threadId: string; index: number }
  pos: number
  total: number
  onNext: () => void
}

interface Props {
  view: View
  data: WorkspaceData
  withheld: WithheldNav | null
  onWorkflow: (id: WorkflowId) => void
  onThread: (id: string) => void
  onRun: (id: string) => void
  onVision: (sel: VisionSel) => void
  onCode: (code: string) => void
  /** Opens one device of "Our devices (simulated)", or the table when null. */
  onDevice?: (id: string | null) => void
  /** Our devices: the status the table is filtered to, and how to change it. */
  deviceFilter?: string | null
  onDeviceFilter?: (label: string | null) => void
  onCapture: (mode: CaptureMode) => void
  onBrief: (date: string) => void
  onAlert: (a: AlertItem) => void
  expanded: boolean
  onToggleExpand: () => void
  /** The live conversation (typed and spoken questions); `enabled` is false when the build has no API address. */
  live?: LiveChat
  /** Shows the live conversation. */
  onLive?: () => void
  /** The API address (null: stored data only); the Connect page asks it for the connector details. */
  apiBase?: string | null
}

function StoredList({ def, data, onThread }: { def: WorkflowDef; data: WorkspaceData; onThread: (id: string) => void }) {
  const group = data.threads.workflows.find((w) => w.id === def.id)
  const items = group ? data.threads.threads.filter((t) => group.thread_ids.includes(t.id)) : []
  const demo = DEMO_WORKFLOWS.includes(def.id)
  return (
    <div>
      <h1 className="t-title-lg m-0">{def.title}</h1>
      <p className="mt-2 text-ink-2">{def.blurb}</p>
      {demo && (
        <p className="ms-banner ms-banner--warn mt-4">
          <span className="ws-wrap">
            <strong>{demoSnapshotLabel(data.sources)}.</strong> These answers were recorded against the demo database, not
            this week's openFDA data. For the newest real data, open the AI device sweep.
          </span>
        </p>
      )}
      {items.length > 0 && (
        <>
          <h2 className="ms-kicker mt-6">Stored questions · {items.length}</h2>
          <ul className="m-0 mt-2 list-none p-0">
            {items.map((t) => (
              <li key={t.id}>
                <button className="ws-side-item items-start border-b border-rule" onClick={() => onThread(t.id)}>
                  <span className="ws-wrap">{t.question}</span>
                  <Icon name="chevron" size={18} />
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

export function ChatPane(p: Props) {
  const { data } = p
  const live = p.live ?? NO_LIVE
  const onLive = p.onLive ?? (() => undefined)
  // The microphone: one click starts, the next stops; the clip becomes a 16 kHz WAV and is sent as a spoken question.
  const recorder = useRecorder({
    onResult: (r) => {
      live.setMicNotice(null)
      void live.askVoice(r.wav)
      onLive()
    },
    onError: (message) => {
      // No permission, no microphone or nothing recorded: say so and show the recorded voice run.
      live.setMicNotice(message)
      p.onCapture('voice')
    },
  })
  let body: JSX.Element
  if (p.view.kind === 'live') {
    body = (
      <LiveChatView
        chat={live}
        threads={data.threads.threads}
        onStarter={(q) => void live.ask(q)}
        onRecordedVoice={() => p.onCapture('voice')}
      />
    )
  } else if (p.view.kind === 'connect') {
    body = <ConnectView apiBase={p.apiBase ?? null} />
  } else if (p.view.kind === 'new') {
    body = <Dashboard data={data} onWorkflow={p.onWorkflow} onBrief={p.onBrief} onAlert={p.onAlert} />
  } else if (p.view.kind === 'workflow') {
    const id = p.view.id
    const def = WORKFLOWS.find((w) => w.id === id) ?? WORKFLOWS[0]
    if (id === 'ai-sweep') body = <SweepCard sweep={data.sweep} />
    else if (id === 'check-device') body = <LiveCheckView key={p.view.code ?? ''} initialCode={p.view.code} />
    else if (id === 'our-devices')
      body = (
        <OurDevices company={data.company} deviceId={p.view.code ?? null}
          onDevice={(x) => p.onDevice?.(x)}
          onBack={() => p.onDevice?.(null)}
          filter={p.deviceFilter ?? null}
          onFilter={p.onDeviceFilter}
        />
      )
    else if (id === 'vision') body = <VisionWorkflow vision={data.vision} onOpen={p.onVision} onCamera={() => p.onCapture('label')} />
    else if (id === 'weekly-investigator' || id === 'recall-sweep')
      body = <RunList kind={id} runs={data.investigations.investigations} notes={data.investigations.notes} onRun={p.onRun} />
    else body = <StoredList def={def} data={data} onThread={p.onThread} />
  } else if (p.view.kind === 'capture') {
    body = (
      <CaptureView
        key={p.view.mode}
        mode={p.view.mode}
        data={data}
        onThread={p.onThread}
        onLabel={(index) => p.onVision({ mode: 'labels', index })}
        voice={live.enabled ? { recorder, notice: live.micNotice, onWav: (w) => { live.setMicNotice(null); void live.askVoice(w); onLive() } } : null}
      />
    )
  } else if (p.view.kind === 'run') {
    const id = p.view.id
    const run = data.investigations.investigations.find((r) => r.id === id)
    body = run ? <RunView run={run} ev={data.evidence} onThread={p.onThread} /> : <p>That run is not in the stored data.</p>
  } else {
    const id = p.view.id
    const t = data.threads.threads.find((x) => x.id === id)
    const group = data.threads.workflows.find((w) => w.id === t?.workflow)
    const siblings = group ? data.threads.threads.filter((x) => group.thread_ids.includes(x.id)) : []
    const hl = p.withheld && p.withheld.highlight.threadId === id ? p.withheld : null
    body = t ? (
      <ThreadView
        key={t.id}
        t={t}
        ev={data.evidence}
        siblings={siblings}
        onThread={p.onThread}
        highlight={hl ? hl.highlight.index : null}
        withheldNav={hl ? { pos: hl.pos, total: hl.total, onNext: hl.onNext } : undefined}
        snapshot={demoSnapshotLabel(data.sources)}
      />
    ) : (
      <p>That thread is not in the stored data.</p>
    )
  }
  // Scrolled down: the composer shrinks to its one input row (phone).
  const [scrolled, setScrolled] = useState<string | null>(null)
  const key = viewKey(p.view)
  const codes = useMemo(() => knownCodes(data.sweep, data.briefs), [data.sweep, data.briefs])
  return (
    <main
      className={['flex min-h-0 min-w-0 flex-1 flex-col bg-paper', p.expanded ? FULLSCREEN : ''].join(' ')}
      aria-label={p.view.kind === 'new' ? 'Home' : 'Chat'}
      data-expanded={p.expanded}
    >
      {/* Below lg the title row and its expand button are dropped (the page is one column already), so the top of the screen is not spent on a second title bar. */}
      <div className={p.expanded ? '' : 'max-lg:hidden'}>
        <PanelBar title={p.view.kind === 'new' ? 'Home' : 'Chat'} panel="main" expanded={p.expanded} onToggle={p.onToggleExpand} />
      </div>
      <div
        className="ws-fade-bottom min-h-0 flex-1 scroll-pb-40 overflow-y-auto px-4 py-4 md:px-8 md:py-6"
        onScroll={(e) => {
          const down = e.currentTarget.scrollTop > 40
          setScrolled((cur) => (down ? key : cur === key ? null : cur))
        }}
      >
        <div className={['mx-auto pb-40 lg:pb-28', p.view.kind === 'new' ? 'max-w-6xl' : 'max-w-3xl'].join(' ')}>{body}</div>
      </div>
      <Composer
        threads={data.threads.threads}
        onThread={p.onThread}
        viewKey={viewKey(p.view)}
        codes={codes}
        onCode={p.onCode}
        onCamera={() => p.onCapture('label')}
        onMic={() => p.onCapture('voice')}
        captureMode={p.view.kind === 'capture' ? p.view.mode : null}
        compact={scrolled === key}
        live={
          live.enabled
            ? {
                busy: live.busy,
                recorder,
                onAsk: (q) => {
                  const refused = live.ask(q)
                  if (!refused) onLive()
                  return refused
                },
              }
            : null
        }
      />
    </main>
  )
}
