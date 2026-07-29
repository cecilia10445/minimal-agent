from __future__ import annotations

import os
from dataclasses import dataclass

from src.context_manager import ContextPolicy


class LLMConfigurationError(Exception):
    ...


def _parse_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    raise LLMConfigurationError(
        f"Cannot parse boolean value: '{value}'. "
        f"Supported values: true/false, 1/0, yes/no."
    )


@dataclass(frozen=True)
class LLMSettings:
    api_key: str
    base_url: str
    model: str
    enable_thinking: bool
    request_timeout: float
    max_retries: int


def load_llm_settings() -> LLMSettings:
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise LLMConfigurationError(
            "DASHSCOPE_API_KEY is not set. "
            "Create a .env file based on .env.example and set your API key."
        )

    base_url = os.environ.get(
        "DASHSCOPE_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ).strip()
    if not base_url:
        raise LLMConfigurationError("DASHSCOPE_BASE_URL must not be empty.")

    model = os.environ.get("AGENT_MODEL", "qwen3.6-plus").strip()
    if not model:
        raise LLMConfigurationError("AGENT_MODEL must not be empty.")

    enable_thinking_str = os.environ.get("AGENT_ENABLE_THINKING", "false").strip()
    enable_thinking = _parse_bool(enable_thinking_str)

    timeout_str = os.environ.get("AGENT_REQUEST_TIMEOUT", "60").strip()
    try:
        request_timeout = float(timeout_str)
    except ValueError:
        raise LLMConfigurationError(
            f"AGENT_REQUEST_TIMEOUT must be a number, got '{timeout_str}'."
        )

    retries_str = os.environ.get("AGENT_MAX_RETRIES", "2").strip()
    try:
        max_retries = int(retries_str)
    except ValueError:
        raise LLMConfigurationError(
            f"AGENT_MAX_RETRIES must be an integer, got '{retries_str}'."
        )

    return LLMSettings(
        api_key=api_key,
        base_url=base_url,
        model=model,
        enable_thinking=enable_thinking,
        request_timeout=request_timeout,
        max_retries=max_retries,
    )


def _parse_positive_int(name: str, value: str | None, default: int) -> int:
    if value is None:
        return default
    stripped = value.strip()
    try:
        parsed = int(stripped)
    except ValueError:
        raise LLMConfigurationError(
            f"{name} must be a positive integer, got '{stripped}'."
        )
    if parsed <= 0:
        raise LLMConfigurationError(
            f"{name} must be a positive integer, got {parsed}."
        )
    return parsed


def load_context_policy() -> ContextPolicy:
    max_tokens = _parse_positive_int(
        "AGENT_CONTEXT_MAX_TOKENS",
        os.environ.get("AGENT_CONTEXT_MAX_TOKENS"),
        6000,
    )
    keep_turns = _parse_positive_int(
        "AGENT_CONTEXT_KEEP_RECENT_TURNS",
        os.environ.get("AGENT_CONTEXT_KEEP_RECENT_TURNS"),
        4,
    )
    max_summary = _parse_positive_int(
        "AGENT_CONTEXT_MAX_SUMMARY_CHARS",
        os.environ.get("AGENT_CONTEXT_MAX_SUMMARY_CHARS"),
        3000,
    )
    max_item = _parse_positive_int(
        "AGENT_CONTEXT_MAX_ITEM_CHARS",
        os.environ.get("AGENT_CONTEXT_MAX_ITEM_CHARS"),
        300,
    )
    return ContextPolicy(
        max_estimated_tokens=max_tokens,
        keep_recent_user_turns=keep_turns,
        max_summary_chars=max_summary,
        max_item_chars=max_item,
    )
