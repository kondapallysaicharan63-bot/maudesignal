import { renderToStaticMarkup } from 'react-dom/server'
import { beforeAll, describe, expect, it } from 'vitest'
import audit from '../public/data/audit.json'
import briefs from '../public/data/briefs.json'
import dossier from '../public/data/dossier.json'
import evidence from '../public/data/evidence.json'
import investigations from '../public/data/investigations.json'
import manifest from '../public/data/manifest.json'
import protocol from '../public/data/protocol.json'
import schedules from '../public/data/schedules.json'
import sources from '../public/data/sources.json'
import sweep from '../public/data/sweep.json'
import threads from '../public/data/threads.json'
import vision from '../public/data/vision.json'
import { ChatPane } from './components/ChatPane'
import { RunList, RunView } from './components/InvestigationViews'
import { Sidebar } from './components/Sidebar'
import { visibleWorkflows, WORKFLOWS } from './data'
import type { InvestigationRun, WorkspaceData } from './types'

beforeAll(() => {
  // Components read prefers-reduced-motion while rendering; the server render has no window.
  ;(globalThis as unknown as { window: unknown }).window = { matchMedia: () => ({ matches: true }) }
})

/** A sample of what Track A's recorder will write (shape from web/DATA_CONTRACT.md). Not real data. */
const SAMPLE_RUN: InvestigationRun = {
  id: 'sample-weekly-LLZ',
  kind: 'weekly-investigator',
  product_code: 'LLZ',
  trigger: 'Weekly check flagged LLZ: reports suddenly increased',
  recorded_at_utc: '2026-11-02T09:00:00Z',
  model: 'muse-spark-1.3',
  tool_steps: [{ name: 'search_reports', arguments: {}, summary: 'searched stored reports' }],
  sentences: [
    {
      text: 'Sample sentence about the grouped reports.',
      status: 'pass',
      reasons: [],
      claims: [{ kind: 'group_count', status: 'pass', reason: 'recomputed 2', evidence_ids: [] }],
    },
  ],
  groups: [{ label: 'Image not displayed', report_ids: ['111', '222'], count: 2 }],
}

const SAMPLE_RECALL: InvestigationRun = { ...SAMPLE_RUN, id: 'sample-recall-LLZ', kind: 'recall-sweep' }

// The banned wording is assembled so this file itself stays free of it.
const SOON = ['coming', 'soon'].join(' ')
const SOON_RE = new RegExp(SOON, 'i')

const text = (html: string) =>
  html
    .replace(/<[^>]+>/g, ' ')
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')

const data = (runs: InvestigationRun[]): WorkspaceData =>
  ({
    manifest,
    threads,
    briefs: briefs.briefs,
    sources: sources.sources,
    schedules: schedules.schedules,
    investigations: { investigations: runs, notes: investigations.notes },
    evidence,
    audit,
    dossier,
    vision,
    sweep,
    protocol,
  }) as unknown as WorkspaceData

const sidebar = (runs: InvestigationRun[]) =>
  renderToStaticMarkup(
    <Sidebar
      open={false}
      collapsed={false}
      threads={threads as never}
      briefs={briefs.briefs as never}
      sources={sources.sources}
      schedules={schedules.schedules as never}
      runs={runs}
      vision={vision as never}
      sweep={sweep as never}
      activeWorkflow={null}
      activeBrief={null}
      isRead={() => true}
      onNewChat={() => {}}
      onWorkflow={() => {}}
      onBrief={() => {}}
      onClose={() => {}}
    />,
  )

