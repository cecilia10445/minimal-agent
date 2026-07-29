import json
import time

import pytest

from src.agent import (
    AgentResult,
    AgentRuntime,
    InvalidLLMResponseError,
    MaxStepsExceededError,
)
from src.llm import LLMResponse, ScriptedLLMClient, ToolCall
from src.prompt import SYSTEM_PROMPT
from src.registry import ToolRegistry
from src.session import SessionStore
from src.tools.calculator import CalculatorTool
from src.tools.read_docs import ReadDocsTool
from src.tools.search import SearchTool
from src.tools.todo import TodoAddTool, TodoCompleteTool, TodoListTool


def _build_registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register(CalculatorTool())
    r.register(SearchTool())
    r.register(ReadDocsTool())
    r.register(TodoAddTool())
    r.register(TodoListTool())
    r.register(TodoCompleteTool())
    return r


def _make_runtime(
    responses: list[LLMResponse],
    store: SessionStore | None = None,
    registry: ToolRegistry | None = None,
    max_steps: int = 10,
):
    if store is None:
        store = SessionStore()
    client = ScriptedLLMClient(responses)
    if registry is None:
        registry = _build_registry()
    runtime = AgentRuntime(
        llm_client=client,
        tool_registry=registry,
        session_store=store,
        max_steps=max_steps,
    )
    return runtime, client, store


class TestDirectAnswer:
    def test_direct_answer(self, store):
        responses = [
            LLMResponse(content="Hello! How can I help you?", tool_calls=[]),
        ]
        runtime, client, _ = _make_runtime(responses, store=store)
        result = runtime.run("user1", "s1", "Hi")
        assert result.answer == "Hello! How can I help you?"
        assert result.steps_used == 1
        assert result.session_id == "s1"


class TestCalculatorTool:
    def test_calculator_then_answer(self, store):
        responses = [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="call_1", name="calculator", arguments={"expression": "12 * 8"}),
                ],
            ),
            LLMResponse(content="12 * 8 = 96", tool_calls=[]),
        ]
        runtime, client, _ = _make_runtime(responses, store=store)
        result = runtime.run("user1", "s1", "Calculate 12 * 8")
        assert result.answer == "12 * 8 = 96"
        assert result.steps_used == 2


class TestMultiStepTools:
    def test_search_then_todo_then_answer(self, store):
        responses = [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="call_1", name="search", arguments={"keywords": "python"}),
                ],
            ),
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="call_2", name="todo_add", arguments={"content": "Learn Python"}),
                ],
            ),
            LLMResponse(content="Done! Added todo and searched.", tool_calls=[]),
        ]
        runtime, client, store = _make_runtime(responses, store=store)
        result = runtime.run("user1", "s1", "Search python and add todo")
        assert result.answer == "Done! Added todo and searched."
        assert result.steps_used == 3

        session = store.get("user1", "s1")
        assert session is not None
        assert len(session.todos) == 1
        assert session.todos[0]["content"] == "Learn Python"


class TestParallelToolCalls:
    def test_parallel_tool_calls(self, store):
        responses = [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="call_1", name="calculator", arguments={"expression": "1+1"}),
                    ToolCall(id="call_2", name="calculator", arguments={"expression": "2+2"}),
                ],
            ),
            LLMResponse(content="Results: 2 and 4", tool_calls=[]),
        ]
        runtime, client, _ = _make_runtime(responses, store=store)
        result = runtime.run("user1", "s1", "Calculate 1+1 and 2+2")
        assert result.answer == "Results: 2 and 4"
        assert result.steps_used == 2

        # Verify both tool results are in session messages
        from src.session import SessionStore
        session = store.get("user1", "s1")
        tool_msgs = [m for m in session.messages if m["role"] == "tool"]
        assert len(tool_msgs) == 2
        assert tool_msgs[0]["tool_call_id"] == "call_1"
        assert tool_msgs[1]["tool_call_id"] == "call_2"


