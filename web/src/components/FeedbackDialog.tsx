import { useEffect, useRef, useState } from 'react'
import {
  CONSENT_OPTIONS,
  EMPTY_FORM,
  dialogKey,
  submitFeedback,
  type FeedbackForm,
  type SubmitResult,
} from '../feedback'

interface Props {
  open: boolean
  onClose: () => void
  apiBase: string | null
  refCode: string | null
  page: string
}

export const PATIENT_WARNING = "Please don't include patient details or any patient data."
export const PRIVATE_NOTE = 'Sent privately to the MaudeSignal builder; never shown publicly.'

const FOCUSABLE = 'button:not([disabled]), input:not([disabled]), textarea:not([disabled])'
const FIELD = 'w-full rounded-xs border border-rule-strong bg-surface px-3 py-2 text-[16px] font-normal text-ink'
const LABEL = 'flex flex-col gap-1 text-[16px] font-semibold text-ink'

export function FeedbackDialog({ open, onClose, apiBase, refCode, page }: Props) {
  const [form, setForm] = useState<FeedbackForm>(EMPTY_FORM)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<SubmitResult | null>(null)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const opener = document.activeElement
    setResult(null)
    setTimeout(() => box.current?.querySelector<HTMLElement>('input,textarea')?.focus(), 0)
    return () => {
      if (opener instanceof HTMLElement) opener.focus()
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  const set = <K extends keyof FeedbackForm>(k: K, v: FeedbackForm[K]) => setForm((f) => ({ ...f, [k]: v }))
  const sent = result?.ok === true

  const send = async () => {
    setBusy(true)
    const r = await submitFeedback(apiBase, form, refCode, page, (u, init) => fetch(u, init))
    setResult(r)
    setBusy(false)
    if (r.ok) setForm(EMPTY_FORM)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/40 px-3 py-6"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        ref={box}
        role="dialog"
        aria-modal="true"
        aria-labelledby="fb-title"
        className="w-full max-w-lg rounded-md border border-rule-strong bg-surface p-4 md:p-5"
        style={{ boxShadow: 'var(--shadow-pop)' }}
        onKeyDown={(e) => {
          const els = Array.from(box.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])
          dialogKey(e, els, document.activeElement as HTMLElement | null, onClose, (el) => el.focus())
        }}
      >
        <h2 id="fb-title" className="m-0 text-[22px] font-semibold text-ink">
          Give feedback
        </h2>
        {sent ? (
          <div className="mt-3" role="status">
            <p className="ms-banner ms-banner--ok">Thank you. Your feedback was sent.</p>
            <div className="mt-4 flex justify-end">
              <button type="button" className="ms-btn ms-btn--primary" onClick={onClose}>
                Close
              </button>
            </div>
          </div>
        ) : (
          <form
            className="mt-3 flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault()
              if (!busy) void send()
            }}
          >
            <p className="ms-banner ms-banner--warn m-0">{PATIENT_WARNING}</p>

            <fieldset className="m-0 border-0 p-0">
              <legend className="mb-1 text-[16px] font-semibold text-ink">
                Does this match real PMS/RA work? (required)
              </legend>
              <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Rating from 1 to 5">
                {[1, 2, 3, 4, 5].map((n) => (
                  <label
                    key={n}
                    className="inline-flex min-h-10 min-w-10 cursor-pointer items-center justify-center rounded-xs border border-rule-strong px-3 text-[16px] text-ink has-[:checked]:bg-inverse has-[:checked]:text-on-inverse has-[:focus-visible]:outline has-[:focus-visible]:outline-2"
                  >
                    <input
                      type="radio"
                      name="fb-rating"
                      value={n}
                      checked={form.rating === n}
                      onChange={() => set('rating', n)}
                      className="sr-only"
                    />
                    {n}
                  </label>
                ))}
              </div>
              <p className="m-0 mt-1 text-[14px] text-ink-3">1 = not at all, 5 = very closely</p>
            </fieldset>

            <label className={LABEL}>
              Comment
              <textarea
                className={FIELD}
                rows={3}
                maxLength={2000}
                value={form.comment}
                onChange={(e) => set('comment', e.target.value)}
              />
            </label>
            <label className={LABEL}>
              What would stop your team using it?
              <textarea
                className={FIELD}
                rows={2}
                maxLength={2000}
                value={form.blocker}
                onChange={(e) => set('blocker', e.target.value)}
              />
            </label>
            <label className={LABEL}>
              One thing that would make it useful?
              <textarea
                className={FIELD}
                rows={2}
                maxLength={2000}
                value={form.one_thing}
                onChange={(e) => set('one_thing', e.target.value)}
              />
            </label>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className={LABEL}>
                Name (optional)
                <input
                  type="text"
                  autoComplete="off"
                  maxLength={120}
                  className={FIELD}
                  value={form.name}
                  onChange={(e) => set('name', e.target.value)}
                />
              </label>
              <label className={LABEL}>
                Role (optional)
                <input
                  type="text"
                  autoComplete="off"
                  maxLength={120}
                  className={FIELD}
                  value={form.role}
                  onChange={(e) => set('role', e.target.value)}
                />
              </label>
            </div>

            <fieldset className="m-0 border-0 p-0">
              <legend className="mb-1 text-[16px] font-semibold text-ink">May we quote you?</legend>
              {CONSENT_OPTIONS.map((o) => (
                <label key={o.value} className="flex min-h-10 items-center gap-2 text-[16px] text-ink">
                  <input
                    type="radio"
                    name="fb-consent"
                    value={o.value}
                    checked={form.consent === o.value}
                    onChange={() => set('consent', o.value)}
                  />
                  {o.label}
                </label>
              ))}
            </fieldset>

            {result && !result.ok && (
              <p className="ms-banner ms-banner--err m-0" role="alert">
                {result.message}
              </p>
            )}
            <p className="m-0 text-[14px] text-ink-3">{PRIVATE_NOTE}</p>
            <div className="flex justify-end gap-2">
              <button type="button" className="ms-btn ms-btn--secondary" onClick={onClose}>
                Cancel
              </button>
              <button type="submit" className="ms-btn ms-btn--primary" disabled={busy || form.rating === null}>
                {busy ? 'Sending…' : 'Send feedback'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
