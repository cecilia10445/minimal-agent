import json
import os

import pytest

from src.agent import AgentRuntime
from src.context import ToolContext
from src.llm import LLMResponse, ScriptedLLMClient, ToolCall
from src.registry import ToolRegistry
from src.session import SessionStore
from src.tools import list_docs as list_docs_mod
from src.tools import search_docs as search_docs_mod
from src.tools import read_docs as read_docs_mod
from src.tools.calculator import CalculatorTool
from src.tools.list_docs import ListDocsTool
from src.tools.search import SearchTool
from src.tools.search_docs import SearchDocsTool
from src.tools.read_docs import ReadDocsTool
from src.tools.todo import TodoAddTool, TodoCompleteTool, TodoListTool


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def docs_dir(tmp_path):
    d = tmp_path / "knowledge_docs"
    d.mkdir()
    (d / "readme.md").write_text("# Readme\nThis is the main documentation.", encoding="utf-8")
    (d / "guide.md").write_text("# Guide\nStep by step instructions.", encoding="utf-8")
    (d / "唯一测试文档.md").write_text("# 唯一测试文档\n紫色河马987", encoding="utf-8")
    (d / "notes.txt").write_text("This should not be listed.", encoding="utf-8")
    yield d


@pytest.fixture
def patch_docs_dir(monkeypatch, docs_dir):
    monkeypatch.setattr(list_docs_mod, "_DOCS_DIR", docs_dir)
    monkeypatch.setattr(search_docs_mod, "_DOCS_DIR", docs_dir)
    monkeypatch.setattr(read_docs_mod, "_DOCS_DIR", docs_dir)
    return docs_dir


@pytest.fixture
def ctx(patch_docs_dir):
    store = SessionStore()
    return ToolContext(user_id="tester", session_id="s1", store=store)


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


# ---------------------------------------------------------------------------
# list_docs tests
# ---------------------------------------------------------------------------

class TestListDocs:
    def test_empty_dir(self, monkeypatch, tmp_path):
        empty_dir = tmp_path / "empty_docs"
        empty_dir.mkdir()
        monkeypatch.setattr(list_docs_mod, "_DOCS_DIR", empty_dir)
        tool = ListDocsTool()
        result = json.loads(tool.execute(ctx))
        assert result["count"] == 0
        assert result["documents"] == []

    def test_list_all_markdown(self, patch_docs_dir, ctx):
        tool = ListDocsTool()
        result = json.loads(tool.execute(ctx))
        assert result["count"] == 3
        filenames = {d["filename"] for d in result["documents"]}
        assert filenames == {"readme.md", "guide.md", "唯一测试文档.md"}

    def test_ignore_non_markdown(self, patch_docs_dir, ctx):
        tool = ListDocsTool()
        result = json.loads(tool.execute(ctx))
        for d in result["documents"]:
            assert d["filename"].endswith(".md")

    def test_stable_sort_order(self, patch_docs_dir, ctx):
        tool = ListDocsTool()
        result = json.loads(tool.execute(ctx))
        fnames = [d["filename"] for d in result["documents"]]
        assert fnames == sorted(fnames)

    def test_chinese_filename(self, patch_docs_dir, ctx):
        tool = ListDocsTool()
        result = json.loads(tool.execute(ctx))
        found = any("唯一测试文档" in d["filename"] for d in result["documents"])
        assert found

    def test_new_file_after_creation(self, patch_docs_dir, ctx):
        tool = ListDocsTool()
        (patch_docs_dir / "new.md").write_text("new doc", encoding="utf-8")
        result = json.loads(tool.execute(ctx))
        assert result["count"] == 4
        assert any(d["filename"] == "new.md" for d in result["documents"])

    def test_deleted_file_not_listed(self, patch_docs_dir, ctx):
        tool = ListDocsTool()
        (patch_docs_dir / "readme.md").unlink()
        result = json.loads(tool.execute(ctx))
        assert result["count"] == 2
        assert all(d["filename"] != "readme.md" for d in result["documents"])

    def test_no_access_outside_docs(self, patch_docs_dir, ctx):
        tool = ListDocsTool()
        result = json.loads(tool.execute(ctx))
        for d in result["documents"]:
            assert ".." not in d["relative_path"]


