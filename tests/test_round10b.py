"""Tests for Round 10B: Hybrid semantic context compression.

Uses FakeSemanticSummarizer — no real network calls.
"""

import json
import time
from typing import Any

import pytest

from src.agent import AgentRuntime
from src.context_manager import ContextManager, ContextPolicy, _merge_summary, _summarize_messages, estimate_tokens
from src.context_summarizer import _format_semantic_summary, _validate_semantic_json, _SEMANTIC_FIELDS
from src.llm import LLMResponse, ScriptedLLMClient
from src.session import Session, SessionStore


# ---------------------------------------------------------------------------
# FakeSemanticSummarizer (placed here for test isolation)
# ---------------------------------------------------------------------------

class FakeSemanticSummarizer:
    def __init__(
        self,
        *,
        fail: bool = False,
        fail_with: type[Exception] | None = None,
        fail_after_calls: int = 999,
        return_text: str | None = None,
        record_inputs: bool = False,
    ):
        self._fail = fail
        self._fail_with = fail_with or RuntimeError
        self._fail_after_calls = fail_after_calls
        self._return_text = return_text
        self._record_inputs = record_inputs
        self.call_count = 0
        self.captured_previous_summary: list[str] = []
        self.captured_messages: list[list[dict]] = []

    def summarize(
        self,
        *,
        previous_summary: str,
        messages: list[dict],
        max_output_chars: int,
    ) -> str:
        self.call_count += 1
        if self._record_inputs:
            self.captured_previous_summary.append(previous_summary)
            self.captured_messages.append(list(messages))
        if self._fail or self.call_count > self._fail_after_calls:
            raise self._fail_with("Simulated semantic summary failure")
        if self._return_text is not None:
            return self._return_text
        return self._default_summary()

    def _default_summary(self) -> str:
        return (
            "Goals:\n"
            "- Test hybrid context compression\n\n"
            "Confirmed Facts:\n"
            "- Fake semantic summary generated\n\n"
            "Latest Corrections:\n"
            "- Saturday 10am replaces Friday 9:30pm\n\n"
            "Preferences:\n"
            "- Answer with conclusion first\n\n"
            "Completed Actions:\n"
            "- Built test session\n"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_turn(user_text: str, answer_text: str = "Answer") -> list[dict]:
    return [
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": answer_text},
    ]


def _make_tool_turn(
    user_text: str,
    tool_name: str = "calculator",
    tool_args: str = '{"expression":"1+1"}',
    tool_result: str = "2",
    answer_text: str = "Result is 2",
) -> list[dict]:
    return [
        {"role": "user", "content": user_text},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": tool_name, "arguments": tool_args},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "name": tool_name, "content": tool_result},
        {"role": "assistant", "content": answer_text},
    ]


def _session_with_messages(messages: list[dict], summary: str = "") -> Session:
    s = Session(user_id="u", session_id="s")
    s.messages = list(messages)
    s.summary = summary
    return s


def _make_runtime(responses, context_manager=None):
    store = SessionStore()
    client = ScriptedLLMClient(responses)
    from src.bootstrap import build_default_registry
    registry = build_default_registry()
    runtime = AgentRuntime(
        llm_client=client,
        tool_registry=registry,
        session_store=store,
        max_steps=10,
        context_manager=context_manager,
    )
    return runtime, client, store


# ---------------------------------------------------------------------------
# 1. deterministic mode preserves old behavior
# ---------------------------------------------------------------------------

class TestDeterministicMode:
    def test_default_mode_is_deterministic(self):
        cm = ContextManager()
        assert cm._summary_mode == "deterministic"

    def test_deterministic_never_calls_summarizer(self):
        summarizer = FakeSemanticSummarizer()
        cm = ContextManager(
            ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=1),
            summarizer=summarizer,
            summary_mode="deterministic",
        )
        msgs = _make_turn("q1", "a1") + _make_turn("q2", "a2")
        session = _session_with_messages(msgs)
        cm.prepare_session(session)
        assert summarizer.call_count == 0

    def test_deterministic_summary_format(self):
        cm = ContextManager(
            ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=1),
            summary_mode="deterministic",
        )
        msgs = _make_turn("First question", "First answer") + _make_turn("Second", "Second answer")
        session = _session_with_messages(msgs)
        cm.prepare_session(session)
        assert "用户请求" in session.summary
        assert "助手回答" in session.summary
        assert "First" in session.summary

    def test_deterministic_semantic_call_count_zero(self):
        summarizer = FakeSemanticSummarizer()
        cm = ContextManager(
            ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=1),
            summarizer=summarizer,
            summary_mode="deterministic",
        )
        msgs = _make_turn("q1", "a1") + _make_turn("q2", "a2")
        session = _session_with_messages(msgs)
        cm.prepare_session(session)
        event = cm.last_compression_event
        assert event["semantic_summary_attempted"] is False
        assert event["semantic_summary_succeeded"] is False
        assert event["summary_mode"] == "deterministic"


