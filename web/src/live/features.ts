// Which optional features the API offers, read once from GET /v1/health ("features"). A feature the API does not name is
// treated as absent, so an older API never gets a request it does not understand (its inputs refuse unknown fields).
import { useEffect, useState } from 'react'

export const HEALTH_PATH = '/v1/health'
const HEALTH_TIMEOUT_MS = 8000

export interface ApiFeatures {
  /** "Research the web" in the + menu: the ask request may carry research: true. */
  research: boolean
  /** Voice can return only the transcript (meta transcribe_only), so the words go into the box for editing. */
  transcribeOnly: boolean
}

export const NO_FEATURES: ApiFeatures = { research: false, transcribeOnly: false }

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)

/** The features named in a health body; only an explicit `true` counts. */
export function parseFeatures(body: unknown): ApiFeatures {
  const f = isObj(body) && isObj(body.features) ? body.features : {}
  return { research: f.research === true, transcribeOnly: f.voice_transcribe_only === true }
}

type Fetcher = (url: string, init?: RequestInit) => Promise<Response>

/** GET /v1/health. Any failure (no address, network, error status, odd body) means no optional feature. */
export async function fetchFeatures(apiBase: string | null, fetcher: Fetcher): Promise<ApiFeatures> {
  if (!apiBase) return NO_FEATURES
  const ctl = new AbortController()
  const timer = setTimeout(() => ctl.abort(), HEALTH_TIMEOUT_MS)
  try {
    const res = await fetcher(`${apiBase}${HEALTH_PATH}`, { method: 'GET', credentials: 'omit', signal: ctl.signal })
    if (!res.ok) return NO_FEATURES
    return parseFeatures(await res.json())
  } catch {
    return NO_FEATURES
  } finally {
    clearTimeout(timer)
  }
}

/** The API's features for this page (none until the health answer arrives, and none without an API). */
export function useApiFeatures(apiBase: string | null, fetcher?: Fetcher): ApiFeatures {
  const [features, setFeatures] = useState<ApiFeatures>(NO_FEATURES)
  useEffect(() => {
    let alive = true
    void fetchFeatures(apiBase, fetcher ?? ((u, i) => fetch(u, i))).then((f) => {
      if (alive) setFeatures(f)
    })
    return () => {
      alive = false
    }
  }, [apiBase, fetcher])
  return features
}
