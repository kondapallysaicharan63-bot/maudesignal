import { fmtStepMs, type AskResponse } from '../live/api'
import { tierLabel, totalMs } from '../live/answerMeta'
import { LiveTrace } from './LiveTrace'

/** "$0.0123", "$0.0000 (no model call)" or "not reported" (the server sent null). */
export function costText(resp: Pick<AskResponse, 'cost_usd' | 'tier'>): string {
  if (typeof resp.cost_usd !== 'number') return 'not reported'
  const free = resp.tier === 'canned' || resp.tier === 'direct' || resp.tier === 'cache'
  return `$${resp.cost_usd.toFixed(4)}${free ? ' (no model call)' : ''}`
}

/**
 * The closed-by-default Details of one answer: which route answered, the step trace with models and timings,
 * the total time, the cost and, when the server sends them, tokens. Nothing here is shown in the main view.
 */
export function AnswerDetails({ resp, id }: { resp: AskResponse; id: string }) {
  const total = totalMs(resp.trace)
  const tokens = resp.usage
  return (
    <div className="ans-panel" id={id} data-testid="answer-details" role="region" aria-label="Details of this answer">
      <dl>
        <dt>Route</dt>
        <dd data-testid="details-tier">{tierLabel(resp)}</dd>
        {resp.badge && (
          <>
            <dt>Note</dt>
            <dd>{resp.badge}</dd>
          </>
        )}
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
          <LiveTrace steps={resp.trace} />
        </>
      )}
    </div>
  )
}
