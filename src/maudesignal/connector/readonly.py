"""Keep the connector's copilot read-only: no tool that writes can be offered or run.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

The copilot's tool set includes ``draft_capa``, which inserts a draft row. The connector
promises read-only, so this wrapper (a) removes every tool outside :data:`READ_ONLY_TOOLS`
from the tool list sent to the model and (b) if the model calls one anyway, renames the
call to :data:`REFUSED_TOOL`, which the copilot's dispatcher answers with an error. A new
copilot tool is refused until someone lists it here (a test enforces that every tool is
classified).
"""

from __future__ import annotations

from typing import Any

#: Tools that only read stored records.
READ_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        "overnight_signals",
        "product_summary",
        "search_reports",
        "get_report",
        "deadline_check",
        "recalls",
        "device_510k",
        "literature",
        "report_sources",
        "my_device_types",
        "compare_signals",
        "mhra_alerts",
    }
)
#: Tools that write; never offered, never run.
WRITE_TOOLS: frozenset[str] = frozenset({"draft_capa"})
#: Name a refused call is rewritten to (not a real tool, so the dispatcher returns an error).
REFUSED_TOOL = "refused_write_tool"


def _tool_name(schema: dict[str, Any]) -> str:
    fn = schema.get("function")
    return str(fn.get("name", "")) if isinstance(fn, dict) else ""


class _Completions:
    def __init__(self, owner: ReadOnlyClient) -> None:
        self._owner = owner

    def create(self, **kwargs: Any) -> Any:
        tools = kwargs.get("tools")
        if tools:
            kwargs["tools"] = [t for t in tools if _tool_name(t) in READ_ONLY_TOOLS]
        resp = self._owner.inner.chat.completions.create(**kwargs)
        for choice in getattr(resp, "choices", None) or []:
            for call in getattr(getattr(choice, "message", None), "tool_calls", None) or []:
                name = str(getattr(call.function, "name", ""))
                if name not in READ_ONLY_TOOLS:
                    self._owner.refused.append(name)
                    call.function.name = REFUSED_TOOL
        return resp


class _Chat:
    def __init__(self, owner: ReadOnlyClient) -> None:
        self.completions = _Completions(owner)


class ReadOnlyClient:
    """OpenAI-style client whose tool use is limited to :data:`READ_ONLY_TOOLS`."""

    def __init__(self, inner: Any) -> None:
        """Wrap ``inner`` (anything with ``chat.completions.create``)."""
        self.inner = inner
        self.refused: list[str] = []
        self.chat = _Chat(self)


def make_read_only(agent: Any) -> ReadOnlyClient:
    """Wrap a copilot agent's model client so it cannot offer or run a writing tool.

    The agent keeps its client in ``_client``; there is no public setter, and the copilot
    package is owned by another track, so the wrapper is applied here.
    """
    client = agent._client
    if isinstance(client, ReadOnlyClient):
        return client
    wrapped = ReadOnlyClient(client)
    agent._client = wrapped
    return wrapped
