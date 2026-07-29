from __future__ import annotations

import json
from typing import Any

import openai
from openai import OpenAI

from src.config import LLMSettings
from src.llm import LLMClient, LLMResponse, ToolCall


class LLMAuthenticationError(Exception):
    ...


class LLMRateLimitError(Exception):
    ...


class LLMTimeoutError(Exception):
    ...


class LLMServiceError(Exception):
    ...


class LLMResponseParseError(Exception):
    ...


_OPENAI_TO_OUR_ERROR: dict[type, type] = {
    openai.AuthenticationError: LLMAuthenticationError,
    openai.RateLimitError: LLMRateLimitError,
    openai.APITimeoutError: LLMTimeoutError,
    openai.APIConnectionError: LLMServiceError,
}


def _map_openai_error(exc: openai.OpenAIError) -> Exception:
    our_type = _OPENAI_TO_OUR_ERROR.get(type(exc), LLMServiceError)
    msg = str(exc)
    return our_type(msg)


def _parse_message(message: Any) -> LLMResponse:
    content: str | None = getattr(message, "content", None)
    raw_tool_calls: list[Any] = getattr(message, "tool_calls", None) or []

    tool_calls: list[ToolCall] = []
    for tc in raw_tool_calls:
        raw_args = getattr(tc.function, "arguments", "{}")
        try:
            parsed = json.loads(raw_args)
        except json.JSONDecodeError as e:
            raise LLMResponseParseError(
                f"Tool call '{tc.function.name}' arguments are not valid JSON: {e}"
            ) from e
        if not isinstance(parsed, dict):
            raise LLMResponseParseError(
                f"Tool call '{tc.function.name}' arguments must be a JSON object, "
                f"got {type(parsed).__name__}"
            )
        tool_calls.append(
            ToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=parsed,
            )
        )

    decision_summary: str | None = None
    if content and not tool_calls:
        decision_summary = content[:200] if len(content) > 200 else content
    elif content and tool_calls:
        decision_summary = content[:200] if len(content) > 200 else content

    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        decision_summary=decision_summary,
    )


class OpenAICompatibleLLMClient:
    def __init__(
        self,
        settings: LLMSettings,
        sdk_client: OpenAI | None = None,
    ) -> None:
        self._settings = settings
        if sdk_client is not None:
            self._client = sdk_client
        else:
            self._client = OpenAI(
                api_key=settings.api_key,
                base_url=settings.base_url,
                timeout=settings.request_timeout,
                max_retries=settings.max_retries,
            )

    def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        try:
            raw = self._client.chat.completions.create(
                model=self._settings.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0,
                extra_body={
                    "enable_thinking": self._settings.enable_thinking,
                },
            )
        except openai.APITimeoutError as e:
            raise _map_openai_error(e) from e
        except openai.APIConnectionError as e:
            raise _map_openai_error(e) from e
        except openai.RateLimitError as e:
            raise _map_openai_error(e) from e
        except openai.AuthenticationError as e:
            raise _map_openai_error(e) from e
        except openai.APIStatusError as e:
            raise _map_openai_error(e) from e
        except openai.OpenAIError as e:
            raise LLMServiceError(str(e)) from e

        if not raw.choices:
            raise LLMResponseParseError(
                "LLM response has no choices."
            )

        message = raw.choices[0].message
        if message is None:
            raise LLMResponseParseError(
                "LLM response choice has no message."
            )

        return _parse_message(message)