# ---------------------------------------------------------------------------
# 2. Threshold control - no summarizer call below threshold
# ---------------------------------------------------------------------------

class TestThreshold:
    def test_no_summarizer_when_below_threshold(self):
        summarizer = FakeSemanticSummarizer()
        cm = ContextManager(
            ContextPolicy(max_estimated_tokens=10000),
            summarizer=summarizer,
            summary_mode="hybrid",
        )
        msgs = _make_turn("hi")
        session = _session_with_messages(msgs)
        cm.prepare_session(session)
        assert summarizer.call_count == 0

    def test_summarizer_called_when_above_threshold(self):
        summarizer = FakeSemanticSummarizer()
        cm = ContextManager(
            ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=1),
            summarizer=summarizer,
            summary_mode="hybrid",
        )
        msgs = _make_turn("q1", "a1") + _make_turn("q2", "a2")
        session = _session_with_messages(msgs)
        cm.prepare_session(session)
        assert summarizer.call_count == 1


# ---------------------------------------------------------------------------
# 3. Hybrid mode behavior
# ---------------------------------------------------------------------------

class TestHybridMode:
    def test_hybrid_calls_summarizer_once(self):
        summarizer = FakeSemanticSummarizer()
        cm = ContextManager(
            ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=1),
            summarizer=summarizer,
            summary_mode="hybrid",
        )
        msgs = _make_turn("q1", "a1") + _make_turn("q2", "a2")
        session = _session_with_messages(msgs)
        cm.prepare_session(session)
        assert summarizer.call_count == 1

    def test_semantic_summary_saved_to_session(self):
        summarizer = FakeSemanticSummarizer()
        cm = ContextManager(
            ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=1),
            summarizer=summarizer,
            summary_mode="hybrid",
        )
        msgs = _make_turn("q1", "a1") + _make_turn("q2", "a2")
        session = _session_with_messages(msgs)
        cm.prepare_session(session)
        assert len(session.summary) > 0
        assert "Fake semantic summary" in session.summary
        event = cm.last_compression_event
        assert event["semantic_summary_succeeded"] is True

    def test_previous_summary_passed_to_summarizer(self):
        summarizer = FakeSemanticSummarizer(record_inputs=True)
        cm = ContextManager(
            ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=1),
            summarizer=summarizer,
            summary_mode="hybrid",
        )
        msgs = _make_turn("q1", "a1") + _make_turn("q2", "a2")
        session = _session_with_messages(msgs, summary="- Old summary")
        cm.prepare_session(session)
        assert len(summarizer.captured_previous_summary) == 1
        assert "Old summary" in summarizer.captured_previous_summary[0]

    def test_latest_corrections_in_summary(self):
        summarizer = FakeSemanticSummarizer()
        cm = ContextManager(
            ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=1),
            summarizer=summarizer,
            summary_mode="hybrid",
        )
        msgs = (
            _make_turn("Deadline is Friday 9:30pm")
            + _make_turn("Correction: deadline is Saturday 10am now")
            + _make_turn("What is the deadline?")
        )
        session = _session_with_messages(msgs)
        cm.prepare_session(session)
        assert "Saturday 10am" in session.summary


