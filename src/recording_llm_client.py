"""Wrapper LLMClient that records call metadata without modifying behavior.

Records per-call metadata: message count, token estimate, tool calls, latency, etc.
Delegates complete() to the wrapped client without modification.
"""

import hashlib
import time
from typing import Any

from src.context_manager import estimate_tokens
from src.llm import LLMClient, LLMResponse


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _preview(text: str | None, max_len: int = 80) -> str:
    if text is None:
        return "None"
    s = str(text)
    if len(s) <= max_len:
        return s
    return s[:max_len] + "..."


class RecordingLLMClient:
    """Wraps an LLMClient and records every call for analysis.

    Does not modify the wrapped client's behavior or execute tools.
    """

    def __init__(self, wrapped: LLMClient) -> None:
        self._wrapped = wrapped
        self.records: list[dict[str, Any]] = []
        self._call_count = 0

    def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        import copy
        # Snapshot input messages (sanitized)
        msg_count = len(messages)
        msg_roles = [m.get("role", "?") for m in messages]
        estimated_tokens = estimate_tokens(messages)
        summary_present = any(
            "Session memory summary" in (m.get("content", "") or "")
            for m in messages
        )
        summary_chars = 0
        for m in messages:
            if "Session memory summary" in (m.get("content", "") or ""):
                summary_chars = len(m.get("content", "") or "")
        tool_schema_count = len(tools) if tools else 0

        # Capture time before
        start = time.monotonic()
        try:
            response = self._wrapped.complete(messages=messages, tools=tools)
            success = True
            error = None
        except Exception as e:
            success = False
            error = str(e)
            raise
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000

        if not success:
            return  # type: ignore [unreachable]

        # Tool names returned
        returned_tool_names = [tc.name for tc in response.tool_calls] if response.tool_calls else []

        # Sanitize: don't store full content for long strings
        # Store length, SHA-256, and preview
        sanitized_messages = []
        for m in messages:
            entry: dict[str, Any] = {"role": m.get("role", "?")}
            content = m.get("content")
            if content:
                entry["content_len"] = len(content)
                entry["content_sha256"] = _sha256(str(content))
                entry["content_preview"] = _preview(str(content), 100)
            else:
                entry["content"] = None
            if "tool_calls" in m:
                entry["tool_call_count"] = len(m["tool_calls"])
            if "tool_call_id" in m:
                entry["tool_call_id"] = m["tool_call_id"]
                tc_content = m.get("content", "")
                if tc_content:
                    entry["tool_result_len"] = len(tc_content)
                    entry["tool_result_sha256"] = _sha256(tc_content)
                    entry["tool_result_preview"] = _preview(tc_content, 60)
            sanitized_messages.append(entry)

        record = {
            "call_index": self._call_count,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "success": success,
            "error": error,
            "latency_ms": round(elapsed_ms, 1),
            "message_count": msg_count,
            "message_roles": msg_roles,
            "estimated_input_tokens": estimated_tokens,
            "summary_present": summary_present,
            "summary_chars": summary_chars,
            "tool_schema_count": tool_schema_count,
            "returned_tool_names": returned_tool_names,
            "returned_content_chars": len(response.content) if response.content else 0,
            "decision_summary_present": response.decision_summary is not None,
        }

        self.records.append(record)
        self._call_count += 1
        return response

    @property
    def total_calls(self) -> int:
        return self._call_count
