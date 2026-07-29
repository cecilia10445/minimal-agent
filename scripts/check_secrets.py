"""Check for API keys and secrets in source files.

Usage:
    python scripts/check_secrets.py
    python scripts/check_secrets.py --fix
"""

import argparse
import re
import sys
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PATTERNS = [
    (r'sk-[A-Za-z0-9]{20,}', "OpenAI-style API key"),
    (r'DASHSCOPE_API_KEY=.+', "DASHSCOPE_API_KEY value"),
    (r'Authorization:\s*Bearer\s+\S+', "Authorization header"),
    (r'api_key\s*=\s*["\'](?!\s*$)', "api_key assignment (non-empty)"),
]

_EXTENSIONS = {'.py', '.json', '.jsonl', '.md', '.txt', '.yml', '.yaml', '.toml', '.cfg', '.ini', '.env.example'}
_SKIP_DIRS = {'.git', '__pycache__', '.pytest_cache', '.venv', 'venv', 'data', 'reports', 'node_modules'}
_SKIP_FILES = {'check_secrets.py'}


def _should_skip(path: Path) -> bool:
    if path.name in _SKIP_FILES:
        return True
    for part in path.parts:
        if part in _SKIP_DIRS:
            return True
    return False


def main():
    parser = argparse.ArgumentParser(description="Check for secrets in source files")
    parser.add_argument("--fix", action="store_true", help="Remove lines containing secrets")
    args = parser.parse_args()

    issues = []
    for path in _PROJECT_ROOT.rglob("*"):
        if _should_skip(path):
            continue
        if path.suffix not in _EXTENSIONS:
            continue
        if not path.is_file():
            continue

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        for i, line in enumerate(content.splitlines(), 1):
            for pattern, desc in _PATTERNS:
                if re.search(pattern, line):
                    issues.append((path, i, desc, line.strip()))

    if not issues:
        print("No secrets found.")
        return

    print(f"Found {len(issues)} potential secret(s):")
    for path, line_num, desc, text in issues:
        masked = text[:20] + "..." if len(text) > 40 else text
        print(f"  {path}:{line_num} [{desc}] {masked}")

    if args.fix:
        print("\n--fix not implemented; remove secrets manually.")
        sys.exit(1)

    sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()
