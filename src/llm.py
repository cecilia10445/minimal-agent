from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall]
    decision_summary: str | None = None


@runtime_checkable
class LLMClient(Protocol):
    def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        ...


class ScriptedLLMClient:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self._index = 0
        self.call_history: list[dict[str, Any]] = []

    def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        if self._index >= len(self._responses):
            raise RuntimeError(
                f"ScriptedLLMClient exhausted: no more preset responses "
                f"(used {len(self._responses)} responses)"
            )
        self.call_history.append(
            {"messages": list(messages), "tools": list(tools)}
        )
        resp = self._responses[self._index]
        self._index += 1
        return resp

    @property
    def current_index(self) -> int:
        return self._index
