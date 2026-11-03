import { useEffect, useState } from 'react'
import { loadAudit, verifyAudit, type AuditEntry } from './audit'

/** The browser audit trail, re-read and re-verified whenever an entry is appended. */
export function useAudit(): { entries: AuditEntry[]; ok: boolean | null; firstBad: number | null } {
  const [entries, setEntries] = useState<AuditEntry[]>(() => loadAudit())
  const [check, setCheck] = useState<{ ok: boolean | null; firstBad: number | null }>({ ok: null, firstBad: null })
  useEffect(() => {
    const on = () => setEntries(loadAudit())
    window.addEventListener('ms-audit', on)
    window.addEventListener('storage', on)
    return () => {
      window.removeEventListener('ms-audit', on)
      window.removeEventListener('storage', on)
    }
  }, [])
  useEffect(() => {
    let live = true
    void verifyAudit(entries).then((r) => live && setCheck(r))
    return () => {
      live = false
    }
  }, [entries])
  return { entries, ...check }
}
