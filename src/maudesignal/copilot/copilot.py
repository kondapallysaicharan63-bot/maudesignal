"""Conversational safety copilot for MaudeSignal.

HACKATHON-BUILT — created during the Meta Global AI Developer Hackathon
(Oct 26 – Nov 4, 2026). This module did not exist before the hackathon.

What it does (Day 1 skeleton; retrieval + citation gate land Days 2–3):
    A quality or regulatory engineer asks a plain-English question and gets
    a streamed answer from a Meta model, grounded in MaudeSignal's signal
    pipeline output.

Design constraints (from the hackathon rules + the project's own principles):
    - The copilot NEVER gives medical advice to patients. It is a B2B tool
      for quality/regulatory professionals analyzing device safety signals.
    - Every factual claim in an answer must trace to a pipeline record or a
      verified primary source (citation hard-gate, Days 2–3).
    - The copilot is NEW hackathon work. The pre-existing pipeline (ingest,
      extract, classify, drift, report) is the base it reads from — it is
      not presented as hackathon-built.
"""

from __future__ import annotations

from collections.abc import Iterator

from maudesignal.copilot.meta_provider import MetaProvider
from maudesignal.extraction.llm_providers.base import LLMMessage

_COPILOT_SYSTEM_PROMPT = """You are MaudeSignal Copilot, a safety-analysis assistant for quality and
regulatory professionals working on FDA-cleared AI/ML medical devices.

Rules:
- You analyze postmarket safety signals (adverse events, drift, trends). You
  do NOT give medical advice, diagnoses, or treatment recommendations to
  patients. If asked for medical advice, decline and say you support
  regulatory professionals only.
- Ground every factual claim in the signal records provided in context.
  Never invent a citation, a report number, or a statistic.
- When you are unsure, say so and say what would resolve it.
- Be concise. Lead with the answer, then the evidence.
"""


class SafetyCopilot:
    """Conversational copilot over MaudeSignal's signal pipeline."""

    def __init__(self, provider: MetaProvider) -> None:
        """Create a copilot bound to a Meta provider.

        Args:
            provider: Configured MetaProvider (key from env var).
        """
        self._provider = provider

    def ask_stream(
        self,
        question: str,
        *,
        context: str = "",
        max_tokens: int = 2048,
    ) -> Iterator[str]:
        """Stream an answer to a plain-English question.

        Args:
            question: The user's question.
            context: Pipeline records (signals, trends) to ground the answer.
                Day 1: caller-supplied text. Days 2–3: retrieved from the
                signal store automatically.
            max_tokens: Maximum output tokens.

        Yields:
            Text deltas as they arrive from the model.
        """
        user_content = question
        if context:
            user_content = f"Signal records for grounding:\n{context}\n\n" f"Question: {question}"
        yield from self._provider.complete_stream(
            system_prompt=_COPILOT_SYSTEM_PROMPT,
            messages=[LLMMessage(role="user", content=user_content)],
            max_tokens=max_tokens,
            temperature=0.0,
        )

    def ask(
        self,
        question: str,
        *,
        context: str = "",
        max_tokens: int = 2048,
    ) -> str:
        """Ask a question and return the full answer (non-streaming)."""
        return "".join(self.ask_stream(question, context=context, max_tokens=max_tokens))
