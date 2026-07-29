from typing import Any

from src.context import ToolContext
from src.tool import Tool

_MOCK_DATA: dict[str, str] = {
    "python": "Python is a high-level, general-purpose programming language.",
    "flask": "Flask is a micro web framework written in Python.",
    "ast": "AST (Abstract Syntax Tree) is a tree representation of source code.",
    "agent runtime": "Agent Runtime is the core loop that manages tool calling, session state, and step limits in an agent system.",
    "function calling": "Function calling allows LLMs to request tool execution by returning structured tool_calls instead of plain text.",
    "context management": "Context management handles message history, session isolation, and trace recording across multiple user interactions.",
}


class SearchTool(Tool):
    name = "search"
    description = "Search for information using keywords."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "string",
                    "description": "搜索关键词",
                }
            },
            "required": ["keywords"],
        }

    def execute(self, context: ToolContext, keywords: str) -> str:
        query = keywords.lower()
        results = []
        for key, val in _MOCK_DATA.items():
            if query in key.lower():
                results.append(f"{key}: {val}")
        if not results:
            return "No results found."
        return "\n".join(results)