describe('workflows with no recorded run are hidden, not shown as placeholders', () => {
  it('stored investigations.json has no run yet', () => {
    expect(investigations.investigations).toEqual([])
  })

  it('with an empty list the sidebar and the palette list neither agentic workflow nor Intake inbox', () => {
    const ids = visibleWorkflows([]).map((w) => w.id)
    expect(ids).not.toContain('weekly-investigator')
    expect(ids).not.toContain('recall-sweep')
    expect(WORKFLOWS.map((w) => w.title.toLowerCase())).not.toContain('intake inbox')
    const t = text(sidebar([]))
    expect(t).not.toMatch(new RegExp(`weekly investigator|recall sweep|intake inbox|${SOON}|no runs yet`, 'i'))
    expect(t).toContain('Check any device type')
    expect(t).toContain('AI device sweep')
  })

  it('with a sample run only that kind appears, with its run count', () => {
    expect(visibleWorkflows([SAMPLE_RUN]).map((w) => w.id)).toContain('weekly-investigator')
    expect(visibleWorkflows([SAMPLE_RUN]).map((w) => w.id)).not.toContain('recall-sweep')
    const t = text(sidebar([SAMPLE_RUN]))
    expect(t).toMatch(/Weekly investigator\s*1/)
    expect(t).not.toMatch(/Recall sweep/)
    const both = text(sidebar([SAMPLE_RUN, SAMPLE_RECALL]))
    expect(both).toMatch(/Recall sweep\s*1/)
  })
})

describe('recorded runs render from investigations.json', () => {
  it('lists the runs of one kind', () => {
    const html = text(
      renderToStaticMarkup(
        <RunList kind="weekly-investigator" runs={[SAMPLE_RUN, SAMPLE_RECALL]} notes={[]} onRun={() => {}} />,
      ),
    )
    expect(html).toContain('Weekly investigator')
    expect(html).toContain('1 recorded run')
    expect(html).toContain('LLZ')
    expect(html).toContain('Weekly check flagged LLZ')
    expect(html).not.toContain('sample-recall-LLZ')
  })

  it('renders a run: steps, gated sentences, groups', () => {
    const html = text(
      renderToStaticMarkup(<RunView run={SAMPLE_RUN} ev={evidence as never} onThread={() => {}} />),
    )
    expect(html).toContain('Weekly investigator')
    expect(html).toContain('Search reports')
    expect(html).toContain('Sample sentence about the grouped reports.')
    expect(html).toContain('Image not displayed')
    expect(html).toContain('2 reports')
  })

  it('an empty list renders an honest empty page, not a placeholder promise', () => {
    const html = text(renderToStaticMarkup(<RunList kind="recall-sweep" runs={[]} notes={['No recorded runs yet.']} onRun={() => {}} />))
    expect(html).toContain('0 recorded runs')
    expect(html).not.toMatch(SOON_RE)
  })
})

describe('first screen and the placeholder wording', () => {
  it('leads with the AI device sweep card, read from sweep.json', () => {
    const raw = renderToStaticMarkup(
        <ChatPane
          view={{ kind: 'new' }}
          data={data([])}
          withheld={null}
          onWorkflow={() => {}}
          onThread={() => {}}
          onRun={() => {}}
          onVision={() => {}}
        onCode={() => {}}
        onCapture={() => {}}
          onBrief={() => {}}
          onAlert={() => {}}
          expanded={false}
          onToggleExpand={() => {}}
        />,
      )
    const html = text(raw)
    const flagged = sweep.rows.filter((r) => r.classification !== 'stable').length
    const lead = `${flagged} flagged of ${sweep.meta.codes_on_list} product codes on FDA's AI-enabled device list`
    expect(html).toContain(lead)
    expect(html).toContain(`Checked ${sweep.meta.generated_utc.slice(0, 10)}`)
    expect(html.indexOf('AI device sweep')).toBeLessThan(html.indexOf('Workflows'))
    expect(html).not.toMatch(SOON_RE)
    // the composer: one input row ("Ask a question"), the recorded questions are a type-ahead list, no menu
    expect(raw).toContain('placeholder="Ask a question"')
    expect(html).not.toMatch(/GitHub|Google Drive|Upload file|Connected sources/)
  })
})
