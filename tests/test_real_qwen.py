"""
Real LLM integration tests for qwen3.6-plus.
Skipped by default. Run with:
  $env:RUN_REAL_LLM_TESTS="1"; pytest -m real_llm -v
"""

import os

import pytest

from src.agent import AgentRuntime
from src.bootstrap import build_default_registry
from src.config import load_llm_settings
from src.prompt import SYSTEM_PROMPT
from src.qwen_client import OpenAICompatibleLLMClient
from src.session import SessionStore


def _should_skip() -> bool:
    if os.environ.get("RUN_REAL_LLM_TESTS", "") != "1":
        return True
    if not os.environ.get("DASHSCOPE_API_KEY", "").strip():
        return True
    return False


skip_reason = "Set RUN_REAL_LLM_TESTS=1 and configure DASHSCOPE_API_KEY to run."


@pytest.mark.real_llm
@pytest.mark.integration
def test_direct_answer():
    if _should_skip():
        pytest.skip(skip_reason)

    settings = load_llm_settings()
    client = OpenAICompatibleLLMClient(settings=settings)
    registry = build_default_registry()
    store = SessionStore()

    runtime = AgentRuntime(
        llm_client=client,
        tool_registry=registry,
        session_store=store,
        system_prompt=SYSTEM_PROMPT,
        max_steps=3,
    )

    result = runtime.run(
        user_id="test-user",
        session_id="real-test-1",
        user_input="请只用一句话介绍你能做什么，不要调用工具。",
    )

    assert result.answer, "Answer should not be empty"
    assert result.steps_used == 1
    assert len(result.traces) == 1
    assert result.traces[0]["event_type"] == "final_answer"


@pytest.mark.real_llm
@pytest.mark.integration
def test_calculator_tool_call():
    if _should_skip():
        pytest.skip(skip_reason)

    settings = load_llm_settings()
    client = OpenAICompatibleLLMClient(settings=settings)
    registry = build_default_registry()
    store = SessionStore()

    runtime = AgentRuntime(
        llm_client=client,
        tool_registry=registry,
        session_store=store,
        system_prompt=SYSTEM_PROMPT,
        max_steps=5,
    )

    result = runtime.run(
        user_id="test-user",
        session_id="real-test-2",
        user_input="请使用计算器计算 (37 + 15) * 4，并告诉我结果。",
    )

    assert result.answer, "Final answer should not be empty"

    calculator_traces = [
        t for t in result.traces
        if t["event_type"] == "tool_call" and t.get("tool_name") == "calculator"
    ]
    assert len(calculator_traces) >= 1, "Should have at least one calculator trace"

    # All calculator calls should succeed
    for t in calculator_traces:
        assert t.get("success") is True, f"Calculator call failed: {t}"

    # The answer or observation should contain 208
    all_text = result.answer + " " + " ".join(
        t.get("observation", "") for t in result.traces
    )
    assert "208" in all_text, f"Result 208 not found in answer or traces: {all_text}"
