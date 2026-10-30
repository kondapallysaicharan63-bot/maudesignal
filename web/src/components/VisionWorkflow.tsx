import { Icon } from '../icons'
import { fieldRows, matchSummary } from '../labelMatch'
import type { LabelReading, Vision } from '../types'

export type VisionSel = { mode: 'labels' | 'k510'; index: number }

/**
 * A short name for a label photo. It reads the same fields the screen shows (the matching run when one was recorded), so a
 * name never carries a value that the screen hides: an illegible reading, or an illegible field, gives the file name instead.
 */
export function labelName(l: LabelReading): string {
  const stem = l.image.replace(/^vision\/label-|\.jpg$/g, '')
  const { rows, overall } = fieldRows(l)
  if (overall === 'illegible') return `${stem} (not legible)`
  const pick = (k: string) => rows.find((r) => r.key === k)?.value
  return pick('device_name') || pick('model_number') || stem
}

const K_STATUS: Record<string, string> = {
  not_printed: 'no K-number printed',
  verified: 'K-number found in openFDA',
  illegible: 'K-number illegible',
  bad_format: 'printed text is not a K-number',
  not_in_openfda: 'K-number not found in openFDA',
}

/** The stored label and 510(k) readings (vision.json) as a workflow page; each opens in the Vision artifact. */
export function VisionWorkflow({ vision, onOpen, onCamera }: { vision: Vision; onOpen: (sel: VisionSel) => void; onCamera?: () => void }) {
  return (
    <div>
      <h1 className="t-title-lg m-0">Label &amp; 510(k) vision</h1>
      <p className="mt-2 max-w-xl text-ink-2">
        Stored readings: a vision model read each 510(k) summary page twice and each device label photo once, and each field
        is checked against openFDA where a source covers it (and, for 510(k) pages, the PDF's own text). Open one to see each field and how it was
        checked. These are replayed from recordings; nothing is read live here.
      </p>
      {onCamera && (
        <p className="m-0 mt-4">
          <button type="button" className="ms-btn ws-btn-primary" style={{ height: 48 }} onClick={onCamera} data-testid="vision-camera">
            <Icon name="camera" size={18} /> Read a device label with the camera
          </button>
        </p>
      )}
      <h2 className="ms-kicker mt-6">510(k) summary readings · {vision.k510.length}</h2>
      <ul className="m-0 mt-2 list-none p-0">
        {vision.k510.map((k, i) => (
          <li key={k.k_number}>
            <button className="ws-side-item items-start border-b border-rule" onClick={() => onOpen({ mode: 'k510', index: i })}>
              <span className="min-w-0">
                <span className="ms-code mr-2">{k.k_number}</span>
                <span className="ms-num">
                  {k.counts.VERIFIED} verified · {k.counts.CONFLICT} conflict · {k.counts.UNVERIFIABLE} unverifiable
                </span>
                <span className="block text-[17px] text-ink-2">
                  {k.agreement_pct}% of fields agree · {k.pages_read} of {k.page_count} pages
                </span>
              </span>
              <Icon name="chevron" size={18} />
            </button>
          </li>
        ))}
      </ul>
      <h2 className="ms-kicker mt-6">Device label photos · {vision.labels.length}</h2>
      <ul className="m-0 mt-2 list-none p-0">
        {vision.labels.map((l, i) => (
          <li key={l.image}>
            <button className="ws-side-item items-start border-b border-rule" onClick={() => onOpen({ mode: 'labels', index: i })}>
              <span className="min-w-0">
                <span className="ws-wrap block">{labelName(l)}</span>
                <span className="block text-[17px] text-ink-2">
                  {K_STATUS[l.k_status] ?? l.k_status} · {l.sam.boxes.length} label {l.sam.boxes.length === 1 ? 'box' : 'boxes'} found · {matchSummary(l)}
                </span>
              </span>
              <Icon name="chevron" size={18} />
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
