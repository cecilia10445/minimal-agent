import json
import os
from pathlib import Path
from typing import Any

from src.context import ToolContext
from src.tool import Tool

_DOCS_DIR = Path(__file__).resolve().parents[2] / "knowledge_docs"


def _resolve_docs_dir() -> Path:
    return _DOCS_DIR.resolve()


class ListDocsTool(Tool):
    name = "list_docs"
    description = "列出本地 knowledge_docs 知识库中当前存在的所有 Markdown 文档。当用户询问当前有哪些、全部有哪些、是否存在某类本地文档时使用。"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }

    def execute(self, context: ToolContext) -> str:
        docs_dir = _resolve_docs_dir()
        if not docs_dir.is_dir():
            return json.dumps(
                {"count": 0, "documents": []}, ensure_ascii=False
            )
        entries: list[dict[str, str]] = []
        for fname in sorted(os.listdir(docs_dir)):
            if fname.lower().endswith(".md"):
                entries.append(
                    {"filename": fname, "relative_path": fname}
                )
        return json.dumps(
            {"count": len(entries), "documents": entries},
            ensure_ascii=False,
        )
