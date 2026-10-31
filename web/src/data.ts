import { useEffect, useState } from 'react'
import { parseAlerts } from './alerts'
import type { MentionsFile } from './mentions'
import type {
  Audit,
  Brief,
  Company,
  Dossier,
  Evidence,
  InvestigationRun,
  Investigations,
  Manifest,
  Protocol,
  Schedule,
  Source,
  Sweep,
  Threads,
  Vision,
  WorkflowDef,
  WorkspaceData,
} from './types'

const base = import.meta.env.BASE_URL

async function getJson<T>(name: string): Promise<T> {
  const res = await fetch(`${base}data/${name}`)
  if (!res.ok) throw new Error(`${name}: HTTP ${res.status}`)
  return (await res.json()) as T
}

/** A file the workspace can do without (alerts.json, mentions.json): null when it is missing or is not JSON of the expected kind. */
async function getOptional<T>(name: string, ok: (raw: unknown) => T | null): Promise<T | null> {
  try {
    const res = await fetch(`${base}data/${name}`)
    if (!res.ok) return null
    return ok(await res.json())
  } catch {
    return null
  }
}

const asMentions = (raw: unknown): MentionsFile | null =>
  typeof raw === 'object' && raw !== null && typeof (raw as MentionsFile).codes === 'object' ? (raw as MentionsFile) : null

/** Loads the stored exports. Everything works with no API key: these files are the data. */
export function useWorkspaceData(): { data: WorkspaceData | null; error: string | null } {
  const [data, setData] = useState<WorkspaceData | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    Promise.all([
      getJson<Manifest>('manifest.json'),
      getJson<Threads>('threads.json'),
      getJson<{ briefs: Brief[] }>('briefs.json'),
      getJson<{ sources: Source[] }>('sources.json'),
      getJson<{ schedules: Schedule[] }>('schedules.json'),
      getJson<Investigations>('investigations.json'),
      getJson<Evidence>('evidence.json'),
      getJson<Audit>('audit.json'),
      getJson<Dossier>('dossier.json'),
      getJson<Vision>('vision.json'),
      getJson<Sweep>('sweep.json'),
      getJson<Protocol>('protocol.json'),
      getJson<Company>('company.json'),
      getOptional('alerts.json', parseAlerts),
      getOptional('mentions.json', asMentions),
    ])
      .then(([manifest, threads, briefs, sources, schedules, investigations, evidence, audit, dossier, vision, sweep, protocol, company, alerts, mentions]) => {
        if (live)
          setData({
            manifest,
            threads,
            briefs: briefs.briefs,
            sources: sources.sources,
            schedules: schedules.schedules,
            investigations,
            evidence,
            audit,
            dossier,
            vision,
            sweep,
            protocol,
            company,
            alerts,
            mentions,
          })
      })
      .catch((e: unknown) => live && setError(e instanceof Error ? e.message : String(e)))
    return () => {
      live = false
    }
  }, [])
  return { data, error }
}

/** Where live questions run (the copilot calls the model there; the key stays on that server). */
export const STREAMLIT_URL = 'https://maudesignal-4vniqswm9ptaxqtf2iawox.streamlit.app/'

export const WORKFLOWS: WorkflowDef[] = [
  {
    id: 'ai-sweep',
    title: 'AI device sweep',
    blurb: "Every product code on FDA's AI-enabled device list, checked against openFDA. The newest real data in this workspace.",
  },
  {
    id: 'check-device',
    title: 'Check any device type',
    blurb: 'Type any FDA product code. The MaudeSignal API reads report counts from openFDA and applies the same four rules. Only the three-letter code is sent.',
  },
  {
    id: 'weekly-signals',
    title: 'What changed this week',
    blurb: 'Recorded answers about which device types had a new kind of problem, more serious reports than usual, or a sudden rise in reports.',
  },
  {
    id: 'ask-copilot',
    title: 'Ask the copilot',
    blurb: 'Recorded questions answered from stored records. Each sentence is checked before you see it.',
  },
  {
    id: 'capa-need-evidence',
    title: 'CAPA-need evidence',
    blurb: 'Evidence for a person deciding whether a corrective action is needed. Drafts only; nothing is filed.',
  },
  {
    id: 'weekly-investigator',
    title: 'Weekly investigator',
    blurb: 'Groups new reports for a flagged device type by kind of problem and checks recalls and 510(k)s.',
  },
  {
    id: 'recall-sweep',
    title: 'Recall sweep',
    blurb: 'When a recall is posted, finds stored reports that describe the same problem.',
  },
  {
    id: 'our-devices',
    title: 'Our devices (simulated)',
    blurb: 'Does this apply to us? A simulated company with fictional devices. The problem evidence next to each device is real FDA data.',
  },
  {
    id: 'vision',
    title: 'Label & 510(k) vision',
    blurb: 'Stored readings of 510(k) summary pages and device label photos; each field is checked against openFDA where a source covers it.',
  },
]

/** The two agentic workflows appear only once a recorded run of that kind exists (no placeholder before). */
export function visibleWorkflows(runs: InvestigationRun[]): WorkflowDef[] {
  const kinds = new Set<string>(runs.map((r) => r.kind))
  return WORKFLOWS.filter((w) => (w.id === 'weekly-investigator' || w.id === 'recall-sweep' ? kinds.has(w.id) : true))
}

/** Workflows whose recorded answers were made against the demo database, not this week's openFDA. */
export const DEMO_WORKFLOWS = ['weekly-signals', 'ask-copilot', 'capa-need-evidence']

/** "2026-09-24" from "20260924"; other text is returned as is. */
export function isoDay(d: string): string {
  return /^\d{8}$/.test(d) ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)}` : d
}

/**
 * The label every view built from the demo database or the August digests carries, with the date
 * the stored reports run to (newest date_received in the demo database, from sources.json).
 */
export function demoSnapshotLabel(sources: Source[]): string {
  const maude = sources.find((s) => s.id === 'maude')
  return maude?.last_refresh ? `Demo snapshot · reports to ${isoDay(maude.last_refresh)}` : 'Demo snapshot'
}

/** Plain-words reading of the two cron expressions the monitor uses; falls back to the raw text. */
export function describeCron(cron: string | null): string {
  if (!cron) return 'schedule not found'
  const m = /^(\d+) (\d+) \* \* (\*|\d)$/.exec(cron)
  if (!m) return cron
  const time = `${m[2].padStart(2, '0')}:${m[1].padStart(2, '0')} UTC`
  if (m[3] === '*') return `Every day at ${time}`
  const days = ['Sundays', 'Mondays', 'Tuesdays', 'Wednesdays', 'Thursdays', 'Fridays', 'Saturdays']
  return `${days[Number(m[3]) % 7]} at ${time}`
}
