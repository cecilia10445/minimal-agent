"""Zero-API inspection script for long document truncation behavior.

Directly uses ReadDocsTool and SearchDocsTool from the project.
Creates a temporary long document, reads it, and reports truncation metadata.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.context import ToolContext
from src.session import SessionStore
from src.tools.read_docs import ReadDocsTool
from src.tools.search_docs import SearchDocsTool

END_MARKER = "文档末尾识别码：银色狮子8642"
TARGET_CHARS = 12000  # exceeds _MAX_CONTENT_CHARS (10000)


def _create_long_doc(docs_dir: Path) -> str:
    filename = "_inspect_long_test_temp_.md"
    filepath = docs_dir / filename
    line = "这是用于测试长文档截断行为的重复行。\n"
    repetitions = (TARGET_CHARS // len(line)) + 1
    content = "# 长文档截断测试\n\n" + (line * repetitions) + "\n\n" + END_MARKER
    filepath.write_text(content, encoding="utf-8")
    print(f"[setup] Created {filepath.name} ({len(content)} chars)")
    return filename


def main():
    # Create a temp docs directory to avoid touching real knowledge_docs
    with tempfile.TemporaryDirectory(prefix="inspect_docs_") as tmpdir:
        docs_dir = Path(tmpdir) / "knowledge_docs"
        docs_dir.mkdir(parents=True)
        print(f"[setup] Using temp docs dir: {docs_dir}")

        # Monkey-patch the tool globals to point at our temp dir
        import src.tools.read_docs as read_docs_mod
        import src.tools.search_docs as search_docs_mod
        read_docs_mod._DOCS_DIR = docs_dir
        search_docs_mod._DOCS_DIR = docs_dir

        filename = _create_long_doc(docs_dir)

        store = SessionStore()
        ctx = ToolContext(user_id="inspect", session_id="inspect-s1", store=store)

        # --- ReadDocsTool ---
        read_tool = ReadDocsTool()
        raw_result = read_tool.execute(ctx, filename=filename)
        result = json.loads(raw_result)

        print(f"\n--- ReadDocsTool Result ---")
        print(f"  filename:       {result.get('filename')}")
        print(f"  found:          {result.get('found')}")
        print(f"  truncated:      {result.get('truncated')}")
        print(f"  original_chars: {result.get('original_chars')}")
        print(f"  returned_chars: {result.get('returned_chars')}")

        content = result.get("content", "")
        if content:
            print(f"  content[:100]:  {content[:100]!r}")
            print(f"  content[-200:]: {content[-200:]!r}")
        else:
            print(f"  content:        (empty)")

        if result.get("truncated"):
            print(f"  [OK] truncated=true - document exceeds limit")
        else:
            print(f"  [WARN] truncated=false - document fit in limit")

        if result.get("original_chars", 0) > result.get("returned_chars", 0):
            print(f"  [OK] original_chars > returned_chars - metadata correct")
        else:
            print(f"  [WARN] original_chars <= returned_chars - may not be truncated")

        if END_MARKER in content:
            print(f"  [WARN] END MARKER FOUND in read_docs content (unexpected)")
        else:
            print(f"  [OK] End marker NOT in read_docs content - as expected")

        # --- SearchDocsTool ---
        search_tool = SearchDocsTool()
        raw_search = search_tool.execute(ctx, query=END_MARKER, top_k=5)
        search_result = json.loads(raw_search)

        print(f"\n--- SearchDocsTool Result ---")
        print(f"  query:   {search_result.get('query')}")
        print(f"  matches: {len(search_result.get('results', []))}")

        found = False
        for r in search_result.get("results", []):
            if filename in r.get("filename", ""):
                found = True
                print(f"  [OK] search_docs found {filename}: snippet={r.get('snippet', '')[:60]}")
                break

        if not found:
            print(f"  [WARN] search_docs did NOT find {filename} for end marker")

        print(f"\n--- Summary ---")
        print(f"  File:               {filename}")
        print(f"  Original chars:     {result.get('original_chars', 'N/A')}")
        print(f"  Returned chars:     {result.get('returned_chars', 'N/A')}")
        print(f"  Truncated:          {result.get('truncated', 'N/A')}")
        print(f"  read_docs tail 200: {content[-200:] if content else 'N/A'}")
        print(f"  search_docs found   {END_MARKER}: {'YES' if found else 'NO'}")

        # Cleanup is handled by temp directory context manager
        print(f"\n[cleanup] Temp dir removed automatically.")


if __name__ == "__main__":
    main()