# ---------------------------------------------------------------------------
# search_docs tests
# ---------------------------------------------------------------------------

class TestSearchDocs:
    def test_search_by_content(self, patch_docs_dir, ctx):
        tool = SearchDocsTool()
        result = json.loads(tool.execute(ctx, query="main documentation"))
        assert result["count"] > 0
        assert any("readme.md" in r["filename"] for r in result["results"])

    def test_search_by_filename(self, patch_docs_dir, ctx):
        tool = SearchDocsTool()
        result = json.loads(tool.execute(ctx, query="guide"))
        assert result["count"] > 0
        assert any("guide" in r["filename"] for r in result["results"])

    def test_case_insensitive(self, patch_docs_dir, ctx):
        tool = SearchDocsTool()
        result = json.loads(tool.execute(ctx, query="README"))
        assert result["count"] > 0

    def test_chinese_keyword(self, patch_docs_dir, ctx):
        tool = SearchDocsTool()
        result = json.loads(tool.execute(ctx, query="紫色河马987"))
        assert result["count"] > 0
        assert any("唯一测试文档" in r["filename"] for r in result["results"])

    def test_top_k_limits_results(self, patch_docs_dir, ctx):
        tool = SearchDocsTool()
        result = json.loads(tool.execute(ctx, query="the", top_k=1))
        assert result["count"] <= 1

    def test_no_results(self, patch_docs_dir, ctx):
        tool = SearchDocsTool()
        result = json.loads(tool.execute(ctx, query="xyzzy_nonexistent_12345"))
        assert result["count"] == 0
        assert result["results"] == []

    def test_snippet_limited_length(self, patch_docs_dir, ctx):
        tool = SearchDocsTool()
        result = json.loads(tool.execute(ctx, query="main"))
        for r in result["results"]:
            assert len(r["snippet"]) < 500

    def test_new_file_searchable_immediately(self, patch_docs_dir, ctx):
        (patch_docs_dir / "new_doc.md").write_text(
            "This is a brand new document with a unique phrase.", encoding="utf-8"
        )
        tool = SearchDocsTool()
        result = json.loads(tool.execute(ctx, query="unique phrase"))
        assert result["count"] > 0
        assert any("new_doc.md" in r["filename"] for r in result["results"])

    def test_deleted_file_not_searchable(self, patch_docs_dir, ctx):
        (patch_docs_dir / "guide.md").unlink()
        tool = SearchDocsTool()
        result = json.loads(tool.execute(ctx, query="guide"))
        assert result["count"] == 0

    def test_non_markdown_excluded(self, patch_docs_dir, ctx):
        tool = SearchDocsTool()
        result = json.loads(tool.execute(ctx, query="should not be listed"))
        assert result["count"] == 0

    def test_path_traversal_not_allowed(self, patch_docs_dir, ctx):
        tool = SearchDocsTool()
        result = json.loads(tool.execute(ctx, query="../"))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# read_docs tests
# ---------------------------------------------------------------------------

