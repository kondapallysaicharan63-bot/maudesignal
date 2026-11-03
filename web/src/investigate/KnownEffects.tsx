// PRD-30: the known-effects note. A button that only shows a draft sentence for a person; nothing is added to any record.
import { useState } from 'react'
import type { Investigation } from './api'

/** "user facility 5, other 2" from the buckets that are not the manufacturer's; empty when none. */
export function eventCounts(a: Investigation): string {
  const s = a.sources
  if (!s) return ''
  return s.buckets
    .filter((b) => b.normalized.toLowerCase() !== 'manufacturer' && b.count > 0)
    .map((b) => `${b.source.toLowerCase()} ${b.count}`)
    .join(', ')
}

export const knownEffectsText = (a: Investigation): string =>
  `Consider adding [${eventCounts(a) || 'event type and counts not available'}] to the known-effects record for ${a.product_code} - human reviews and approves.`

/** PRD-30: a button that only shows a draft sentence. No auto-add, no auto-approval, nothing is written. */
export function KnownEffects({ a }: { a: Investigation }) {
  const [open, setOpen] = useState(false)
  if (!a.sources) return null
  return (
    <div className="mt-2" data-testid="inv-known">
      <button type="button" className="ms-btn" onClick={() => setOpen((o) => !o)} aria-expanded={open} data-testid="inv-known-btn">
        Known-effects note
      </button>
      {open && (
        <p className="ms2-card mt-2 text-[15px]" data-testid="inv-known-text">
          {knownEffectsText(a)} <span className="ms2-muted">This is a draft sentence for your team. Nothing was added to any record.</span>
        </p>
      )}
    </div>
  )
}

