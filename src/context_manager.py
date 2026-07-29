from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from src.session import Session


@dataclass(frozen=True)
class ContextPolicy:
    max_estimated_tokens: int = 6000
    keep_recent_user_turns: int = 4
    max_summary_chars: int = 3000
    max_item_chars: int = 300


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def _summarize_messages(messages: list[dict[str, Any]], max_item_chars: int) -> list[str]:
    entries: list[str] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if content is None:
                content = ""
            entries.append(f"- 用户请求：{_truncate(content, max_item_chars)}")
            i += 1
        elif msg.get("role") == "assistant" and "tool_calls" in msg:
            for tc in msg["tool_calls"]:
                name = tc["function"]["name"]
                raw_args = tc["function"].get("arguments", "{}")
                entries.append(f"- 调用工具：{name}，{_truncate(raw_args, max_item_chars)}")
            i += 1
        elif msg.get("role") == "tool":
            name = msg.get("name", "?")
            content = msg.get("content", "")
            if content is None:
                content = ""
            entries.append(f"- 工具结果（{name}）：{_truncate(content, max_item_chars)}")
            i += 1
        elif msg.get("role") == "assistant":
            content = msg.get("content", "")
            if content is None:
                content = ""
            entries.append(f"- 助手回答：{_truncate(content, max_item_chars)}")
            i += 1
        else:
            i += 1
    return entries


def _merge_summary(existing: str, new_entries: list[str], max_chars: int) -> str:
    new_text = "\n".join(new_entries)

    if not existing:
        if len(new_text) <= max_chars:
            return new_text
        return new_text[:max_chars] + "\n(较早内容已进一步压缩)"

    combined = existing + "\n" + new_text
    if len(combined) <= max_chars:
        return combined

    space_for_new = max_chars - 50
    if len(new_text) > space_for_new:
        return new_text[:space_for_new] + "\n(较早内容已进一步压缩)"

    space_for_old = max_chars - len(new_text) - 1
    if space_for_old > 20:
        trimmed_old = existing[-space_for_old:]
        return trimmed_old + "\n" + new_text

    return new_text + "\n(较早内容已进一步压缩)"


def _find_compress_boundary(messages: list[dict[str, Any]], keep_turns: int) -> int:
    user_count = sum(1 for m in messages if m.get("role") == "user")
    if user_count <= keep_turns:
        return 0

    turns_to_skip = user_count - keep_turns
    seen = 0
    for i, msg in enumerate(messages):
        if msg.get("role") == "user":
            seen += 1
            if seen > turns_to_skip:
                return i
    return len(messages)


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    if not messages:
        return 0
    text = json.dumps(messages, ensure_ascii=False, default=str)
    return max(1, len(text) // 4)


class ContextManager:
    def __init__(self, policy: ContextPolicy | None = None) -> None:
        self._policy = policy or ContextPolicy()

    def prepare_session(self, session: Session) -> bool:
        if not session.messages:
            return False

        current_estimate = estimate_tokens(session.messages)
        if current_estimate < self._policy.max_estimated_tokens:
            return False

        boundary = _find_compress_boundary(
            session.messages, self._policy.keep_recent_user_turns
        )
        if boundary <= 0:
            return False

        to_compress = session.messages[:boundary]
        summary_entries = _summarize_messages(to_compress, self._policy.max_item_chars)
        new_summary = _merge_summary(
            session.summary, summary_entries, self._policy.max_summary_chars
        )
        session.summary = new_summary
        session.messages = session.messages[boundary:]
        return True

    def build_messages(
        self,
        *,
        system_prompt: str,
        session: Session,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        if session.summary:
            result.append(
                {
                    "role": "system",
                    "content": (
                        "Session memory summary. Treat this as previous conversation "
                        "context, but prefer current tool results when conflicts exist:\n"
                        + session.summary
                    ),
                }
            )
        result.extend(session.messages)
        return result
