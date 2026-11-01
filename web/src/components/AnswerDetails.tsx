import { fmtStepMs, type AskResponse, type LiveTraceStep } from '../live/api'
import { modelName, stepNote, tierLabel, totalMs } from '../live/answerMeta'

/** "$0.0123", "$0.0000 (no model call)" or "not reported" (the server sent null). */
export function costText(resp: Pick<AskResponse, 'cost_usd' | 'tier'>): string {
  if (typeof resp.cost_usd !== 'number') return 'not reported'
  const free = resp.tier === 'canned' || resp.tier === 'direct' || resp.tier === 'cache'
  return `$${resp.cost_usd.toFixed(4)}${free ? ' (no model call)' : ''}`
}

const STATUS_WORD: Record<LiveTraceStep['status'], string> = {
  ok: 'done',
  skipped: 'skipped',
  failed: 'failed',
  not_searched: 'not searched',
  unknown: 'unknown',
}

function StepIcon({ status }: { status: LiveTraceStep['status'] }) {
  const ok = status === 'ok'
  return (
    <span className={`ans-step-icon${ok ? '' : ' ans-step-icon--off'}`}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
        <path d={ok ? 'm5 12.5 4.5 4.5L19 7.5' : status === 'failed' ? 'M6 6l12 12M18 6 6 18' : 'M6 12h12'} />
      </svg>
      <span className="sr-only">{STATUS_WORD[status]}</span>
    </span>
  )
}

/** One step in two lines at most: its name, then model, time and outcome note (cut with an ellipsis, full text on hover). */
function Step({ s }: { s: LiveTraceStep }) {
  const meta = [modelName(s.model), fmtStepMs(s.ms), s.status !== 'ok' ? STATUS_WORD[s.status] : null, stepNote(s.note)]
    .filter((x): x is string => !!x)
    .join(' · ')
  return (
    <li className="ans-step" data-testid="trace-step">
      <StepIcon status={s.status} />
      <span className="ans-step-name">{s.step}</span>
      <span className="ans-step-meta ms-num" title={meta}>
        {meta}
      </span>
    </li>
  )
}

/**
 * The closed-by-default Details of one answer: which route answered, the steps with models and timings, the total
 * time, the cost and, when the server sends them, tokens. Nothing here is shown in the main view.
 */
export function AnswerDetails({ resp, id }: { resp: AskResponse; id: string }) {
  const total = totalMs(resp.trace)
  const tokens = resp.usage
  return (
    <div className="ans-panel" id={id} data-testid="answer-details" role="region" aria-label="Details of this answer">
      <dl>
        <dt>Route</dt>
        <dd data-testid="details-tier">{tierLabel(resp)}</dd>
        <dt>Cost</dt>
        <dd className="ms-num" data-testid="details-cost">
          {costText(resp)}
        </dd>
        {tokens && (
          <>
            <dt>Tokens</dt>
            <dd className="ms-num" data-testid="details-tokens">
              {typeof tokens.input_tokens === 'number' ? `${tokens.input_tokens} in` : ''}
              {typeof tokens.input_tokens === 'number' && typeof tokens.output_tokens === 'number' ? ' · ' : ''}
              {typeof tokens.output_tokens === 'number' ? `${tokens.output_tokens} out` : ''}
            </dd>
          </>
        )}
        {total !== null && (
          <>
            <dt>Time</dt>
            <dd className="ms-num" data-testid="details-time">
              {fmtStepMs(total)} across {resp.trace.length} {resp.trace.length === 1 ? 'step' : 'steps'}
            </dd>
          </>
        )}
        {resp.tier === 'cache' && resp.answered_at && (
          <>
            <dt>First answered</dt>
            <dd className="ms-num">{resp.answered_at.slice(11, 16)} UTC</dd>
          </>
        )}
      </dl>
      {resp.trace.length > 0 && (
        <>
          <p className="ans-sub">Steps</p>
          <ol className="ans-steps" aria-label="Steps of this run" data-testid="live-trace">
            {resp.trace.map((s, i) => (
              <Step key={i} s={s} />
            ))}
          </ol>
        </>
      )}
    </div>
  )
}
