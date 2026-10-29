import { Icon } from '../icons'
import type { LabelReading, Vision } from '../types'

export type VisionSel = { mode: 'labels' | 'k510'; index: number }

export const labelName = (l: LabelReading): string =>
  l.fields.device_name?.value || l.fields.model_number?.value || l.image.replace(/^vision\/label-|\.jpg$/g, '')

const K_STATUS: Record<string, string> = {
  not_printed: 'no K-number printed',
  verified: 'K-number found in openFDA',
  illegible: 'K-number illegible',
  bad_format: 'printed text is not a K-number',
  not_in_openfda: 'K-number not found in openFDA',
}

/** The stored label and 510(k) readings (vision.json) as a workflow page; each opens in the Vision artifact. */
export function VisionWorkflow({ vision, onOpen }: { vision: Vision; onOpen: (sel: VisionSel) => void }) {
  return (
    <div>
      <h1 className="t-title-lg m-0">Label &amp; 510(k) vision</h1>
      <p className="mt-2 max-w-xl text-ink-2">
        Stored readings: a vision model read each 510(k) summary page twice and each device label photo once, and each field
        is checked against openFDA where a source covers it (and, for 510(k) pages, the PDF's own text). Open one to see each field and how it was
        checked. These are replayed from recordings; nothing is read live here.
      </p>
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
                <span className="block text-[14px] text-ink-3">
                  Both reads agree on {k.agreement_pct}% of fields · {k.pages_read} of {k.page_count} pages read
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
                <span className="block text-[14px] text-ink-3">
                  {K_STATUS[l.k_status] ?? l.k_status} · {l.sam.boxes.length} label {l.sam.boxes.length === 1 ? 'box' : 'boxes'} found
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
