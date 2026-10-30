import { useState } from 'react'
import type { Dossier, K510Field, K510Reading, LabelReading, ReadStatus, Vision } from '../../types'
import { buildLabelTrace, buildReviewTrace } from '../../trace'
import { TraceView } from '../TraceView'
import { labelName, type VisionSel } from '../VisionWorkflow'
import { PdfView } from './PdfView'
import { Empty, Pill, Segmented, type Tone } from './common'

const base = import.meta.env.BASE_URL
const dataUrl = (p: string) => `${base}data/${p}`

/** Draft and approved evidence-pack PDFs, embedded, with download. */
export function DossierTab({ dossier }: { dossier: Dossier }) {
  const [which, setWhich] = useState<'draft' | 'approved'>('draft')
  const url = dataUrl(dossier.pdf[which])
  const r = dossier.review
  return (
    <article>
      <p className="ms-kicker">Dossier</p>
      <h2 className="t-title-lg ms-code m-0 mt-1" style={{ fontSize: 18 }}>
        {dossier.doc_id}
      </h2>
      <div className="mt-3">
        <Segmented
          label="Which copy"
          value={which}
          options={[
            { id: 'draft', label: 'Draft PDF' },
            { id: 'approved', label: 'Approved PDF (demo reviewer)' },
          ]}
          onChange={setWhich}
        />
      </div>
      {which === 'approved' && (
        <p className="mt-2 text-[15px] text-ink-2">
          The approval in this copy is by a demo reviewer. It is a demonstration, not a Part 11 signature.
        </p>
      )}
      <div className="mt-3">
        <PdfView url={url} title={`${which} evidence pack ${dossier.doc_id}`} />
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        <a className="ms-chip" href={url} target="_blank" rel="noreferrer">
          Open in a new tab
        </a>
        <a className="ms-chip" href={url} download>
          Download {which} PDF
        </a>
      </div>
      <dl className="m-0 mt-4 text-[15px] text-ink-2">
        {dossier.narrative && (
          <div>
            <dt className="inline text-ink-2">Summary written by </dt>
            <dd className="m-0 inline">
              {dossier.narrative.model} (skill {dossier.narrative.skill_version}), {dossier.narrative.created_at}
            </dd>
          </div>
        )}
        {r && (
          <div className="mt-1">
            <dt className="inline text-ink-2">Independent review by </dt>
            <dd className="m-0 inline">
              {r.model}: {r.parse_error ? `could not be read (${r.parse_error})` : `${r.findings.length} findings`}
            </dd>
          </div>
        )}
      </dl>
      {r && !r.parse_error && (
        <div className="mt-4">
          <TraceView trace={buildReviewTrace(r)} shown={99} label="Review steps" replayed={false} />
        </div>
      )}
      <p className="mt-3 text-[15px] leading-snug text-ink-2">
        Advisory only. A named person reviews and decides; nothing is filed with FDA.
      </p>
    </article>
  )
}

const READ_TONE: Record<ReadStatus, Tone> = { VERIFIED: 'ok', CONFLICT: 'bad', UNVERIFIABLE: 'warn' }
const READ_LABEL: Record<ReadStatus, string> = { VERIFIED: 'verified', CONFLICT: 'conflict', UNVERIFIABLE: 'unverifiable' }

const K_STATUS: Record<string, string> = {
  not_printed: 'No K-number is printed on this label.',
  verified: 'K-number found in openFDA.',
  illegible: 'A K-number is printed but cannot be read.',
  bad_format: 'The printed text is not in K-number format.',
  not_in_openfda: 'The K-number was not found in openFDA.',
}

const OUTCOME_TONE: Record<string, Tone> = { pass: 'ok', fail: 'bad' }

