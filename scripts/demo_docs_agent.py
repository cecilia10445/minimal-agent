"""
Real qwen3.6-plus end-to-end demo for local document tools.

Usage:
    $env:RUN_REAL_LLM_TESTS="1"; python scripts/demo_docs_agent.py

Requires DASHSCOPE_API_KEY in .env or environment.
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

api_key = os.getenv("DASHSCOPE_API_KEY")
run_real = os.getenv("RUN_REAL_LLM_TESTS") == "1"

if not run_real:
    print("SKIP: RUN_REAL_LLM_TESTS is not enabled.")
    raise SystemExit(0)

if not api_key:
    print("SKIP: DASHSCOPE_API_KEY not configured.")
    raise SystemExit(0)

# Ensure project root is on sys.path
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import AgentRuntime
from src.bootstrap import build_default_registry
from src.config import load_llm_settings
from src.prompt import SYSTEM_PROMPT
from src.qwen_client import OpenAICompatibleLLMClient
from src.session import SessionStore


_DEMO_FILE = "knowledge_docs/__agent_dynamic_demo__.md"
_DEMO_USER = "docs-demo-user"
_DEMO_SESSION = "docs-demo-session"


def main():
    # Create the dynamic demo file
    demo_path = PROJECT_ROOT / _DEMO_FILE
    demo_path.parent.mkdir(parents=True, exist_ok=True)
    demo_path.write_text(
        "# Dynamic Document Demo\n\n"
        "Unique ID: \u84dd\u8272\u9cb8\u9c7c2468.\n"
        "Purpose: Verify that the Agent can discover newly added local "
        "knowledge documents without restarting.\n",
        encoding="utf-8",
    )

    try:
        settings = load_llm_settings()
    except Exception as e:
        print(f"Configuration error: {e}")
        demo_path.unlink(missing_ok=True)
        sys.exit(1)

    try:
        llm_client = OpenAICompatibleLLMClient(settings=settings)
    except Exception as e:
        print(f"Failed to create LLM client: {e}")
        demo_path.unlink(missing_ok=True)
        sys.exit(1)

    store = SessionStore()
    registry = build_default_registry()

    runtime = AgentRuntime(
        llm_client=llm_client,
        tool_registry=registry,
        session_store=store,
        system_prompt=SYSTEM_PROMPT,
        max_steps=10,
    )

    questions = [
        "Please list all Markdown documents currently in the local knowledge base.",
        "Search the local documents for \u201c\u84dd\u8272\u9cb8\u9c7c2468\u201d.",
        "Read the document you just found and tell me what it is used to verify.",
    ]

    expected_tools = ["list_docs", "search_docs", "read_docs"]
    all_ok = True

    for i, question in enumerate(questions):
        print(f"\n{'='*60}")
        print(f"Round {i+1}: {question}")
        print(f"{'='*60}")

        try:
            result = runtime.run(
                user_id=_DEMO_USER,
                session_id=_DEMO_SESSION,
                user_input=question,
            )
        except Exception as e:
            print(f"ERROR: {type(e).__name__}: {e}")
            all_ok = False
            continue

        print(f"\nAnswer: {result.answer}")
        print(f"Steps used: {result.steps_used}")

        # Check which tools were actually called
        called_tools = [
            t.get("tool_name", "?")
            for t in result.traces
            if t["event_type"] == "tool_call"
        ]
        seen = set()
        called_tools_unique = []
        for t in called_tools:
            if t not in seen:
                seen.add(t)
                called_tools_unique.append(t)

        print(f"Tools called: {called_tools_unique}")

        expected = expected_tools[i]
        if expected in called_tools_unique:
            print(f"OK: Expected tool '{expected}' was called.")
        else:
            print(f"FAIL: Expected tool '{expected}' was NOT called.")
            all_ok = False

        if "blue" in result.answer.lower() or "\u84dd\u8272" in result.answer:
            print("OK: Dynamic demo document content found in answer.")
        if "2468" in result.answer:
            print("OK: Identifier '2468' found in answer.")

    # Final report
    print(f"\n{'='*60}")
    print(f"Demo Summary")
    print(f"{'='*60}")
    print(f"All rounds passed: {all_ok}")

    session = store.get(_DEMO_USER, _DEMO_SESSION)
    if session:
        tool_names_in_session = set()
        for m in session.messages:
            if m.get("role") == "assistant" and "tool_calls" in m:
                for tc in m["tool_calls"]:
                    tool_names_in_session.add(tc["function"]["name"])
        print(f"Tools used in session: {tool_names_in_session}")
        for et in expected_tools:
            if et in tool_names_in_session:
                print(f"  {et}: YES")
            else:
                print(f"  {et}: NO")
                all_ok = False

    if all_ok:
        print("\nSUCCESS: All document routing tests passed.")
    else:
        print("\nFAILURE: Some routing tests did not pass.")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    try:
        main()
    finally:
        demo_path = PROJECT_ROOT / _DEMO_FILE
        if demo_path.exists():
            demo_path.unlink()
