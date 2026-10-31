// Pure helpers for a live label reading and for the photo that is sent. A value the server marked as withheld, or that
// was read as illegible, is never shown; nothing is filled in from anywhere else.
import { FIELD_LABEL } from '../labelMatch'
import type { LiveReading } from './api'

export interface Row {
  key: string
  label: string
  value: string | null
  hidden: boolean
}

const LABELS: Record<string, string> = { ...FIELD_LABEL, model: 'Model', udi_gtin: 'UDI / GTIN', 'udi/gtin': 'UDI / GTIN' }

/** The fields of a live reading as rows. Withheld, illegible or empty values are never shown (value null). */
export function readingRows(r: LiveReading): Row[] {
  const withheldKeys = Array.isArray(r.values_withheld) ? new Set(r.values_withheld.map(String)) : new Set<string>()
  const allWithheld = r.values_withheld === true
  return Object.entries(r.fields).map(([key, f]) => {
    const raw = typeof f === 'string' || f === null ? f : (f?.value ?? null)
    const leg = typeof f === 'object' && f !== null ? f.legibility : undefined
    // "hidden" (shown as "value withheld") only for keys the server listed in values_withheld; an unreadable or empty
    // field has no value and shows "not read". A value that was read as illegible is never shown either way.
    const withheld = allWithheld || withheldKeys.has(key)
    const unreadable = r.legibility === 'illegible' || leg === 'illegible' || !raw
    return { key, label: LABELS[key] ?? key.replace(/_/g, ' '), value: withheld || unreadable ? null : String(raw), hidden: withheld }
  })
}

/** The longest side a photo is drawn at before it is sent (matches the server's own 1600 px, keeps the upload under the 4 MB limit). */
export const MAX_SIDE = 1600

/** Size to draw a w x h image at so its longest side is at most `max`; never enlarges. */
export function fitSize(w: number, h: number, max: number = MAX_SIDE): { width: number; height: number } {
  if (!(w > 0) || !(h > 0)) return { width: 0, height: 0 }
  const k = Math.min(1, max / Math.max(w, h))
  return { width: Math.max(1, Math.round(w * k)), height: Math.max(1, Math.round(h * k)) }
}

/** True for the two image types the API accepts. */
export const isAcceptedImage = (type: string): boolean => type === 'image/jpeg' || type === 'image/png'