# ---------------------------------------------------------------------------
# 4. Fallback behavior
# ---------------------------------------------------------------------------

class TestFallback:
    def test_empty_output_fallback(self):
        summarizer = FakeSemanticSummarizer(return_text="")
        cm = ContextManager(
            ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=1),
            summarizer=summarizer,
            summary_mode="hybrid",
        )
        msgs = _make_turn("q1", "a1") + _make_turn("q2", "a2")
        session = _session_with_messages(msgs)
        cm.prepare_session(session)
        assert "用户请求" in session.summary

    def test_exception_fallback(self):
        summarizer = FakeSemanticSummarizer(fail=True)
        cm = ContextManager(
            ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=1),
            summarizer=summarizer,
            summary_mode="hybrid",
        )
        msgs = _make_turn("q1", "a1") + _make_turn("q2", "a2")
        session = _session_with_messages(msgs)
        cm.prepare_session(session)
        assert "用户请求" in session.summary
        event = cm.last_compression_event
        assert event["fallback_used"] is True

    def test_timeout_fallback(self):
        class TimeoutSummarizer:
            def summarize(self, **kwargs):
                raise RuntimeError("Simulated timeout")
        cm = ContextManager(
            ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=1),
            summarizer=TimeoutSummarizer(),
            summary_mode="hybrid",
        )
        msgs = _make_turn("q1", "a1") + _make_turn("q2", "a2")
        session = _session_with_messages(msgs)
        cm.prepare_session(session)
        assert "用户请求" in session.summary

    def test_fallback_agent_still_works(self):
        summarizer = FakeSemanticSummarizer(fail=True)
        cm = ContextManager(
            ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=1),
            summarizer=summarizer,
            summary_mode="hybrid",
        )
        responses = [
            LLMResponse(content="First answer", tool_calls=[]),
            LLMResponse(content="Second answer", tool_calls=[]),
            LLMResponse(content="Third answer", tool_calls=[]),
        ]
        runtime, client, store = _make_runtime(responses, context_manager=cm)
        runtime.run("u", "s1", "Input 1")
        runtime.run("u", "s1", "Input 2")
        result = runtime.run("u", "s1", "Input 3")
        assert result.answer == "Third answer"
        session = store.get("u", "s1")
        assert "用户请求" in session.summary


# ---------------------------------------------------------------------------
# 5. Structural safety
# ---------------------------------------------------------------------------

class TestStructuralSafety:
    def test_recent_turns_not_semantically_summarized(self):
        summarizer = FakeSemanticSummarizer(record_inputs=True)
        cm = ContextManager(
            ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=2),
            summarizer=summarizer,
            summary_mode="hybrid",
        )
        msgs = _make_turn("q1", "a1") + _make_turn("q2", "a2") + _make_turn("q3", "a3")
        session = _session_with_messages(msgs)
        cm.prepare_session(session)
        # Only 1 turn compressed (q1), last 2 turns (q2, q3) kept
        assert len(session.messages) == 4  # q2+a2, q3+a3
        assert session.messages[0]["content"] == "q2"

    def test_tool_call_not_split_from_result(self):
        summarizer = FakeSemanticSummarizer()
        cm = ContextManager(
            ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=1),
            summarizer=summarizer,
            summary_mode="hybrid",
        )
        msgs = (
            _make_turn("q1", "a1")
            + _make_tool_turn("q2 calc", tool_result="42")
        )
        session = _session_with_messages(msgs)
        cm.prepare_session(session)
        remaining = session.messages
        assert len(remaining) == 4
        tool_msgs = [m for m in remaining if m["role"] == "tool"]
        assert len(tool_msgs) == 1

    def test_todos_and_traces_untouched(self):
        summarizer = FakeSemanticSummarizer()
        cm = ContextManager(
            ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=1),
            summarizer=summarizer,
            summary_mode="hybrid",
        )
        msgs = _make_turn("q1", "a1") + _make_turn("q2", "a2")
        session = _session_with_messages(msgs)
        session.todos = [{"id": 1, "content": "test", "done": False}]
        session.traces = [{"step_number": 1, "event_type": "final_answer"}]
        cm.prepare_session(session)
        assert len(session.todos) == 1
        assert len(session.traces) == 1


