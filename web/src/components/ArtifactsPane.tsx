import { Icon } from '../icons'
import type { Brief } from '../types'

interface Props {
  open: boolean
  brief: Brief | null
  onClose: () => void
}

const COUNT_LABELS: [keyof Brief['counts'], string][] = [
  ['new', 'New kind of problem'],
  ['more_serious_than_usual', 'More serious than usual'],
  ['reports_suddenly_increased', 'Reports suddenly increased'],
  ['stable', 'No change'],
]

function BriefView({ b }: { b: Brief }) {
  return (
    <article>
      <p className="ms-kicker">Daily brief</p>
      <h2 className="t-title-lg ms-num m-0 mt-1">{b.date}</h2>
      <p className="ws-wrap mt-2 text-ink-2">{b.headline}</p>
      <p className="m-0 text-[14px] text-ink-3">
        Week {b.window.current_start} to {b.window.current_end}, compared with {b.window.baseline_start} to{' '}
        {b.window.baseline_end}.
      </p>
      <dl className="m-0 mt-4 grid grid-cols-2 gap-2">
        {COUNT_LABELS.map(([k, label]) => (
          <div key={k} className="rounded-md border border-rule bg-surface p-3">
            <dt className="text-[14px] leading-snug text-ink-2">{label}</dt>
            <dd className="t-index ms-num m-0 mt-1">{b.counts[k]}</dd>
          </div>
        ))}
      </dl>
      <h3 className="ms-kicker mt-6">Device types · {b.signals.length}</h3>
      <ul className="m-0 mt-2 list-none p-0">
        {b.signals.map((s) => (
          <li key={s.product_code} className="flex items-baseline justify-between gap-3 border-t border-rule py-2">
            <span>
              <span className="ms-code mr-2">{s.product_code}</span>
              {s.label}
            </span>
            <span className="ms-num shrink-0 text-ink-2">{s.current_count} this week</span>
          </li>
        ))}
      </ul>
      {b.footer && <p className="ws-wrap mt-4 text-[13px] leading-snug text-ink-3">{b.footer}</p>}
    </article>
  )
}

export function ArtifactsPane({ open, brief, onClose }: Props) {
  return (
    <aside
      id="artifacts"
      aria-label="Artifacts"
      className={[
        'z-30 flex flex-col border-rule bg-surface',
        // phone and tablet: bottom sheet
        'max-lg:fixed max-lg:inset-x-0 max-lg:bottom-0 max-lg:max-h-[78dvh] max-lg:rounded-t-md max-lg:border-t max-lg:transition-transform max-lg:duration-200',
        open ? '' : 'max-lg:invisible max-lg:translate-y-full',
        // desktop: docked on the right
        'lg:static lg:w-[26rem] lg:shrink-0 lg:border-l',
        open ? '' : 'lg:hidden',
      ].join(' ')}
    >
      <div className="flex shrink-0 items-center justify-between border-b border-rule px-4 py-2">
        <h2 className="m-0 text-[16px] font-semibold">Artifacts</h2>
        <button className="ws-icon-btn" onClick={onClose} aria-label="Close artifacts">
          <Icon name="close" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {brief ? (
          <BriefView b={brief} />
        ) : (
          <div className="text-ink-2">
            <p className="m-0 font-semibold text-ink">Nothing open</p>
            <p className="mt-2">
              Open a daily brief from the sidebar to read it here. Dossier, vision readings, the audit trail and
              CAPA drafts are coming soon.
            </p>
          </div>
        )}
      </div>
    </aside>
  )
}