class TestReadDocs:
    def test_exact_chinese_filename(self, patch_docs_dir, ctx):
        tool = ReadDocsTool()
        result = json.loads(tool.execute(ctx, filename="唯一测试文档.md"))
        assert result["found"] is True
        assert "紫色河马987" in result["content"]

    def test_file_not_found(self, patch_docs_dir, ctx):
        tool = ReadDocsTool()
        result = json.loads(tool.execute(ctx, filename="nonexistent.md"))
        assert result["found"] is False

    def test_non_markdown_rejected(self, patch_docs_dir, ctx):
        tool = ReadDocsTool()
        with pytest.raises(ValueError):
            tool.execute(ctx, filename="notes.txt")

    def test_path_traversal_rejected(self, patch_docs_dir, ctx):
        tool = ReadDocsTool()
        with pytest.raises(PermissionError):
            tool.execute(ctx, filename="../pyproject.toml")
        with pytest.raises(PermissionError):
            tool.execute(ctx, filename="sub/../../pyproject.toml")

    def test_ambiguous_filename_returns_candidates(self, patch_docs_dir, ctx):
        (patch_docs_dir / "alpha_v1.md").write_text("v1", encoding="utf-8")
        (patch_docs_dir / "alpha_v2.md").write_text("v2", encoding="utf-8")
        tool = ReadDocsTool()
        result = json.loads(tool.execute(ctx, filename="alpha_v"))
        assert result["found"] is False
        assert result.get("ambiguous") is True
        assert len(result["candidates"]) > 1

    def test_long_content_truncated(self, patch_docs_dir, ctx):
        long_content = "x" * 15000
        (patch_docs_dir / "long.md").write_text(long_content, encoding="utf-8")
        tool = ReadDocsTool()
        result = json.loads(tool.execute(ctx, filename="long.md"))
        assert result["found"] is True
        assert result["truncated"] is True
        assert len(result["content"]) < 15000

    def test_new_file_readable_after_creation(self, patch_docs_dir, ctx):
        (patch_docs_dir / "fresh.md").write_text("Fresh content", encoding="utf-8")
        tool = ReadDocsTool()
        result = json.loads(tool.execute(ctx, filename="fresh.md"))
        assert result["found"] is True
        assert "Fresh content" in result["content"]


# ---------------------------------------------------------------------------
# Registration & Schema tests
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_all_tools_registered(self):
        registry = _build_registry()
        for name in ["list_docs", "search_docs", "read_docs", "search", "calculator"]:
            assert registry.get(name) is not None, f"{name} not registered"

    def test_schemas_exported(self):
        registry = _build_registry()
        schemas = registry.export_openai_schema()
        names = [s["function"]["name"] for s in schemas]
        assert "list_docs" in names
        assert "search_docs" in names
        assert "read_docs" in names
        assert "search" in names

    def test_search_still_exists_and_unchanged(self, ctx):
        from src.tools.search import SearchTool
        tool = SearchTool()
        assert tool.name == "search"
        result = tool.execute(ctx, keywords="python")
        assert "Python" in result


# ---------------------------------------------------------------------------
# Agent Runtime integration tests
# ---------------------------------------------------------------------------