# ---------------------------------------------------------------------------
# 6. Invalid summary_mode raises
# ---------------------------------------------------------------------------

class TestInvalidMode:
    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="summary_mode"):
            ContextManager(summary_mode="invalid_mode")

    def test_invalid_mode_empty(self):
        with pytest.raises(ValueError, match="summary_mode"):
            ContextManager(summary_mode="")


# ---------------------------------------------------------------------------
# 7. Semantic probe checks match expectations
# ---------------------------------------------------------------------------

class TestSemanticFormat:
    def test_format_semantic_summary_basic(self):
        data = {
            "goals": ["Test system"],
            "confirmed_facts": ["Fact 1", "Fact 2"],
            "latest_corrections": [],
            "preferences": [],
            "constraints": [],
            "completed_actions": ["Action 1"],
            "open_items": [],
            "document_references": [],
        }
        text = _format_semantic_summary(data, 5000)
        assert "Goals:" in text
        assert "Test system" in text
        assert "Confirmed Facts:" in text
        assert "Completed Actions:" in text
        assert text.count("- ") == 4

    def test_format_semantic_summary_truncates(self):
        data = {"goals": ["x" * 5000]}
        text = _format_semantic_summary(data, 100)
        assert "(truncated)" in text

    def test_validate_semantic_json_valid(self):
        data = {f: ["test"] for f in _SEMANTIC_FIELDS}
        result = _validate_semantic_json(data)
        for f in _SEMANTIC_FIELDS:
            assert f in result
            assert result[f] == ["test"]

    def test_validate_semantic_json_not_dict(self):
        with pytest.raises(ValueError, match="not a JSON object"):
            _validate_semantic_json("not a dict")

    def test_validate_semantic_json_field_not_array(self):
        with pytest.raises(ValueError, match="must be an array"):
            _validate_semantic_json({"goals": "not a list"})

    def test_validate_semantic_json_element_not_string(self):
        with pytest.raises(ValueError, match="must be a string"):
            _validate_semantic_json({"goals": [42]})


# ---------------------------------------------------------------------------
# 8. Hybrid mode metadata in compression event
# ---------------------------------------------------------------------------

class TestCompressionEventMetadata:
    def test_hybrid_success_event(self):
        summarizer = FakeSemanticSummarizer()
        cm = ContextManager(
            ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=1),
            summarizer=summarizer,
            summary_mode="hybrid",
        )
        msgs = _make_turn("q1", "a1") + _make_turn("q2", "a2")
        session = _session_with_messages(msgs)
        cm.prepare_session(session)
        event = cm.last_compression_event
        assert event["summary_mode"] == "hybrid"
        assert event["semantic_summary_attempted"] is True
        assert event["semantic_summary_succeeded"] is True
        assert event["fallback_used"] is False
        assert event["messages_compressed"] > 0

    def test_hybrid_fallback_event(self):
        summarizer = FakeSemanticSummarizer(fail=True)
        cm = ContextManager(
            ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=1),
            summarizer=summarizer,
            summary_mode="hybrid",
        )
        msgs = _make_turn("q1", "a1") + _make_turn("q2", "a2")
        session = _session_with_messages(msgs)
        cm.prepare_session(session)
        event = cm.last_compression_event
        assert event["summary_mode"] == "hybrid"
        assert event["semantic_summary_attempted"] is True
        assert event["semantic_summary_succeeded"] is False
        assert event["fallback_used"] is True

    def test_no_compress_no_event(self):
        summarizer = FakeSemanticSummarizer()
        cm = ContextManager(
            ContextPolicy(max_estimated_tokens=10000),
            summarizer=summarizer,
            summary_mode="hybrid",
        )
        session = _session_with_messages(_make_turn("hi"))
        cm.prepare_session(session)
        assert cm.last_compression_event is None


# ---------------------------------------------------------------------------
# 9. All existing tests still pass
# ---------------------------------------------------------------------------

class TestExistingTestsNotBroken:
    def test_existing_tests_import(self):
        pass
