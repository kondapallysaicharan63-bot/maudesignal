import { useEffect, useMemo, useRef, useState } from 'react'
import { WORKFLOWS } from '../data'
import { Icon } from '../icons'
import type { WorkflowId } from '../types'

interface Props {
  open: boolean
  onClose: () => void
  onWorkflow: (id: WorkflowId) => void
}

export function CommandPalette({ open, onClose, onWorkflow }: Props) {
  const [q, setQ] = useState('')
  const [idx, setIdx] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  const items = useMemo(
    () => WORKFLOWS.filter((w) => w.title.toLowerCase().includes(q.trim().toLowerCase())),
    [q],
  )

  useEffect(() => {
    if (open) {
      setQ('')
      setIdx(0)
      // focus after the dialog is in the DOM
      setTimeout(() => input.current?.focus(), 0)
    }
  }, [open])

  if (!open) return null
  const pick = (i: number) => {
    const w = items[i]
    if (!w) return
    onWorkflow(w.id)
    onClose()
  }
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-ink/40 px-3 pt-[12vh]"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Workflows"
        className="w-full max-w-lg rounded-md border border-rule-strong bg-surface"
        style={{ boxShadow: 'var(--shadow-pop)' }}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onClose()
          else if (e.key === 'ArrowDown') {
            e.preventDefault()
            setIdx((i) => Math.min(i + 1, items.length - 1))
          } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            setIdx((i) => Math.max(i - 1, 0))
          } else if (e.key === 'Enter') {
            e.preventDefault()
            pick(idx)
          }
        }}
      >
        <div className="flex items-center gap-2 border-b border-rule px-3">
          <Icon name="search" />
          <input
            ref={input}
            value={q}
            onChange={(e) => {
              setQ(e.target.value)
              setIdx(0)
            }}
            placeholder="Go to a workflow"
            aria-label="Search workflows"
            className="h-12 min-w-0 flex-1 bg-transparent text-[17px] text-ink placeholder:text-ink-3 focus:outline-none"
          />
        </div>
        <ul role="listbox" aria-label="Workflows" className="m-0 max-h-[50vh] list-none overflow-y-auto p-1">
          {items.map((w, i) => (
            <li key={w.id} role="option" aria-selected={i === idx}>
              <button
                className={`ws-side-item ${i === idx ? 'bg-sunk' : ''}`}
                onMouseEnter={() => setIdx(i)}
                onClick={() => pick(i)}
              >
                <span>{w.title}</span>
                {w.comingSoon && <span className="ws-pill bg-sunk text-ink-2">coming soon</span>}
              </button>
            </li>
          ))}
          {items.length === 0 && <li className="px-3 py-3 text-ink-3">No workflow matches.</li>}
        </ul>
      </div>
    </div>
  )
}
