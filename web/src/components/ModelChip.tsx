import type { Chip } from '../live/answerMeta'

/** One small quiet chip under an answer: "Muse Spark 1.3 · Live", "Instant answer", "Cached", "Recorded · Oct 28, 2026". */
export function ModelChip({ chip }: { chip: Chip }) {
  return (
    <span className="ans-chip" data-testid="model-chip" data-kind={chip.kind}>
      {chip.text}
    </span>
  )
}
