import json
import os
from pathlib import Path
from typing import Any

from src.context import ToolContext
from src.tool import Tool

_DOCS_DIR = Path(__file__).resolve().parents[2] / "knowledge_docs"
_SNIPPET_CHARS = 120


def _resolve_docs_dir() -> Path:
    return _DOCS_DIR.resolve()


def _read_safe(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _snippet(text: str, query: str, context_chars: int = _SNIPPET_CHARS) -> str:
    idx = text.lower().find(query.lower())
    if idx == -1:
        return text[:context_chars]
    start = max(0, idx - context_chars // 2)
    end = min(len(text), idx + len(query) + context_chars // 2)
    snippet = text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


class SearchDocsTool(Tool):
    name = "search_docs"
    description = (
        "在本地 knowledge_docs 知识库的所有 Markdown 文件名和正文中搜索关键词。"
        "当用户要求在本地文档、知识库或资料中查找某个词、主题或内容时使用。"
        "不要使用通用 search 代替。"
    )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "需要在本地知识文档中搜索的关键词或短语",
                },
                "top_k": {
                    "type": "integer",
                    "description": "最多返回多少个匹配文档",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 5,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    def execute(self, context: ToolContext, query: str, top_k: int = 5) -> str:
        docs_dir = _resolve_docs_dir()
        if not docs_dir.is_dir():
            return json.dumps(
                {"query": query, "count": 0, "results": []},
                ensure_ascii=False,
            )

        q = query.lower()
        scored: list[dict[str, Any]] = []

        for fname in sorted(os.listdir(docs_dir)):
            if not fname.lower().endswith(".md"):
                continue
            relevance = 0
            match_source: str | None = None
            snippet_text = ""

            # Filename exact match (highest priority)
            if fname.lower() == q:
                relevance += 10
                match_source = "filename"
                snippet_text = fname
            # Filename contains
            elif q in fname.lower():
                relevance += 5
                match_source = "filename"
                snippet_text = fname

            # Content match
            fpath = docs_dir / fname
            content = _read_safe(fpath)
            if content is not None:
                content_lower = content.lower()
                count_in_content = content_lower.count(q)
                if count_in_content > 0:
                    relevance += count_in_content
                    if match_source is None:
                        match_source = "content"
                    snippet_text = _snippet(content, q)

            if relevance > 0:
                scored.append(
                    {
                        "filename": fname,
                        "match_source": match_source or "content",
                        "snippet": snippet_text,
                        "relevance_score": relevance,
                    }
                )

        scored.sort(key=lambda x: (-x["relevance_score"], x["filename"]))
        top = scored[:top_k]

        return json.dumps(
            {"query": query, "count": len(top), "results": top},
            ensure_ascii=False,
        )