function SamImage({ l }: { l: LabelReading }) {
  const [w, h] = l.image_size
  const chosen = l.sam.chosen_box
  return (
    <figure className="m-0">
      <div
        className="relative mx-auto overflow-hidden rounded-md border border-rule"
        style={{ width: `min(100%, calc(52dvh * ${w} / ${h}))`, aspectRatio: `${w} / ${h}` }}
      >
        <img src={dataUrl(l.image)} alt="Device label photo with the detected label boxes drawn on it" className="block h-full w-full" />
        <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full" aria-hidden="true">
          {l.sam.boxes.map((b, i) => {
            const isChosen = chosen !== null && b.x1 === chosen.x1 && b.y1 === chosen.y1
            return (
              <rect
                key={i}
                x={b.x1}
                y={b.y1}
                width={b.x2 - b.x1}
                height={b.y2 - b.y1}
                fill="none"
                stroke={isChosen ? 'var(--accent)' : 'var(--warning-mark)'}
                strokeWidth={3}
                strokeDasharray={isChosen ? undefined : '10 6'}
                vectorEffect="non-scaling-stroke"
              />
            )
          })}
        </svg>
      </div>
      <figcaption className="mt-2 text-[15px] text-ink-2">
        {l.sam.boxes.length === 0
          ? 'No label box was detected.'
          : `${l.sam.boxes.length} box${l.sam.boxes.length === 1 ? '' : 'es'} detected by SAM 3.1 (Meta); detector score on a 0 to 1 scale: ${l.sam.boxes
              .map((b) => b.c.toFixed(2))
              .join(', ')}. Label text read by ${l.model}. Solid line: the box read; dashed: not used.`}
      </figcaption>
    </figure>
  )
}

const FIELD_LABEL: Record<string, string> = {
  device_name: 'Device name',
  manufacturer: 'Manufacturer',
  model_number: 'Model number',
  k_number: 'K-number',
  udi: 'UDI',
  gtin: 'GTIN',
}

