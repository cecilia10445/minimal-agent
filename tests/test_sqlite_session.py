import json
import os

import pytest

from src.agent import AgentRuntime
from src.context_manager import ContextManager, ContextPolicy
from src.llm import LLMResponse, ScriptedLLMClient, ToolCall
from src.registry import ToolRegistry
from src.session import Session
from src.sqlite_session import SQLiteSessionStore, SessionPersistenceError
from src.tools.calculator import CalculatorTool
from src.tools.list_docs import ListDocsTool
from src.tools.search import SearchTool
from src.tools.read_docs import ReadDocsTool
from src.tools.search_docs import SearchDocsTool
from src.tools.todo import TodoAddTool, TodoCompleteTool, TodoListTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register(CalculatorTool())
    r.register(SearchTool())
    r.register(ListDocsTool())
    r.register(SearchDocsTool())
    r.register(ReadDocsTool())
    r.register(TodoAddTool())
    r.register(TodoListTool())
    r.register(TodoCompleteTool())
    return r


def _make_runtime(responses, store, context_manager=None):
    client = ScriptedLLMClient(responses)
    registry = _build_registry()
    runtime = AgentRuntime(
        llm_client=client,
        tool_registry=registry,
        session_store=store,
        max_steps=10,
        context_manager=context_manager,
    )
    return runtime, client, store


