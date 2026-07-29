from __future__ import annotations

from typing import Any

from src.context import ToolContext
from src.tool import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def export_openai_schema(self) -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = []
        for tool in self._tools.values():
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
            )
        return schemas

    def execute(
        self, context: ToolContext, tool_name: str, arguments: dict[str, Any]
    ) -> str:
        tool = self._tools.get(tool_name)
        if tool is None:
            raise ToolNotFoundError(f"Unknown tool: {tool_name}")

        try:
            return tool.execute(context, **arguments)
        except TypeError as e:
            raise ToolParameterError(
                f"Parameter error for tool '{tool_name}': {e}"
            ) from e
        except Exception as e:
            raise ToolExecutionError(
                f"Error executing tool '{tool_name}': {e}"
            ) from e

    def clear(self) -> None:
        self._tools.clear()


class ToolNotFoundError(Exception):
    ...


class ToolParameterError(Exception):
    ...


class ToolExecutionError(Exception):
    ...