class TestToolMessageFormat:
    def test_tool_call_id_and_name_preserved(self, store):
        responses = [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="call_calc", name="calculator", arguments={"expression": "3*3"}),
                ],
            ),
            LLMResponse(content="Result is 9", tool_calls=[]),
        ]
        runtime, client, _ = _make_runtime(responses, store=store)
        runtime.run("user1", "s1", "3*3?")
        session = store.get("user1", "s1")

        # find assistant message with tool_calls
        assistant_msgs = [m for m in session.messages if m["role"] == "assistant" and "tool_calls" in m]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0]["tool_calls"][0]["id"] == "call_calc"
        assert assistant_msgs[0]["tool_calls"][0]["function"]["name"] == "calculator"
        args = json.loads(assistant_msgs[0]["tool_calls"][0]["function"]["arguments"])
        assert args == {"expression": "3*3"}

        tool_msgs = [m for m in session.messages if m["role"] == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "call_calc"
        assert tool_msgs[0]["name"] == "calculator"


class TestSameSessionHistory:
    def test_second_run_sees_history(self, store):
        responses = [
            LLMResponse(content="First answer", tool_calls=[]),
        ]
        registry = _build_registry()
        runtime, client, _ = _make_runtime(responses, store=store, registry=registry)
        runtime.run("user1", "s1", "First message")

        # Second run with new responses
        responses2 = [
            LLMResponse(content="Second answer", tool_calls=[]),
        ]
        client2 = ScriptedLLMClient(responses2)
        runtime2 = AgentRuntime(
            llm_client=client2,
            tool_registry=registry,
            session_store=store,
            max_steps=10,
        )
        runtime2.run("user1", "s1", "Second message")

        # Check that LLM received both user messages
        assert len(client2.call_history) == 1
        sent_msgs = client2.call_history[0]["messages"]
        # system + user1 + assistant(First answer) + user2
        assert len(sent_msgs) == 4
        roles = [m["role"] for m in sent_msgs]
        assert roles == ["system", "user", "assistant", "user"]

    def test_second_run_sees_todos(self, store):
        # First run: add todo
        responses = [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="c1", name="todo_add", arguments={"content": "Buy milk"}),
                ],
            ),
            LLMResponse(content="Added", tool_calls=[]),
        ]
        registry = _build_registry()
        runtime, client, store = _make_runtime(responses, store=store, registry=registry)
        runtime.run("user1", "s1", "Add buy milk")

        # Second run: list todos
        responses2 = [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="c2", name="todo_list", arguments={}),
                ],
            ),
            LLMResponse(content="Here are your todos", tool_calls=[]),
        ]
        client2 = ScriptedLLMClient(responses2)
        runtime2 = AgentRuntime(
            llm_client=client2,
            tool_registry=registry,
            session_store=store,
            max_steps=10,
        )
        result = runtime2.run("user1", "s1", "List my todos")
        # todo_list should return non-empty result
        tool_msg = [m for m in store.get("user1", "s1").messages if m["role"] == "tool"]
        assert any("Buy milk" in m["content"] for m in tool_msg)


class TestSessionIsolation:
    def test_same_user_diff_session_isolation(self, store):
        responses_a = [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="c1", name="todo_add", arguments={"content": "Session A todo"}),
                ],
            ),
            LLMResponse(content="Done A", tool_calls=[]),
        ]
        runtime_a, _, _ = _make_runtime(responses_a, store=store)
        runtime_a.run("alice", "sess_a", "Add todo")

        responses_b = [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="c2", name="todo_list", arguments={}),
                ],
            ),
            LLMResponse(content="Done B", tool_calls=[]),
        ]
        runtime_b, client_b, _ = _make_runtime(responses_b, store=store)
        runtime_b.run("alice", "sess_b", "List todos")

        sess_a = store.get("alice", "sess_a")
        sess_b = store.get("alice", "sess_b")
        assert len(sess_a.todos) == 1
        assert len(sess_b.todos) == 0

        # Check traces are isolated too
        assert len(sess_a.traces) > 0
        assert len(sess_b.traces) > 0

    def test_diff_user_diff_session_isolation(self, store):
        responses_bob = [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="c1", name="todo_add", arguments={"content": "Bob todo"}),
                ],
            ),
            LLMResponse(content="Bob done", tool_calls=[]),
        ]
        runtime_bob, _, _ = _make_runtime(responses_bob, store=store)
        runtime_bob.run("bob", "s1", "Add bob todo")

        responses_carol = [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="c2", name="todo_list", arguments={}),
                ],
            ),
            LLMResponse(content="Carol done", tool_calls=[]),
        ]
        runtime_carol, _, _ = _make_runtime(responses_carol, store=store)
        runtime_carol.run("carol", "s1", "List carol todos")

        bob_s = store.get("bob", "s1")
        carol_s = store.get("carol", "s1")
        assert len(bob_s.todos) == 1
        assert len(carol_s.todos) == 0

        # Messages should also be isolated
        assert len(bob_s.messages) > 0
        assert len(carol_s.messages) > 0
        assert bob_s.messages != carol_s.messages


