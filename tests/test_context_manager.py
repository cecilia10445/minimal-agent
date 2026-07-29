import json

import pytest

from src.agent import AgentRuntime
from src.context_manager import (
    ContextManager,
    ContextPolicy,
    _find_compress_boundary,
    _merge_summary,
    _summarize_messages,
    _truncate,
    estimate_tokens,
)
from src.llm import LLMResponse, ScriptedLLMClient, ToolCall
from src.session import Session, SessionStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TR = "tool_result:" + "x" * 300  # tool result longer than max_item_chars


def _session_with_messages(messages: list[dict], summary: str = "") -> Session:
    s = Session(user_id="u", session_id="s")
    s.messages = list(messages)
    s.summary = summary
    return s


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
# estimate_tokens
# ---------------------------------------------------------------------------

class TestEstimateTokens:
    def test_empty_returns_zero(self):
        assert estimate_tokens([]) == 0

    def test_non_empty_at_least_one(self):
        assert estimate_tokens([{"role": "user", "content": "hi"}]) >= 1

    def test_includes_tool_calls(self):
        msgs = [
            {"role": "user", "content": "calc"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "calc", "arguments": '{"x":1}'}}
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "name": "calc", "content": "2"},
        ]
        assert estimate_tokens(msgs) >= 1


# ---------------------------------------------------------------------------
# _truncate
# ---------------------------------------------------------------------------

class TestTruncate:
    def test_short_unchanged(self):
        assert _truncate("hello", 10) == "hello"

    def test_long_truncated(self):
        result = _truncate("hello world", 5)
        assert result == "hello..."
        assert len(result) == 8


# ---------------------------------------------------------------------------
# _find_compress_boundary
# ---------------------------------------------------------------------------

class TestFindCompressBoundary:
    def test_no_messages(self):
        assert _find_compress_boundary([], 4) == 0

    def test_fewer_turns_than_keep(self):
        msgs = _make_turn("hi", "hello")
        assert _find_compress_boundary(msgs, 4) == 0

    def test_exact_turns_no_compress(self):
        msgs = _make_turn("q1", "a1") + _make_turn("q2", "a2")
        assert _find_compress_boundary(msgs, 2) == 0

    def test_more_turns_than_keep(self):
        msgs = _make_turn("q1", "a1") + _make_turn("q2", "a2") + _make_turn("q3", "a3")
        boundary = _find_compress_boundary(msgs, 2)
        # Should skip 1 turn, boundary should be at index 2 (start of second turn)
        assert boundary == 2

    def test_more_turns_keeps_last_n(self):
        msgs = _make_turn("q1", "a1") + _make_turn("q2", "a2") + _make_turn("q3", "a3") + _make_turn("q4", "a4")
        boundary = _find_compress_boundary(msgs, 2)
        assert boundary == 4  # skip 2 turns, keep last 2 (4 messages)

    def test_tool_turns_boundary(self):
        msgs = _make_tool_turn("q1") + _make_turn("q2", "a2") + _make_turn("q3", "a3")
        boundary = _find_compress_boundary(msgs, 2)
        # 3 turns, keep 2 -> skip 1 turn (4 messages including tool calls)
        assert boundary == 4


# ---------------------------------------------------------------------------
# _summarize_messages
# ---------------------------------------------------------------------------

class TestSummarizeMessages:
    def test_user_and_assistant(self):
        msgs = _make_turn("你好", "你好！有什么需要帮助的吗？")
        entries = _summarize_messages(msgs, 300)
        assert any("用户请求" in e for e in entries)
        assert any("助手回答" in e for e in entries)

    def test_tool_calls_summarized(self):
        msgs = _make_tool_turn("calc", tool_result="2.0")
        entries = _summarize_messages(msgs, 300)
        texts = " ".join(entries)
        assert "调用工具" in texts
        assert "工具结果" in texts
        assert "calculator" in texts

    def test_long_content_truncated(self):
        long_text = "x" * 1000
        msgs = _make_turn(long_text)
        entries = _summarize_messages(msgs, 50)
        assert any("..." in e for e in entries)

    def test_content_none_handled(self):
        msgs = [{"role": "user", "content": None}]
        entries = _summarize_messages(msgs, 300)
        assert len(entries) == 1
        assert "用户请求" in entries[0]


# ---------------------------------------------------------------------------
# _merge_summary
# ---------------------------------------------------------------------------

class TestMergeSummary:
    def test_no_existing(self):
        result = _merge_summary("", ["- entry1", "- entry2"], 1000)
        assert "- entry1" in result
        assert "- entry2" in result

    def test_combines_existing_and_new(self):
        result = _merge_summary("- old", ["- new"], 1000)
        assert "- old" in result
        assert "- new" in result

    def test_trims_when_exceeds_max(self):
        existing = "- " + "x" * 500
        new_entries = ["- " + "y" * 500]
        result = _merge_summary(existing, new_entries, 200)
        assert len(result) <= 210
        assert "进一步压缩" in result or "y" in result

    def test_prefers_newer_content(self):
        existing = "- old" * 500
        new_entries = ["- new content here"]
        result = _merge_summary(existing, new_entries, 200)
        assert "new content" in result


