import { useEffect, useState } from 'react'
import type { Brief, Investigations, Manifest, Schedule, Source, Threads, WorkspaceData, WorkflowDef } from './types'

const base = import.meta.env.BASE_URL

async function getJson<T>(name: string): Promise<T> {
  const res = await fetch(`${base}data/${name}`)
  if (!res.ok) throw new Error(`${name}: HTTP ${res.status}`)
  return (await res.json()) as T
}

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
    ])
      .then(([manifest, threads, briefs, sources, schedules, investigations]) => {
        if (live)
          setData({
            manifest,
            threads,
            briefs: briefs.briefs,
            sources: sources.sources,
            schedules: schedules.schedules,
            investigations,
          })
      })
      .catch((e: unknown) => live && setError(e instanceof Error ? e.message : String(e)))
    return () => {
      live = false
    }
  }, [])
  return { data, error }
}

export const WORKFLOWS: WorkflowDef[] = [
  {
    id: 'overnight-signals',
    title: 'What changed this week',
    blurb: 'Which device types had a new kind of problem, more serious reports than usual, or a sudden rise in reports.',
  },
  {
    id: 'ask-copilot',
    title: 'Ask the copilot',
    blurb: 'Questions answered from stored records. Each sentence is checked before you see it.',
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
    comingSoon: true,
  },
  {
    id: 'recall-sweep',
    title: 'Recall sweep',
    blurb: 'When a recall is posted, finds stored reports that describe the same problem.',
    comingSoon: true,
  },
  {
    id: 'vision',
    title: 'Label & 510(k) vision',
    blurb: 'Reads a 510(k) summary page or a device label photo and checks each field against openFDA.',
    comingSoon: true,
  },
  {
    id: 'intake',
    title: 'Intake inbox',
    blurb: 'Reports arriving from chat channels.',
    comingSoon: true,
  },
]

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
