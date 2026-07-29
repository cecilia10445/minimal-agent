from __future__ import annotations

import json
import time
from typing import Any, Protocol

from openai import OpenAI

from src.config import LLMSettings


class SemanticSummarizer(Protocol):
    def summarize(
        self,
        *,
        previous_summary: str,
        messages: list[dict[str, Any]],
        max_output_chars: int,
    ) -> str:
        ...


SUMMARY_SYSTEM_PROMPT = """You are a conversation memory summarizer. Your job is to produce a concise structured summary of the old conversation turns provided below.

Output ONLY a JSON object with these fields (each is an array of strings):
- "goals": user's current goals
- "confirmed_facts": confirmed facts still relevant
- "latest_corrections": corrections that override earlier facts
- "preferences": user's answer format or work preferences
- "constraints": prohibited items, technical boundaries
- "completed_actions": important completed actions
- "open_items": unresolved issues or follow-ups
- "document_references": important document names and their purpose

Rules:
1. Only extract facts present in the input.
2. Later corrections override older values.
3. Do not fabricate information.
4. Do not store full chain-of-thought.
5. Do not store API keys or environment variables.
6. Each field must be an array of strings.
7. The total output must be within the character limit.
8. Output ONLY the JSON object, no other text."""


_SEMANTIC_FIELDS = [
    "goals",
    "confirmed_facts",
    "latest_corrections",
    "preferences",
    "constraints",
    "completed_actions",
    "open_items",
    "document_references",
]


def _format_semantic_summary(parsed: dict[str, Any], max_chars: int) -> str:
    lines: list[str] = []
    for field in _SEMANTIC_FIELDS:
        values = parsed.get(field)
        if not isinstance(values, list) or len(values) == 0:
            continue
        label = field.replace("_", " ").title()
        lines.append(f"{label}:")
        for v in values:
            if not isinstance(v, str):
                continue
            lines.append(f"- {v}")
        lines.append("")
    text = "\n".join(lines).strip()
    if not text:
        return ""
    if len(text) > max_chars:
        text = text[:max_chars] + "\n(truncated)"
    return text


def _validate_semantic_json(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("Semantic summary is not a JSON object")
    for field in _SEMANTIC_FIELDS:
        values = data.get(field)
        if values is None:
            data[field] = []
        elif not isinstance(values, list):
            raise ValueError(f"Field '{field}' must be an array")
        else:
            for i, v in enumerate(values):
                if not isinstance(v, str):
                    raise ValueError(
                        f"Field '{field}' element {i} must be a string"
                    )
    return data


class QwenSemanticSummarizer:
    def __init__(
        self,
        *,
        settings: LLMSettings,
        summary_model: str | None = None,
    ) -> None:
        self._settings = settings
        self._model = summary_model or settings.model
        self._client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=settings.request_timeout,
            max_retries=0,
        )

    def summarize(
        self,
        *,
        previous_summary: str,
        messages: list[dict[str, Any]],
        max_output_chars: int,
    ) -> str:
        import openai

        user_content = (
            f"Previous summary:\n{previous_summary}\n\n"
            if previous_summary
            else ""
        )
        user_content += "Messages to summarize:\n"
        for m in messages:
            role = m.get("role", "?")
            content = m.get("content", "")
            if content is None:
                content = ""
            user_content += f"\n[{role}]: {content}"
            if "tool_calls" in m:
                for tc in m["tool_calls"]:
                    user_content += (
                        f"\n  [tool_call: {tc['function']['name']}]"
                    )

        try:
            raw = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
        except (openai.APITimeoutError, openai.APIConnectionError) as e:
            raise RuntimeError(f"Semantic summary network error: {e}") from e
        except openai.RateLimitError as e:
            raise RuntimeError(f"Semantic summary rate limited: {e}") from e
        except openai.AuthenticationError as e:
            raise RuntimeError(f"Semantic summary auth error: {e}") from e
        except openai.APIStatusError as e:
            raise RuntimeError(f"Semantic summary API error: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Semantic summary error: {e}") from e

        if not raw.choices:
            raise RuntimeError("Semantic summary: no choices")
        content = raw.choices[0].message.content
        if not content:
            raise RuntimeError("Semantic summary: empty content")

        parsed = json.loads(content)
        parsed = _validate_semantic_json(parsed)
        return _format_semantic_summary(parsed, max_output_chars)