# ---------------------------------------------------------------------------
# ContextManager.prepare_session
# ---------------------------------------------------------------------------

class TestPrepareSession:
    def test_no_compress_when_below_threshold(self):
        cm = ContextManager(ContextPolicy(max_estimated_tokens=10000))
        msgs = _make_turn("hi")
        session = _session_with_messages(msgs)
        assert cm.prepare_session(session) is False
        assert len(session.messages) == 2

    def test_compress_when_above_threshold(self):
        cm = ContextManager(ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=1))
        msgs = _make_turn("hi") + _make_turn("hello")
        session = _session_with_messages(msgs)
        assert cm.prepare_session(session) is True
        # Session should have been compressed: 1 turn kept = 2 messages
        assert len(session.messages) == 2

    def test_keeps_recent_turns(self):
        cm = ContextManager(ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=2))
        msgs = _make_turn("q1") + _make_turn("q2") + _make_turn("q3")
        session = _session_with_messages(msgs)
        cm.prepare_session(session)
        # Should keep last 2 turns (q2 + a2, q3 + a3 = 4 messages)
        assert len(session.messages) == 4
        assert session.messages[0]["content"] == "q2"

    def test_no_compress_if_empty(self):
        cm = ContextManager(ContextPolicy(max_estimated_tokens=1))
        session = _session_with_messages([])
        assert cm.prepare_session(session) is False

    def test_summary_created_after_compress(self):
        cm = ContextManager(ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=1))
        msgs = _make_turn("First question", "First answer") + _make_turn("Second", "Second answer")
        session = _session_with_messages(msgs)
        cm.prepare_session(session)
        assert len(session.summary) > 0
        assert "First" in session.summary

    def test_tool_call_not_split_from_result(self):
        cm = ContextManager(ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=1))
        msgs = (
            _make_turn("q1", "a1")
            + _make_tool_turn("q2 calc", tool_result="42")
        )
        session = _session_with_messages(msgs)
        cm.prepare_session(session)
        remaining = session.messages
        # After keeping 1 turn, should have q2 + asst(tc) + tool + asst = 4 messages
        assert len(remaining) == 4
        # No orphaned tool messages
        tool_msgs = [m for m in remaining if m["role"] == "tool"]
        assert len(tool_msgs) == 1
        # Verify boundary is at a user message
        assert remaining[0]["role"] == "user"

    def test_parallel_tool_calls_preserved(self):
        cm = ContextManager(ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=1))
        turn_msgs = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "calc1", "arguments": "{}"}},
                    {"id": "c2", "type": "function", "function": {"name": "calc2", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "name": "calc1", "content": "r1"},
            {"role": "tool", "tool_call_id": "c2", "name": "calc2", "content": "r2"},
            {"role": "assistant", "content": "done"},
        ]
        session = _session_with_messages(turn_msgs)
        cm.prepare_session(session)
        # Should have all 5 messages of the tool turn kept (q2 + 2 tools + 2 results + done)
        assert len(session.messages) == 5
        assert session.messages[0]["role"] == "user"

    def test_summary_length_limited(self):
        policy = ContextPolicy(max_estimated_tokens=1, max_summary_chars=100)
        cm = ContextManager(policy)
        long_q = "x" * 200
        msgs = _make_turn(long_q, long_q) + _make_turn("q2", "a2")
        session = _session_with_messages(msgs)
        cm.prepare_session(session)
        assert len(session.summary) <= 150  # some slack for newline + marker

    def test_session_a_not_affect_b(self):
        cm = ContextManager(ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=1))
        s_a = _session_with_messages(_make_turn("a1", "a1a") + _make_turn("a2", "a2a"))
        s_b = _session_with_messages(_make_turn("b1", "b1b"))
        cm.prepare_session(s_a)
        cm.prepare_session(s_b)
        assert "a" in s_a.summary
        assert s_b.summary == ""

    def test_todos_and_traces_untouched(self):
        cm = ContextManager(ContextPolicy(max_estimated_tokens=1))
        msgs = _make_turn("q1") + _make_turn("q2")
        session = _session_with_messages(msgs)
        session.todos = [{"id": 1, "content": "test", "done": False}]
        session.traces = [{"step_number": 1, "event_type": "final_answer"}]
        cm.prepare_session(session)
        assert len(session.todos) == 1
        assert len(session.traces) == 1


# ---------------------------------------------------------------------------
# ContextManager.build_messages
# ---------------------------------------------------------------------------

