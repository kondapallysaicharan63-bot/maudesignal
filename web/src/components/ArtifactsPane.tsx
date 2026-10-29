import { useEffect, useMemo, useState } from 'react'
import { auditRunFor, capaDrafts, protocolFor, TABS, type TabId } from '../artifacts'
import { Icon } from '../icons'
import type { Thread, WorkspaceData } from '../types'
import { AuditTab, CapaTab, ProtocolTab } from './artifacts/AuditCapaProtocol'
import { BriefTab, DigestTab } from './artifacts/BriefTabs'
import { DossierTab, VisionTab } from './artifacts/DossierVision'

interface Props {
  open: boolean
  data: WorkspaceData
  tab: TabId
  onTab: (t: TabId) => void
  /** The stored thread on screen, if any. */
  thread: Thread | null
  /** Tabs that thread produced (they get a dot). */
  produced: TabId[]
  briefDate: string | null
  onBriefDate: (d: string) => void
  onClose: () => void
}

export function ArtifactsPane({ open, data, tab, onTab, thread, produced, briefDate, onBriefDate, onClose }: Props) {
  const drafts = useMemo(() => capaDrafts(data.audit), [data.audit])
  const [pick, setPick] = useState<string | null>(null)
  const threadId = thread?.id ?? null
  useEffect(() => setPick(null), [threadId])
  const protocolId = pick ?? threadId
  const brief = data.briefs.find((b) => b.date === briefDate) ?? data.briefs[0] ?? null
  useEffect(() => {
    document.getElementById(`tab-${tab}`)?.scrollIntoView({ inline: 'nearest', block: 'nearest' })
  }, [tab, open])
  const activeRun = auditRunFor(data.audit, thread)?.run_label ?? null

  return (
    <aside
      id="artifacts"
      aria-label="Artifacts"
      className={[
        'z-30 flex flex-col border-rule bg-surface',
        // phone and tablet: bottom sheet
        'max-lg:fixed max-lg:inset-x-0 max-lg:bottom-0 max-lg:h-[82dvh] max-lg:rounded-t-md max-lg:border-t max-lg:transition-transform max-lg:duration-200',
        open ? '' : 'max-lg:invisible max-lg:translate-y-full',
        // desktop: docked on the right
        'lg:static lg:w-[28rem] lg:shrink-0 lg:border-l xl:w-[34rem]',
        open ? '' : 'lg:hidden',
      ].join(' ')}
    >
      <div className="flex shrink-0 items-center justify-between border-b border-rule px-4 py-2">
        <h2 className="m-0 text-[16px] font-semibold">Artifacts</h2>
        <button className="ws-icon-btn" onClick={onClose} aria-label="Close artifacts">
          <Icon name="close" />
        </button>
      </div>
      <div role="tablist" aria-label="Artifacts" className="ws-tabfade flex shrink-0 gap-0.5 overflow-x-auto border-b border-rule px-2">
        {TABS.map((t) => {
          const selected = t.id === tab
          return (
            <button
              key={t.id}
              role="tab"
              id={`tab-${t.id}`}
              aria-selected={selected}
              aria-controls="artifact-panel"
              onClick={() => onTab(t.id)}
              className={[
                'relative min-h-11 shrink-0 whitespace-nowrap border-b-2 px-2.5 text-[15px]',
                selected ? 'border-ink font-semibold text-ink' : 'border-transparent text-ink-2 hover:text-ink',
              ].join(' ')}
            >
              {t.label}
              {produced.includes(t.id) && (
                <>
                  <span className="ws-dot ml-1.5 inline-block align-middle" aria-hidden="true" />
                  <span className="sr-only"> (produced by this thread)</span>
                </>
              )}
            </button>
          )
        })}
      </div>
      <div
        id="artifact-panel"
        role="tabpanel"
        aria-labelledby={`tab-${tab}`}
        className="min-h-0 flex-1 overflow-y-auto px-4 py-4"
      >
        {tab === 'brief' && <BriefTab briefs={data.briefs} date={briefDate} onDate={onBriefDate} />}
        {tab === 'digest' && <DigestTab sweep={data.sweep} brief={brief} />}
        {tab === 'dossier' && <DossierTab dossier={data.dossier} />}
        {tab === 'vision' && <VisionTab vision={data.vision} />}
        {tab === 'audit' && (
          <AuditTab audit={data.audit} activeRun={activeRun} generatedUtc={data.manifest.generated_utc} />
        )}
        {tab === 'capa' && <CapaTab drafts={drafts} evidence={data.evidence} />}
        {tab === 'protocol' && (
          <ProtocolTab
            threadIds={Object.keys(data.protocol.protocols)}
            threadId={protocolId}
            onThread={setPick}
            steps={protocolFor(data.protocol, protocolId)}
            notes={data.investigations.notes}
          />
        )}
      </div>
    </aside>
  )
}