def _store(tmp_path) -> SQLiteSessionStore:
    db = os.path.join(tmp_path, "test.db")
    return SQLiteSessionStore(db_path=db)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBasicPersistence:
    def test_new_session_save_and_read(self, tmp_path):
        store = _store(tmp_path)
        session = store.get_or_create("user1", "sess1")
        session.messages.append({"role": "user", "content": "hello"})
        session.summary = "test summary"
        session.todos.append({"id": 1, "content": "task1", "done": False})
        store.save(session)

        # Re-read
        store2 = _store(tmp_path)
        loaded = store2.get("user1", "sess1")
        assert loaded is not None
        assert loaded.messages == [{"role": "user", "content": "hello"}]
        assert loaded.summary == "test summary"
        assert loaded.todos == [{"id": 1, "content": "task1", "done": False}]

    def test_restart_simulation(self, tmp_path):
        db = os.path.join(tmp_path, "restart.db")
        store1 = SQLiteSessionStore(db_path=db)
        s1 = store1.get_or_create("alice", "s1")
        s1.messages.append({"role": "user", "content": "Hello Alice"})
        store1.save(s1)

        store2 = SQLiteSessionStore(db_path=db)
        s2 = store2.get("alice", "s1")
        assert s2 is not None
        assert len(s2.messages) == 1
        assert s2.messages[0]["content"] == "Hello Alice"

    def test_messages_persisted(self, tmp_path):
        store = _store(tmp_path)
        s = store.get_or_create("u", "s")
        s.messages = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
        ]
        store.save(s)

        store2 = _store(tmp_path)
        loaded = store2.get("u", "s")
        assert loaded is not None
        assert loaded.messages == s.messages

    def test_summary_persisted(self, tmp_path):
        store = _store(tmp_path)
        s = store.get_or_create("u", "s")
        s.summary = "This is a session summary about weather."
        store.save(s)

        store2 = _store(tmp_path)
        loaded = store2.get("u", "s")
        assert loaded.summary == "This is a session summary about weather."

    def test_todos_persisted(self, tmp_path):
        store = _store(tmp_path)
        s = store.get_or_create("u", "s")
        s.todos = [
            {"id": 1, "content": "Buy milk", "done": False},
            {"id": 2, "content": "Write code", "done": True},
        ]
        store.save(s)

        store2 = _store(tmp_path)
        loaded = store2.get("u", "s")
        assert loaded.todos == s.todos

    def test_traces_and_run_id_persisted(self, tmp_path):
        store = _store(tmp_path)
        s = store.get_or_create("u", "s")
        s.traces = [
            {"step_number": 1, "event_type": "tool_call", "run_id": 1, "tool_name": "calc"},
            {"step_number": 2, "event_type": "final_answer", "run_id": 1},
        ]
        store.save(s)

        store2 = _store(tmp_path)
        loaded = store2.get("u", "s")
        assert loaded.traces == s.traces

    def test_same_user_diff_session_isolation(self, tmp_path):
        store = _store(tmp_path)
        s_a = store.get_or_create("alice", "sess_a")
        s_a.todos.append({"id": 1, "content": "Alice todo", "done": False})
        store.save(s_a)
        s_b = store.get_or_create("alice", "sess_b")
        s_b.todos.append({"id": 1, "content": "Bob todo", "done": False})
        store.save(s_b)

        store2 = _store(tmp_path)
        loaded_a = store2.get("alice", "sess_a")
        loaded_b = store2.get("alice", "sess_b")
        assert len(loaded_a.todos) == 1
        assert loaded_a.todos[0]["content"] == "Alice todo"
        assert len(loaded_b.todos) == 1
        assert loaded_b.todos[0]["content"] == "Bob todo"

    def test_diff_user_same_session_id_isolation(self, tmp_path):
        store = _store(tmp_path)
        s_a = store.get_or_create("user_a", "common")
        s_a.todos.append({"id": 1, "content": "User A data", "done": False})
        store.save(s_a)
        s_b = store.get_or_create("user_b", "common")
        s_b.todos.append({"id": 1, "content": "User B data", "done": False})
        store.save(s_b)

        store2 = _store(tmp_path)
        loaded_a = store2.get("user_a", "common")
        loaded_b = store2.get("user_b", "common")
        assert loaded_a.todos[0]["content"] == "User A data"
        assert loaded_b.todos[0]["content"] == "User B data"

    def test_list_user_sessions_only_current_user(self, tmp_path):
        store = _store(tmp_path)
        store.get_or_create("alice", "s1")
        store.get_or_create("alice", "s2")
        store.get_or_create("bob", "s1")
        store.save(store.get_or_create("alice", "s1"))
        store.save(store.get_or_create("alice", "s2"))
        store.save(store.get_or_create("bob", "s1"))

        store2 = _store(tmp_path)
        alice_sessions = store2.list_user_sessions("alice")
        bob_sessions = store2.list_user_sessions("bob")
        assert len(alice_sessions) == 2
        assert len(bob_sessions) == 1
        assert {s.session_id for s in alice_sessions} == {"s1", "s2"}
        assert bob_sessions[0].session_id == "s1"

    def test_chinese_content(self, tmp_path):
        store = _store(tmp_path)
        s = store.get_or_create("zh", "cn")
        s.messages.append({"role": "user", "content": "你好，世界！"})
        s.summary = "用户说了你好世界"
        store.save(s)

        store2 = _store(tmp_path)
        loaded = store2.get("zh", "cn")
        assert loaded.messages[0]["content"] == "你好，世界！"
        assert loaded.summary == "用户说了你好世界"

    def test_auto_create_parent_directory(self, tmp_path):
        nested = os.path.join(tmp_path, "nested", "dir", "test.db")
        store = SQLiteSessionStore(db_path=nested)
        s = store.get_or_create("u", "s")
        s.messages.append({"role": "user", "content": "hello"})
        store.save(s)

        store2 = SQLiteSessionStore(db_path=nested)
        loaded = store2.get("u", "s")
        assert loaded is not None

    def test_corrupted_json_raises_error(self, tmp_path):
        store = _store(tmp_path)
        s = store.get_or_create("u", "s")
        store.save(s)
        # Corrupt the state_json directly in the database
        store._conn.execute(
            "UPDATE sessions SET state_json = '{broken json' WHERE user_id = 'u' AND session_id = 's'"
        )
        store._conn.commit()
        # Create a fresh store instance so cache is empty
        store2 = SQLiteSessionStore(db_path=store._db_path)
        with pytest.raises(SessionPersistenceError):
            store2.get("u", "s")

    def test_upsert_no_duplicate_rows(self, tmp_path):
        store = _store(tmp_path)
        s = store.get_or_create("u", "s")
        s.messages.append({"role": "user", "content": "first"})
        store.save(s)
        s.messages.append({"role": "user", "content": "second"})
        store.save(s)

        rows = store._conn.execute(
            "SELECT COUNT(*) as cnt FROM sessions WHERE user_id = 'u' AND session_id = 's'"
        ).fetchone()
        assert rows["cnt"] == 1

    def test_clear(self, tmp_path):
        store = _store(tmp_path)
        store.get_or_create("u", "s1")
        store.get_or_create("u", "s2")
        store.clear()
        assert store.get("u", "s1") is None
        assert store.get("u", "s2") is None

    def test_two_store_instances_same_db(self, tmp_path):
        db = os.path.join(tmp_path, "shared.db")
        store_a = SQLiteSessionStore(db_path=db)
        s = store_a.get_or_create("u", "s")
        s.messages.append({"role": "user", "content": "from a"})
        store_a.save(s)

        store_b = SQLiteSessionStore(db_path=db)
        loaded = store_b.get("u", "s")
        assert loaded is not None
        assert loaded.messages[0]["content"] == "from a"

    def test_get_unknown_returns_none(self, tmp_path):
        store = _store(tmp_path)
        assert store.get("nonexistent", "nope") is None