function LabelView({ l }: { l: LabelReading }) {
  const gtinText =
    l.gtin === null
      ? 'No GTIN is printed on this label.'
      : `GTIN ${l.gtin}: check digit ${l.gtin_valid ? 'valid' : 'does not match'}.`
  return (
    <div>
      <SamImage l={l} />
      <div className="mt-4">
        <TraceView trace={buildLabelTrace(l)} shown={99} label="Label reading steps" replayed={false} />
      </div>
      <h3 className="ms-kicker mt-4">Fields read from the label</h3>
      <dl className="m-0 mt-1">
        {Object.entries(l.fields).map(([k, f]) => (
          <div key={k} className="flex flex-wrap items-baseline justify-between gap-x-3 border-t border-rule py-2">
            <dt className="text-[15px] text-ink-2">{FIELD_LABEL[k] ?? k}</dt>
            <dd className="ws-wrap m-0 text-right">
              {f.value ? f.value : <span className="text-ink-2">not present</span>}{' '}
              <span className="ms-code">{f.legibility.replace('_', ' ')}</span>
            </dd>
          </div>
        ))}
      </dl>
      <h3 className="ms-kicker mt-4">Checks</h3>
      <ul className="m-0 mt-1 list-none p-0">
        <li className="border-t border-rule py-2">
          <Pill tone={l.k_status === 'verified' ? 'ok' : l.k_status === 'not_printed' ? 'neutral' : 'warn'}>K-number</Pill>{' '}
          <span className="ws-wrap">
            {K_STATUS[l.k_status] ?? l.k_status}
            {l.k_number ? ` (${l.k_number})` : ''}
          </span>
        </li>
        <li className="border-t border-rule py-2">
          <Pill tone={l.gtin === null ? 'neutral' : l.gtin_valid ? 'ok' : 'bad'}>GTIN</Pill>{' '}
          <span className="ws-wrap">{gtinText}</span>
        </li>
        {l.checks.map((c, i) => (
          <li key={i} className="border-t border-rule py-2">
            <Pill tone={OUTCOME_TONE[c.outcome] ?? 'neutral'}>{c.outcome}</Pill>{' '}
            <span className="ws-wrap">
              {c.source.replace(/_/g, ' ')}: {c.detail}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-[15px] leading-snug text-ink-2">
        Lot and serial numbers are read for the session only and are never stored or exported. Overall legibility: {l.overall_legibility.replace('_', ' ')}.
      </p>
    </div>
  )
}

function fmt(v: string | string[] | null | undefined): string {
  if (v === null || v === undefined) return ''
  return Array.isArray(v) ? v.join(', ') : v
}

function ReadLine({ f }: { f: K510Field }) {
  const sources = Array.from(
    new Set(f.checks.filter((c) => c.outcome === 'pass' && c.source !== 'two_reads').map((c) => c.source.replace(/_/g, ' '))),
  )
  const basis = sources.length > 0 ? `Both reads agree; also checked against ${sources.join(', ')}` : 'Two reads only: no other source covers this field'
  return (
    <li className="border-t border-rule py-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-[15px] text-ink-2">{f.name.replace(/_/g, ' ')}</span>
        <Pill tone={READ_TONE[f.status]}>{READ_LABEL[f.status]}</Pill>
      </div>
      <p className="ws-wrap m-0">{fmt(f.value) || <span className="text-ink-2">no value</span>}</p>
      {f.status !== 'VERIFIED' && (
        <p className="ws-wrap m-0 mt-1 text-[15px] text-ink-2">
          Read A: {fmt(f.read_a?.value) || 'none'} · Read B: {fmt(f.read_b?.value) || 'none'}
          {f.note ? ` · ${f.note}` : ''}
        </p>
      )}
      {f.status === 'VERIFIED' && (
        <p className="ws-wrap m-0 mt-1 text-[15px] text-ink-2">
          {basis}
          {f.note ? ` · ${f.note}` : ''}
        </p>
      )}
      <details>
        <summary className="min-h-10 cursor-pointer py-2 text-[15px] text-ink-2">How it was checked</summary>
        <ul className="m-0 list-none p-0 text-[15px] text-ink-2">
          {f.checks.map((c, i) => (
            <li key={i} className="ws-wrap py-0.5">
              {c.source.replace(/_/g, ' ')}: {c.outcome}, {c.detail}
            </li>
          ))}
        </ul>
      </details>
    </li>
  )
}

function K510View({ k }: { k: K510Reading }) {
  return (
    <div>
      <p className="ws-wrap m-0 text-ink-2">
        The summary page was read twice, independently. Verified: both reads agree and every available independent source
        (the openFDA record, the PDF text layer) agrees; where no source covers a field, two agreeing reads are the basis
        and the field says so. Conflict: the reads disagree or a source disagrees. Unverifiable: illegible or not found.
      </p>
      <dl className="m-0 mt-3 grid grid-cols-3 gap-2">
        {(['VERIFIED', 'CONFLICT', 'UNVERIFIABLE'] as const).map((s) => (
          <div key={s} className="rounded-md border border-rule bg-surface p-3">
            <dt className="text-[15px] leading-snug text-ink-2">{READ_LABEL[s]}</dt>
            <dd className="t-index ms-num m-0 mt-1">{k.counts[s]}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-2 text-[15px] text-ink-2">
        Both reads agree on <span className="ms-num">{k.agreement_pct}%</span> of fields · {k.pages_read} of{' '}
        {k.page_count} pages read ·{' '}
        <a className="text-accent underline" href={k.pdf_url} target="_blank" rel="noreferrer">
          source PDF on fda.gov
        </a>
      </p>
      <ul className="m-0 mt-2 list-none p-0">
        {k.fields.map((f) => (
          <ReadLine key={f.name} f={f} />
        ))}
      </ul>
    </div>
  )
}


/** Stored vision readings. `initial` (from the Vision workflow page) picks which one opens first. */
export function VisionTab({ vision, initial }: { vision: Vision; initial?: VisionSel }) {
  const [mode, setMode] = useState<'labels' | 'k510'>(initial?.mode ?? 'labels')
  const [li, setLi] = useState(initial?.mode === 'labels' ? initial.index : 0)
  const [ki, setKi] = useState(initial?.mode === 'k510' ? initial.index : 0)
  const label = vision.labels[li]
  const k = vision.k510[ki]
  return (
    <article>
      <p className="ms-kicker">Vision</p>
      <div className="mt-2">
        <Segmented
          label="Kind of reading"
          value={mode}
          options={[
            { id: 'labels', label: `Device labels · ${vision.labels.length}` },
            { id: 'k510', label: `510(k) summaries · ${vision.k510.length}` },
          ]}
          onChange={setMode}
        />
      </div>
      {mode === 'labels' ? (
        label ? (
          <div className="mt-3">
            <label className="block text-[15px] text-ink-2" htmlFor="label-pick">
              Stored label photo
            </label>
            <select
              id="label-pick"
              value={li}
              onChange={(e) => setLi(Number(e.target.value))}
              className="mb-3 min-h-10 w-full rounded-xs border border-rule bg-surface px-2 text-ink"
            >
              {vision.labels.map((l, i) => (
                <option key={l.image} value={i}>
                  {labelName(l)}
                </option>
              ))}
            </select>
            <LabelView l={label} />
          </div>
        ) : (
          <div className="mt-3">
            <Empty title="No label readings stored" />
          </div>
        )
      ) : k ? (
        <div className="mt-3">
          <Segmented
            label="Choose a 510(k)"
            value={String(ki)}
            options={vision.k510.map((x, i) => ({ id: String(i), label: x.k_number }))}
            onChange={(v) => setKi(Number(v))}
          />
          <div className="mt-3">
            <K510View k={k} />
          </div>
        </div>
      ) : (
        <div className="mt-3">
          <Empty title="No 510(k) readings stored" />
        </div>
      )}
    </article>
  )
}