class TestToolErrorsHandled:
    def test_tool_not_found_continues(self, store):
        responses = [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="bad", name="nonexistent_tool", arguments={}),
                ],
            ),
            LLMResponse(content="Recovered from error", tool_calls=[]),
        ]
        runtime, _, _ = _make_runtime(responses, store=store)
        result = runtime.run("user1", "s1", "Call bad tool")
        assert result.answer == "Recovered from error"
        assert result.steps_used == 2

        # Check the error observation was stored
        session = store.get("user1", "s1")
        tool_msgs = [m for m in session.messages if m["role"] == "tool"]
        assert len(tool_msgs) == 1
        content = json.loads(tool_msgs[0]["content"])
        assert content["ok"] is False
        assert content["error_type"] == "ToolNotFoundError"

    def test_tool_parameter_error_continues(self, store):
        responses = [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="bad", name="calculator", arguments={}),
                ],
            ),
            LLMResponse(content="Fixed the params", tool_calls=[]),
        ]
        runtime, _, _ = _make_runtime(responses, store=store)
        result = runtime.run("user1", "s1", "Call calculator with no params")
        assert result.answer == "Fixed the params"

        session = store.get("user1", "s1")
        tool_msgs = [m for m in session.messages if m["role"] == "tool"]
        assert len(tool_msgs) == 1
        content = json.loads(tool_msgs[0]["content"])
        assert content["ok"] is False
        assert content["error_type"] == "ToolParameterError"

    def test_tool_execution_error_continues(self, store, registry):
        responses = [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="bad", name="calculator", arguments={"expression": "__import__('os')"}),
                ],
            ),
            LLMResponse(content="Handled invalid expr", tool_calls=[]),
        ]
        runtime, _, _ = _make_runtime(responses, store=store, registry=registry)
        result = runtime.run("user1", "s1", "Bad expression")
        assert result.answer == "Handled invalid expr"

        session = store.get("user1", "s1")
        tool_msgs = [m for m in session.messages if m["role"] == "tool"]
        assert len(tool_msgs) == 1
        content = json.loads(tool_msgs[0]["content"])
        assert content["ok"] is False
        assert content["error_type"] == "ToolExecutionError"


class TestInvalidLLMResponse:
    def test_empty_content_no_tools_raises(self, store):
        responses = [
            LLMResponse(content=None, tool_calls=[]),
        ]
        runtime, _, _ = _make_runtime(responses, store=store)
        with pytest.raises(InvalidLLMResponseError):
            runtime.run("user1", "s1", "Hello")

    def test_empty_string_no_tools_raises(self, store):
        responses = [
            LLMResponse(content="", tool_calls=[]),
        ]
        runtime, _, _ = _make_runtime(responses, store=store)
        with pytest.raises(InvalidLLMResponseError):
            runtime.run("user1", "s1", "Hello")


class TestMaxStepsExceeded:
    def test_max_steps_exceeded(self, store):
        # Always request a tool call, never finish
        responses = [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id=f"c{i}", name="calculator", arguments={"expression": "1+1"}),
                ],
            )
            for i in range(20)
        ]
        runtime, _, _ = _make_runtime(responses, store=store, max_steps=3)
        with pytest.raises(MaxStepsExceededError) as exc:
            runtime.run("user1", "s1", "Loop forever")
        assert "3" in str(exc.value)

        # Verify traces contain all steps + the final max_steps_exceeded
        session = store.get("user1", "s1")
        assert len(session.traces) == 4  # 3 tool_call + 1 max_steps_exceeded
        assert session.traces[-1]["event_type"] == "max_steps_exceeded"


class TestScriptedClientExhausted:
    def test_exhausted_raises(self, store):
        # Only 1 response, but agent will need 2 (tool + answer)
        responses = [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="c1", name="calculator", arguments={"expression": "1+1"}),
                ],
            ),
        ]
        runtime, client, _ = _make_runtime(responses, store=store)
        with pytest.raises(RuntimeError, match="exhausted"):
            runtime.run("user1", "s1", "Calc")