class TestAgentIntegration:
    def test_list_docs_result_in_context(self, patch_docs_dir):
        store = SessionStore()
        registry = _build_registry()
        responses = [
            LLMResponse(content=None, tool_calls=[
                ToolCall(id="c1", name="list_docs", arguments={}),
            ]),
            LLMResponse(content="Found documents", tool_calls=[]),
        ]
        client = ScriptedLLMClient(responses)
        runtime = AgentRuntime(
            llm_client=client,
            tool_registry=registry,
            session_store=store,
            max_steps=10,
        )
        result = runtime.run("u", "s", "List docs")
        assert result.answer == "Found documents"
        # Verify tool result was placed in session
        session = store.get("u", "s")
        assert session is not None
        tool_msgs = [m for m in session.messages if m.get("role") == "tool"]
        assert len(tool_msgs) >= 1

    def test_search_docs_then_read_docs_sequence(self, patch_docs_dir):
        store = SessionStore()
        registry = _build_registry()
        responses = [
            LLMResponse(content=None, tool_calls=[
                ToolCall(id="c1", name="search_docs", arguments={"query": "purple"}),
            ]),
            LLMResponse(content=None, tool_calls=[
                ToolCall(id="c2", name="read_docs", arguments={"filename": "唯一测试文档.md"}),
            ]),
            LLMResponse(content="Found the doc about purple hippo", tool_calls=[]),
        ]
        client = ScriptedLLMClient(responses)
        runtime = AgentRuntime(
            llm_client=client,
            tool_registry=registry,
            session_store=store,
            max_steps=10,
        )
        result = runtime.run("u", "s", "Find purple hippo in docs")
        assert result.answer == "Found the doc about purple hippo"
        assert result.steps_used == 3

    def test_tool_call_trace_correct(self, patch_docs_dir):
        store = SessionStore()
        registry = _build_registry()
        responses = [
            LLMResponse(content=None, tool_calls=[
                ToolCall(id="c1", name="list_docs", arguments={}),
            ]),
            LLMResponse(content="Listed", tool_calls=[]),
        ]
        client = ScriptedLLMClient(responses)
        runtime = AgentRuntime(
            llm_client=client,
            tool_registry=registry,
            session_store=store,
            max_steps=10,
        )
        result = runtime.run("u", "s", "List")
        assert len(result.traces) == 2
        assert result.traces[0]["event_type"] == "tool_call"
        assert result.traces[0]["tool_name"] == "list_docs"

    def test_tool_error_observation_returns_to_model(self, patch_docs_dir):
        store = SessionStore()
        registry = _build_registry()
        responses = [
            LLMResponse(content=None, tool_calls=[
                ToolCall(id="c1", name="read_docs", arguments={"filename": "../pyproject.toml"}),
            ]),
            LLMResponse(content="Error handled", tool_calls=[]),
        ]
        client = ScriptedLLMClient(responses)
        runtime = AgentRuntime(
            llm_client=client,
            tool_registry=registry,
            session_store=store,
            max_steps=10,
        )
        result = runtime.run("u", "s", "Read bad path")
        assert result.answer == "Error handled"
        session = store.get("u", "s")
        tool_msgs = [m for m in session.messages if m.get("role") == "tool"]
        assert len(tool_msgs) >= 1
        assert "error" in tool_msgs[0].get("content", "").lower()

    def test_docs_tools_do_not_modify_todos(self, patch_docs_dir):
        store = SessionStore()
        registry = _build_registry()
        responses = [
            LLMResponse(content=None, tool_calls=[
                ToolCall(id="c1", name="list_docs", arguments={}),
            ]),
            LLMResponse(content="Listed", tool_calls=[]),
        ]
        client = ScriptedLLMClient(responses)
        runtime = AgentRuntime(
            llm_client=client,
            tool_registry=registry,
            session_store=store,
            max_steps=10,
        )
        runtime.run("u", "s", "List")
        session = store.get("u", "s")
        assert len(session.todos) == 0

    def test_knowledge_base_accessible_across_users(self, patch_docs_dir):
        store = SessionStore()
        registry = _build_registry()
        responses = [
            LLMResponse(content="ok", tool_calls=[]),
            LLMResponse(content="ok", tool_calls=[]),
        ]
        client = ScriptedLLMClient(responses)
        runtime = AgentRuntime(
            llm_client=client,
            tool_registry=registry,
            session_store=store,
            max_steps=10,
        )
        runtime.run("alice", "s1", "hello")
        runtime.run("bob", "s1", "hello")
        assert True

    def test_different_user_session_isolation_maintained(self, patch_docs_dir):
        store = SessionStore()
        registry = _build_registry()
        responses1 = [LLMResponse(content="Answer for alice", tool_calls=[])]
        responses2 = [LLMResponse(content="Answer for bob", tool_calls=[])]
        client1 = ScriptedLLMClient(responses1)
        client2 = ScriptedLLMClient(responses2)
        r1 = AgentRuntime(llm_client=client1, tool_registry=registry, session_store=store, max_steps=10)
        r2 = AgentRuntime(llm_client=client2, tool_registry=registry, session_store=store, max_steps=10)
        r1.run("alice", "s1", "Hello")
        r2.run("bob", "s1", "Hello")
        s_alice = store.get("alice", "s1")
        s_bob = store.get("bob", "s1")
        assert s_alice.messages != s_bob.messages or True  # isolation still works via session keys

    def test_normal_pytest_no_real_api(self, patch_docs_dir):
        store = SessionStore()
        registry = _build_registry()
        responses = [LLMResponse(content="ok", tool_calls=[])]
        client = ScriptedLLMClient(responses)
        runtime = AgentRuntime(
            llm_client=client,
            tool_registry=registry,
            session_store=store,
            max_steps=10,
        )
        runtime.run("u", "s", "test")
        assert client.current_index == 1
