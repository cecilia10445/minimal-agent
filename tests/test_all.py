import pytest

from src.context import ToolContext
from src.registry import ToolExecutionError, ToolNotFoundError, ToolParameterError


class TestRegistry:
    def test_register_and_get(self, registry):
        tool = registry.get("calculator")
        assert tool is not None
        assert tool.name == "calculator"

    def test_get_unknown(self, registry):
        assert registry.get("nonexistent") is None

    def test_export_schema(self, registry):
        schemas = registry.export_openai_schema()
        names = [s["function"]["name"] for s in schemas]
        assert "calculator" in names
        assert "search" in names
        assert "read_docs" in names
        assert "todo_add" in names
        assert "todo_list" in names
        assert "todo_complete" in names

    def test_clear(self, registry):
        registry.clear()
        assert registry.get("calculator") is None


class TestCalculator:
    def test_normal(self, registry, ctx):
        result = registry.execute(ctx, "calculator", {"expression": "1 + 2 * 3"})
        assert result == "7.0"

    def test_division(self, registry, ctx):
        result = registry.execute(ctx, "calculator", {"expression": "10 / 2"})
        assert result == "5.0"

    def test_power(self, registry, ctx):
        result = registry.execute(ctx, "calculator", {"expression": "2 ** 10"})
        assert result == "1024.0"

    def test_illegal_expression(self, registry, ctx):
        with pytest.raises(ToolExecutionError):
            registry.execute(ctx, "calculator", {"expression": "__import__('os')"})

    def test_illegal_string(self, registry, ctx):
        with pytest.raises(ToolExecutionError):
            registry.execute(ctx, "calculator", {"expression": "'hello'"})


class TestSearch:
    def test_hit(self, registry, ctx):
        result = registry.execute(ctx, "search", {"keywords": "python"})
        assert "Python" in result

    def test_miss(self, registry, ctx):
        result = registry.execute(ctx, "search", {"keywords": "nonexistent"})
        assert result == "No results found."

    def test_agent_runtime_hit(self, registry, ctx):
        result = registry.execute(ctx, "search", {"keywords": "Agent Runtime"})
        assert "Agent Runtime" in result

    def test_agent_runtime_lowercase(self, registry, ctx):
        result = registry.execute(ctx, "search", {"keywords": "agent runtime"})
        assert "Agent Runtime" in result

    def test_function_calling_hit(self, registry, ctx):
        result = registry.execute(ctx, "search", {"keywords": "function calling"})
        assert "Function calling" in result

    def test_context_management_case_insensitive(self, registry, ctx):
        result = registry.execute(ctx, "search", {"keywords": "CONTEXT MANAGEMENT"})
        assert "Context management" in result


class TestReadDocs:
    def test_normal(self, registry, ctx):
        result = registry.execute(ctx, "read_docs", {"filename": "readme.md"})
        assert "Knowledge Docs" in result

    def test_non_md(self, registry, ctx):
        with pytest.raises(ToolExecutionError):
            registry.execute(ctx, "read_docs", {"filename": "readme.txt"})

    def test_path_traversal(self, registry, ctx):
        with pytest.raises(ToolExecutionError):
            registry.execute(ctx, "read_docs", {"filename": "../pyproject.toml"})

    def test_not_found(self, registry, ctx):
        result = registry.execute(ctx, "read_docs", {"filename": "nope.md"})
        assert "not found" in result


class TestTodo:
    def test_add_and_list(self, registry, ctx):
        r1 = registry.execute(ctx, "todo_add", {"content": "Buy milk"})
        assert "#1" in r1
        r2 = registry.execute(ctx, "todo_add", {"content": "Write code"})
        assert "#2" in r2
        r3 = registry.execute(ctx, "todo_list", {})
        assert "Buy milk" in r3
        assert "Write code" in r3

    def test_complete(self, registry, ctx):
        registry.execute(ctx, "todo_add", {"content": "Task A"})
        r = registry.execute(ctx, "todo_complete", {"id": 1})
        assert "completed" in r
        listing = registry.execute(ctx, "todo_list", {})
        assert "[x]" in listing

    def test_empty_list(self, registry, ctx):
        result = registry.execute(ctx, "todo_list", {})
        assert result == "No todos."

    def test_complete_not_found(self, registry, ctx):
        r = registry.execute(ctx, "todo_complete", {"id": 99})
        assert "not found" in r


class TestSessionIsolation:
    def test_same_user_diff_session(self, store):
        ctx1 = ToolContext(user_id="alice", session_id="sess_a", store=store)
        ctx2 = ToolContext(user_id="alice", session_id="sess_b", store=store)

        from src.tools.todo import TodoAddTool, TodoListTool
        add = TodoAddTool()
        lst = TodoListTool()

        add.execute(ctx1, content="Alice session A todo")
        result_a = lst.execute(ctx1)
        result_b = lst.execute(ctx2)
        assert "Alice session A todo" in result_a
        assert result_b == "No todos."

    def test_diff_user_diff_session(self, store):
        ctx1 = ToolContext(user_id="bob", session_id="s1", store=store)
        ctx2 = ToolContext(user_id="carol", session_id="s1", store=store)

        from src.tools.todo import TodoAddTool, TodoListTool
        add = TodoAddTool()
        lst = TodoListTool()

        add.execute(ctx1, content="Bob's todo")
        result_bob = lst.execute(ctx1)
        result_carol = lst.execute(ctx2)
        assert "Bob's todo" in result_bob
        assert result_carol == "No todos."


class TestErrorHandling:
    def test_unknown_tool(self, registry, ctx):
        with pytest.raises(ToolNotFoundError):
            registry.execute(ctx, "nonexistent", {})

    def test_missing_parameter(self, registry, ctx):
        with pytest.raises(ToolParameterError):
            registry.execute(ctx, "calculator", {})

    def test_wrong_parameter_type(self, registry, ctx):
        with pytest.raises(ToolParameterError):
            registry.execute(ctx, "read_docs", {"filename": 123})
