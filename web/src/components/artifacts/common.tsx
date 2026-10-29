import type { ReactNode } from 'react'

export type Tone = 'ok' | 'bad' | 'warn' | 'neutral'

const TONE: Record<Tone, string> = {
  ok: 'bg-success-soft text-success',
  bad: 'bg-critical-soft text-critical',
  warn: 'bg-warning-soft text-warning',
  neutral: 'bg-sunk text-ink-2',
}

export function Pill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={`ws-pill ${TONE[tone]}`}>{children}</span>
}

/** A row of exclusive choices (segmented control). */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: T
  options: { id: T; label: string }[]
  onChange: (v: T) => void
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          aria-pressed={o.id === value}
          onClick={() => onChange(o.id)}
          className={[
            'min-h-10 rounded-xs border px-3 text-[15px]',
            o.id === value ? 'border-ink bg-sunk font-semibold text-ink' : 'border-rule text-ink-2 hover:bg-sunk',
          ].join(' ')}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="text-ink-2">
      <p className="m-0 font-semibold text-ink">{title}</p>
      {children && <div className="mt-2">{children}</div>}
    </div>
  )
}
