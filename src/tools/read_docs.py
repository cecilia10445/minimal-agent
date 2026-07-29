import os
from pathlib import Path
from typing import Any

from src.context import ToolContext
from src.tool import Tool

_DOCS_DIR = Path(__file__).resolve().parents[2] / "knowledge_docs"


class ReadDocsTool(Tool):
    name = "read_docs"
    description = "Read a Markdown document from the knowledge_docs directory."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Markdown 文件名（例如 readme.md）",
                }
            },
            "required": ["filename"],
        }

    def execute(self, context: ToolContext, filename: str) -> str:
        requested = Path(filename)

        if requested.suffix.lower() != ".md":
            raise ValueError("Only .md files are allowed.")

        if ".." in requested.parts or requested.is_absolute():
            raise PermissionError("Path traversal is not allowed.")

        full_path = (_DOCS_DIR / requested).resolve()

        if not str(full_path).startswith(str(_DOCS_DIR.resolve())):
            raise PermissionError("Access outside knowledge_docs is not allowed.")

        if not full_path.exists():
            return f"Document '{filename}' not found."

        return full_path.read_text(encoding="utf-8")
