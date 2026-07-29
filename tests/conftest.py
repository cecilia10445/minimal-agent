import pytest

from src.context import ToolContext
from src.registry import ToolRegistry
from src.session import SessionStore
from src.tools.calculator import CalculatorTool
from src.tools.list_docs import ListDocsTool
from src.tools.read_docs import ReadDocsTool
from src.tools.search import SearchTool
from src.tools.search_docs import SearchDocsTool
from src.tools.todo import TodoAddTool, TodoCompleteTool, TodoListTool


@pytest.fixture
def store():
    return SessionStore()


@pytest.fixture
def registry():
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


@pytest.fixture
def ctx(store):
    return ToolContext(user_id="user1", session_id="session1", store=store)
