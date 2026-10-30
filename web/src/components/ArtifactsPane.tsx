import { useEffect, useMemo, useState } from 'react'
import { auditRunFor, capaDrafts, protocolFor, TABS, type TabId } from '../artifacts'
import { Icon } from '../icons'
import { FULLSCREEN } from '../layout'
import { Crumbs, ExpandButton } from './PanelBar'
import type { Thread, WorkspaceData } from '../types'
import { AuditTab, CapaTab, ProtocolTab } from './artifacts/AuditCapaProtocol'
import { BriefTab, DigestTab } from './artifacts/BriefTabs'
import { DossierTab, VisionTab } from './artifacts/DossierVision'
import { demoSnapshotLabel } from '../data'
import type { VisionSel } from './VisionWorkflow'

interface Props {
  open: boolean
  data: WorkspaceData
  tab: TabId
  onTab: (t: TabId) => void
  /** The stored thread on screen, if any. */
  thread: Thread | null
  /** Tabs whose artifact this thread itself created (they get a dot). */
  produced: TabId[]
  briefDate: string | null
  /** Reading the Vision workflow page asked to open (with a counter so the same one can be reopened). */
  vision: (VisionSel & { nonce: number }) | null
  onBriefDate: (d: string) => void
  onClose: () => void
  expanded: boolean
  onToggleExpand: () => void
}

export function ArtifactsPane({ open, data, tab, onTab, thread, produced, briefDate, onBriefDate, vision, onClose, expanded, onToggleExpand }: Props) {
  const drafts = useMemo(() => capaDrafts(data.audit), [data.audit])
  const [pick, setPick] = useState<string | null>(null)
  const threadId = thread?.id ?? null
  useEffect(() => setPick(null), [threadId])
  const protocolId = pick ?? threadId
  const brief = data.briefs.find((b) => b.date === briefDate) ?? data.briefs[0] ?? null
  // A new tab or a newly opened reading starts at the top of the panel.
  useEffect(() => {
    document.getElementById('artifact-panel')?.scrollTo({ top: 0 })
  }, [tab, vision?.nonce])
  // The selected tab scrolls into view in the single-row strip.
  useEffect(() => {
    document.getElementById(`tab-${tab}`)?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
  }, [tab, open, expanded])
  const activeRun = auditRunFor(data.audit, thread)?.run_label ?? null

  return (
    <aside
      id="artifacts"
      aria-label="Artifacts"
      data-expanded={expanded}
      className={[
        'z-30 flex flex-col border-rule bg-surface',
        expanded
          ? FULLSCREEN
          : [
              // phone and tablet: bottom sheet
              'max-lg:fixed max-lg:inset-x-0 max-lg:bottom-0 max-lg:h-[82dvh] max-lg:rounded-t-md max-lg:border-t max-lg:transition-transform max-lg:duration-200',
              open ? '' : 'max-lg:invisible max-lg:translate-y-full',
              // desktop: docked on the right
              'lg:static lg:w-[26rem] lg:shrink-0 lg:border-l xl:w-[27rem]',
              open ? '' : 'lg:hidden',
            ].join(' '),
      ].join(' ')}
    >
      <div className="flex shrink-0 items-center justify-between border-b border-rule px-4 py-2">
        {expanded ? <Crumbs panel="artifacts" /> : <h2 className="m-0 text-[17px] font-semibold">Artifacts</h2>}
        <span className="flex items-center">
          <ExpandButton panel="artifacts" expanded={expanded} onToggle={onToggleExpand} />
          <button className="ws-icon-btn min-h-11 min-w-11" onClick={onClose} aria-label="Close artifacts">
            <Icon name="close" />
          </button>
        </span>
      </div>
      <div className="relative shrink-0 border-b border-rule">
        <div role="tablist" aria-label="Artifacts" className="ws-tabstrip gap-x-1 px-2" data-testid="tabstrip">
          {TABS.map((t) => {
            const selected = t.id === tab
            const made = produced.includes(t.id)
            return (
              <button
                key={t.id}
                role="tab"
                id={`tab-${t.id}`}
                aria-selected={selected}
                aria-controls="artifact-panel"
                onClick={() => onTab(t.id)}
                className={[
                  'relative flex h-11 shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-3 text-[17px]',
                  selected ? 'border-ink font-semibold text-ink' : 'border-transparent text-ink-2 hover:text-ink',
                ].join(' ')}
              >
                {t.label}
                {made && (
                  <>
                    <span className="rounded-xs bg-accent-soft px-1.5 text-[14px] font-semibold leading-snug text-accent" aria-hidden="true">
                      New
                    </span>
                    <span className="sr-only"> (created by this thread)</span>
                  </>
                )}
              </button>
            )
          })}
        </div>
        {produced.length > 0 && (
          <p className="m-0 px-4 pb-1 text-[14px] text-ink-2">New: made by the question on screen.</p>
        )}
      </div>
      <div
        id="artifact-panel"
        role="tabpanel"
        aria-labelledby={`tab-${tab}`}
        className="min-h-0 flex-1 overflow-y-auto px-4 pb-24 pt-4"
      >
        {tab === 'brief' && (
          <BriefTab briefs={data.briefs} date={briefDate} onDate={onBriefDate} snapshot={demoSnapshotLabel(data.sources)} />
        )}
        {tab === 'digest' && <DigestTab sweep={data.sweep} brief={brief} snapshot={demoSnapshotLabel(data.sources)} />}
        {tab === 'dossier' && <DossierTab dossier={data.dossier} />}
        {tab === 'vision' && (
          <VisionTab key={vision ? vision.nonce : 0} vision={data.vision} initial={vision ?? undefined} />
        )}
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