class TestTraceContent:
    def test_trace_fields(self, store):
        responses = [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="t1", name="calculator", arguments={"expression": "2+3"}),
                ],
                decision_summary="need to calculate",
            ),
            LLMResponse(content="Result is 5", tool_calls=[], decision_summary="got answer"),
        ]
        runtime, _, _ = _make_runtime(responses, store=store)
        result = runtime.run("user1", "s1", "2+3?")

        assert len(result.traces) == 2

        # First trace = tool_call
        t1 = result.traces[0]
        assert t1["step_number"] == 1
        assert t1["event_type"] == "tool_call"
        assert t1["tool_call_id"] == "t1"
        assert t1["tool_name"] == "calculator"
        assert t1["arguments"] == {"expression": "2+3"}
        assert t1["success"] is True
        assert t1["error_type"] is None
        assert t1["duration_ms"] is not None
        assert t1["duration_ms"] >= 0
        assert t1["decision_summary"] == "need to calculate"
        obs = json.loads(t1["observation"])
        assert obs["ok"] is True
        assert obs["result"] == "5.0"

        # Second trace = final_answer
        t2 = result.traces[1]
        assert t2["step_number"] == 2
        assert t2["event_type"] == "final_answer"
        assert t2["observation"] == "Result is 5"
        assert t2["success"] is True

    def test_error_trace_has_error_type(self, store):
        responses = [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="bad", name="nonexistent", arguments={}),
                ],
            ),
            LLMResponse(content="ok", tool_calls=[]),
        ]
        runtime, _, _ = _make_runtime(responses, store=store)
        result = runtime.run("user1", "s1", "bad tool")

        # First trace should have error info
        t1 = result.traces[0]
        assert t1["event_type"] == "tool_call"
        assert t1["success"] is False
        assert t1["error_type"] == "ToolNotFoundError"

    def test_max_steps_trace(self, store):
        responses = [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="c1", name="calculator", arguments={"expression": "1"}),
                ],
            ),
        ]
        runtime, _, _ = _make_runtime(responses, store=store, max_steps=1)
        with pytest.raises(MaxStepsExceededError):
            runtime.run("user1", "s1", "test")

        session = store.get("user1", "s1")
        assert len(session.traces) == 2
        assert session.traces[-1]["event_type"] == "max_steps_exceeded"
        assert session.traces[-1]["success"] is False


class TestRunTraceIsolation:
    def test_second_run_traces_do_not_include_first_run(self, store):
        responses_a = [
            LLMResponse(content="First answer", tool_calls=[]),
        ]
        runtime, _, _ = _make_runtime(responses_a, store=store)
        result_a = runtime.run("user1", "s1", "First message")
        assert len(result_a.traces) == 1
        assert result_a.traces[0]["event_type"] == "final_answer"
        assert result_a.traces[0]["step_number"] == 1

        responses_b = [
            LLMResponse(content="Second answer", tool_calls=[]),
        ]
        runtime_b, client_b, _ = _make_runtime(responses_b, store=store)
        result_b = runtime_b.run("user1", "s1", "Second message")
        assert len(result_b.traces) == 1
        assert result_b.traces[0]["event_type"] == "final_answer"
        assert result_b.traces[0]["step_number"] == 1

        session = store.get("user1", "s1")
        assert len(session.traces) == 2


class TestLLMReceivesCorrectContext:
    def test_llm_receives_messages_and_tools_schema(self, store, registry):
        responses = [
            LLMResponse(content="Direct answer", tool_calls=[]),
        ]
        runtime, client, _ = _make_runtime(responses, store=store)
        runtime.run("user1", "s1", "Hello")

        assert len(client.call_history) == 1
        call = client.call_history[0]
        msgs = call["messages"]
        assert len(msgs) == 2  # system + user
        assert msgs[0]["role"] == "system"
        assert "personal work assistant" in msgs[0]["content"]
        assert msgs[1]["role"] == "user"
        assert msgs[1]["content"] == "Hello"

        tools = call["tools"]
        tool_names = [t["function"]["name"] for t in tools]
        assert "calculator" in tool_names
        assert "search" in tool_names
        assert "read_docs" in tool_names
        assert "todo_add" in tool_names

    def test_llm_receives_tool_results_in_history(self, store):
        responses = [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(id="c1", name="calculator", arguments={"expression": "2*3"}),
                ],
            ),
            LLMResponse(content="6", tool_calls=[]),
        ]
        runtime, client, _ = _make_runtime(responses, store=store)
        runtime.run("user1", "s1", "2*3?")

        # Second LLM call should include the tool result
        assert len(client.call_history) == 2
        call2 = client.call_history[1]
        roles = [m["role"] for m in call2["messages"]]
        assert "tool" in roles

        tool_msgs = [m for m in call2["messages"] if m["role"] == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "c1"


class TestInputValidation:
    def test_empty_user_id_raises(self, store):
        responses = [LLMResponse(content="x", tool_calls=[])]
        runtime, _, _ = _make_runtime(responses, store=store)
        with pytest.raises(ValueError, match="user_id"):
            runtime.run("", "s1", "hello")

    def test_empty_session_id_raises(self, store):
        responses = [LLMResponse(content="x", tool_calls=[])]
        runtime, _, _ = _make_runtime(responses, store=store)
        with pytest.raises(ValueError, match="session_id"):
            runtime.run("u1", "", "hello")

    def test_empty_input_raises(self, store):
        responses = [LLMResponse(content="x", tool_calls=[])]
        runtime, _, _ = _make_runtime(responses, store=store)
        with pytest.raises(ValueError, match="user_input"):
            runtime.run("u1", "s1", "")
