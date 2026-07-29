from src.registry import ToolRegistry
from src.tools.calculator import CalculatorTool
from src.tools.read_docs import ReadDocsTool
from src.tools.search import SearchTool
from src.tools.todo import TodoAddTool, TodoCompleteTool, TodoListTool


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(CalculatorTool())
    registry.register(SearchTool())
    registry.register(ReadDocsTool())
    registry.register(TodoAddTool())
    registry.register(TodoListTool())
    registry.register(TodoCompleteTool())
    return registry