class TestAgentRuntimeIntegration:
    def test_runtime_persists_then_new_runtime_recovers(self, tmp_path):
        store = _store(tmp_path)
        responses = [
            LLMResponse(content=None, tool_calls=[
                ToolCall(id="c1", name="todo_add", arguments={"content": "Buy milk"}),
            ]),
            LLMResponse(content="Todo added", tool_calls=[]),
        ]
        runtime, _, _ = _make_runtime(responses, store=store)
        runtime.run("alice", "s1", "Add milk")

        store2 = _store(tmp_path)
        loaded = store2.get("alice", "s1")
        assert loaded is not None
        assert len(loaded.todos) == 1
        assert loaded.todos[0]["content"] == "Buy milk"
        assert len(loaded.messages) > 0

    def test_new_runtime_continues_conversation(self, tmp_path):
        store = _store(tmp_path)
        responses1 = [
            LLMResponse(content="First answer", tool_calls=[]),
        ]
        runtime1, _, _ = _make_runtime(responses1, store=store)
        runtime1.run("alice", "s1", "First message")

        store2 = _store(tmp_path)
        responses2 = [
            LLMResponse(content="Second answer", tool_calls=[]),
        ]
        runtime2, client2, _ = _make_runtime(responses2, store=store2)
        runtime2.run("alice", "s1", "Second message")

        # Should have both messages in history
        loaded = store2.get("alice", "s1")
        assert loaded is not None
        assert len(loaded.messages) >= 2

    def test_different_session_not_visible(self, tmp_path):
        store = _store(tmp_path)
        responses = [LLMResponse(content="Answer", tool_calls=[])]
        runtime, _, _ = _make_runtime(responses, store=store)
        runtime.run("alice", "s1", "Hello")

        store2 = _store(tmp_path)
        assert store2.get("alice", "s2") is None

    def test_different_user_not_visible(self, tmp_path):
        store = _store(tmp_path)
        responses = [LLMResponse(content="Answer", tool_calls=[])]
        runtime, _, _ = _make_runtime(responses, store=store)
        runtime.run("alice", "s1", "Hello")

        store2 = _store(tmp_path)
        loaded = store2.get("bob", "s1")
        assert loaded is None

    def test_context_summary_survives_store_recreation(self, tmp_path):
        policy = ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=1)
        cm = ContextManager(policy)
        store = _store(tmp_path)
        responses = [
            LLMResponse(content="First answer", tool_calls=[]),
            LLMResponse(content="Second answer", tool_calls=[]),
            LLMResponse(content="Third answer", tool_calls=[]),
        ]
        runtime, _, _ = _make_runtime(responses, store=store, context_manager=cm)
        runtime.run("alice", "s1", "First")
        runtime.run("alice", "s1", "Second")
        runtime.run("alice", "s1", "Third")

        store2 = _store(tmp_path)
        loaded = store2.get("alice", "s1")
        assert loaded is not None
        assert len(loaded.summary) > 0

    def test_normal_pytest_no_real_api(self, tmp_path):
        store = _store(tmp_path)
        responses = [LLMResponse(content="ok", tool_calls=[])]
        runtime, client, _ = _make_runtime(responses, store=store)
        runtime.run("u", "s", "test")
        assert client.current_index == 1
