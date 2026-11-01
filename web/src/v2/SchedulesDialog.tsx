// "Schedules and sources" (v2): the same stored facts the classic sidebar footer lists, in a small dialog.
import { useEffect, useRef } from 'react'
import { demoSnapshotLabel, describeCron } from '../data'
import { Icon } from '../icons'
import type { Schedule, Source } from '../types'

function scheduleResult(s: Schedule): string {
  const r = s.last_result
  if (!r) return 'No result yet'
  if (r.flagged !== undefined && r.checked !== undefined) return `Last: ${r.flagged} flagged of ${r.checked} device types · ${r.date.slice(0, 10)}`
  return `Newest brief: ${r.date} · demo snapshot`
}

export function SchedulesDialog({ open, onClose, schedules, sources }: { open: boolean; onClose: () => void; schedules: Schedule[]; sources: Source[] }) {
  const closeBtn = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!open) return
    const back = document.activeElement as HTMLElement | null
    window.setTimeout(() => closeBtn.current?.focus(), 0)
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', key)
    return () => {
      window.removeEventListener('keydown', key)
      back?.focus?.()
    }
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="ws-scrim z-[70] flex items-start justify-center px-3 pt-[10vh]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-labelledby="sched-h" className="ms2-palette p-5" data-testid="schedules-dialog">
        <div className="flex items-center justify-between gap-2">
          <h2 id="sched-h" className="ms2-h2">
            Schedules and sources
          </h2>
          <button ref={closeBtn} type="button" className="ws-icon-btn min-h-11 min-w-11" onClick={onClose} aria-label="Close">
            <Icon name="close" />
          </button>
        </div>
        <h3 className="ms2-h3 mt-3">Schedules</h3>
        <ul className="m-0 list-none space-y-2 p-0">
          {schedules.map((s) => (
            <li key={s.id}>
              <span className="block font-medium">{s.label}</span>
              <span className="ms2-muted block">{describeCron(s.cron)}</span>
              <span className="ms2-muted ws-wrap block">{scheduleResult(s)}</span>
            </li>
          ))}
        </ul>
        <h3 className="ms2-h3 mt-4">Sources · demo database</h3>
        <ul className="m-0 list-none p-0">
          {sources.map((s) => (
            <li key={s.id} className="flex justify-between gap-3 py-0.5">
              <span>{s.label}</span>
              <span className="ms-num ms2-muted">{s.records.toLocaleString('en-US')}</span>
            </li>
          ))}
        </ul>
        <p className="ms2-muted m-0 mt-3 text-[15px]">
          {demoSnapshotLabel(sources)}: stored records in the demo database, not live openFDA. MHRA (UK) is regulator context only and never
          counted in a MAUDE number.
        </p>
      </div>
    </div>
  )
}