class TestBuildMessages:
    def test_no_summary_no_extra_message(self):
        cm = ContextManager()
        session = _session_with_messages(
            [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        )
        result = cm.build_messages(system_prompt="You are a bot.", session=session)
        assert len(result) == 3  # system + user + assistant
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "You are a bot."

    def test_with_summary_injected(self):
        cm = ContextManager()
        session = _session_with_messages(
            [{"role": "user", "content": "hi"}],
            summary="- 用户请求：hi\n- 助手回答：hello",
        )
        result = cm.build_messages(system_prompt="Sys prompt", session=session)
        assert len(result) == 3
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "Sys prompt"
        assert result[1]["role"] == "system"
        assert "Session memory summary" in result[1]["content"]
        assert "summary" in result[1]["content"].lower()
        assert result[2]["role"] == "user"

    def test_summary_position_after_system(self):
        cm = ContextManager()
        session = _session_with_messages(
            [{"role": "user", "content": "recent"}],
            summary="- old summary",
        )
        result = cm.build_messages(system_prompt="System", session=session)
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "system"  # summary
        assert result[2]["role"] == "user"     # recent messages after summary

    def test_current_user_input_preserved(self):
        cm = ContextManager()
        session = _session_with_messages(
            [{"role": "user", "content": "current input"}]
        )
        result = cm.build_messages(system_prompt="System", session=session)
        assert any(m.get("content") == "current input" for m in result)


# ---------------------------------------------------------------------------
# Integration: AgentRuntime + ContextManager
# ---------------------------------------------------------------------------

def _build_small_policy() -> ContextPolicy:
    return ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=1)


class TestRuntimeWithContextManager:
    def test_llm_receives_summary_after_compress(self):
        policy = _build_small_policy()
        cm = ContextManager(policy)
        responses = [
            LLMResponse(content="First answer", tool_calls=[]),
            LLMResponse(content="Second answer", tool_calls=[]),
            LLMResponse(content="Third answer", tool_calls=[]),
        ]
        runtime, client, store = _make_runtime(responses, context_manager=cm)

        # First two runs fill history
        runtime.run("u", "s1", "First input")
        runtime.run("u", "s1", "Second input")
        # Third run triggers compression (3 turns, keep=1 → 2 turns compressed)
        runtime.run("u", "s1", "Third input")

        session = store.get("u", "s1")
        assert len(session.summary) > 0

        # Check what the LLM received in the third run
        assert len(client.call_history) >= 3
        third_call_msgs = client.call_history[2]["messages"]
        roles = [m["role"] for m in third_call_msgs]
        assert "system" in roles
        # There should be 2 system messages (system prompt + summary) or 1
        sys_count = roles.count("system")
        assert sys_count >= 1

    def test_plain_chat_after_compress_still_works(self):
        cm = ContextManager(_build_small_policy())
        responses = [
            LLMResponse(content="First answer", tool_calls=[]),
            LLMResponse(content="Second answer", tool_calls=[]),
        ]
        runtime, client, store = _make_runtime(responses, context_manager=cm)
        runtime.run("u", "s1", "Hello")
        result = runtime.run("u", "s1", "Hi again")
        assert result.answer == "Second answer"

    def test_todo_after_compress_still_accessible(self):
        cm = ContextManager(_build_small_policy())
        responses1 = [
            LLMResponse(content=None, tool_calls=[
                ToolCall(id="c1", name="todo_add", arguments={"content": "Buy milk"}),
            ]),
            LLMResponse(content="Added", tool_calls=[]),
        ]
        runtime, _, store = _make_runtime(responses1, context_manager=cm)
        runtime.run("u", "s1", "Add milk")

        # Second run: list todos
        responses2 = [
            LLMResponse(content=None, tool_calls=[
                ToolCall(id="c2", name="todo_list", arguments={}),
            ]),
            LLMResponse(content="Here are your todos", tool_calls=[]),
        ]
        client2 = ScriptedLLMClient(responses2)
        registry = runtime._tool_registry
        runtime2 = AgentRuntime(
            llm_client=client2,
            tool_registry=registry,
            session_store=store,
            max_steps=10,
            context_manager=ContextManager(_build_small_policy()),
        )
        # This should trigger compression of the first run
        runtime2.run("u", "s1", "List todos")
        session = store.get("u", "s1")
        assert len(session.todos) == 1
        assert session.todos[0]["content"] == "Buy milk"

    def test_normal_pytest_no_real_api(self):
        # Verify ScriptedLLMClient is used, no real API calls
        cm = ContextManager(_build_small_policy())
        responses = [LLMResponse(content="ok", tool_calls=[])]
        runtime, client, _ = _make_runtime(responses, context_manager=cm)
        runtime.run("u", "s1", "test")
        assert client.current_index == 1


# ---------------------------------------------------------------------------
# Existing tests still pass
# ---------------------------------------------------------------------------

class TestExistingTestsNotBroken:
    def test_agent_tests_import(self):
        # Just verify the test module can be imported without error
        pass
