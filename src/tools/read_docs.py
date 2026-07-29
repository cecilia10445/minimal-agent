import json
import os
from pathlib import Path
from typing import Any

from src.context import ToolContext
from src.tool import Tool

_DOCS_DIR = Path(__file__).resolve().parents[2] / "knowledge_docs"
_MAX_CONTENT_CHARS = 10000


def _resolve_docs_dir() -> Path:
    return _DOCS_DIR.resolve()


def _find_candidates(filename: str) -> list[str]:
    docs_dir = _resolve_docs_dir()
    if not docs_dir.is_dir():
        return []
    candidates: list[str] = []
    stem = Path(filename).stem  # e.g. "guide" from "guide.md"
    for fname in os.listdir(docs_dir):
        if not fname.lower().endswith(".md"):
            continue
        if fname == filename:
            return [fname]
        if fname.lower() == filename.lower():
            candidates.append(fname)
    if len(candidates) == 1:
        return candidates
    if len(candidates) > 1:
        return candidates
    for fname in os.listdir(docs_dir):
        if not fname.lower().endswith(".md"):
            continue
        if stem.lower() in fname.lower():
            candidates.append(fname)
    return candidates


class ReadDocsTool(Tool):
    name = "read_docs"
    description = (
        "读取本地 knowledge_docs 中的一个指定 Markdown 文档。"
        "适用于用户已经给出明确文件名，或已经通过 list_docs/search_docs 找到候选文件之后。"
    )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": (
                        "需要读取的 Markdown 文件名，例如 HiveServer2-排障总结.md"
                    ),
                }
            },
            "required": ["filename"],
            "additionalProperties": False,
        }

    def execute(self, context: ToolContext, filename: str) -> str:
        requested = Path(filename)

        if ".." in requested.parts or requested.is_absolute():
            raise PermissionError("Path traversal is not allowed.")

        if requested.suffix.lower() not in (".md", ""):
            raise ValueError("Only .md files are allowed.")

        if not requested.suffix:
            filename = filename + ".md"

        candidates = _find_candidates(filename)

        if not candidates:
            return json.dumps(
                {
                    "found": False,
                    "message": f"Document '{filename}' not found in knowledge_docs.",
                },
                ensure_ascii=False,
            )

        if len(candidates) > 1:
            return json.dumps(
                {
                    "found": False,
                    "ambiguous": True,
                    "candidates": candidates,
                    "message": (
                        f"Multiple documents match '{filename}': "
                        f"{', '.join(candidates)}. "
                        "Please specify the exact filename."
                    ),
                },
                ensure_ascii=False,
            )

        match = candidates[0]
        full_path = (_resolve_docs_dir() / match).resolve()

        if not str(full_path).startswith(str(_resolve_docs_dir())):
            raise PermissionError("Access outside knowledge_docs is not allowed.")

        if not full_path.exists():
            return json.dumps(
                {"found": False, "message": f"Document '{filename}' not found."},
                ensure_ascii=False,
            )

        content = full_path.read_text(encoding="utf-8")
        original_chars = len(content)
        truncated = original_chars > _MAX_CONTENT_CHARS
        returned_chars = original_chars
        if truncated:
            content = content[:_MAX_CONTENT_CHARS] + "\n\n... (内容过长，已截断)"
            returned_chars = len(content)

        return json.dumps(
            {
                "found": True,
                "filename": match,
                "content": content,
                "truncated": truncated,
                "original_chars": original_chars,
                "returned_chars": returned_chars,
            },
            ensure_ascii=False,
        )
