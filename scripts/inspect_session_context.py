"""Read-only inspection of a SQLite session's context data.

Usage:
    python scripts/inspect_session_context.py --user-id user-a --session-id window-1 --db-path data/agent_sessions.db
"""

import argparse
import hashlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.context_manager import estimate_tokens
from src.sqlite_session import SQLiteSessionStore


def _preview(text: str | None, max_len: int = 80) -> str:
    if text is None:
        return "None"
    s = str(text)
    if len(s) <= max_len:
        return s
    return s[:max_len] + "..."


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _role_sequence(msgs: list[dict]) -> str:
    return " → ".join(m.get("role", "?") for m in msgs)


def _find_tool_calls_and_results(msgs: list[dict]) -> tuple[list[dict], list[dict]]:
    calls = []
    results = []
    for m in msgs:
        if m.get("role") == "assistant" and "tool_calls" in m:
            for tc in m["tool_calls"]:
                calls.append({
                    "id": tc["id"],
                    "name": tc["function"]["name"],
                    "args_preview": _preview(tc["function"].get("arguments", "{}"), 60),
                    "msg_index": msgs.index(m),
                })
        if m.get("role") == "tool":
            results.append({
                "id": m.get("tool_call_id", "?"),
                "name": m.get("name", "?"),
                "content_len": len(m.get("content", "") or ""),
                "content_sha256": _sha256(m.get("content", "") or ""),
                "content_preview": _preview(m.get("content", ""), 60),
                "msg_index": msgs.index(m),
            })
    return calls, results


def main():
    parser = argparse.ArgumentParser(description="Inspect a SQLite session's context data (read-only)")
    parser.add_argument("--user-id", required=True, help="User ID")
    parser.add_argument("--session-id", required=True, help="Session ID")
    parser.add_argument("--db-path", default="data/agent_sessions.db", help="SQLite database path")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"Session database not found: {db_path}")
        sys.exit(1)

    store = SQLiteSessionStore(db_path=str(db_path))
    session = store.get(args.user_id, args.session_id)

    if session is None:
        print(f"Session not found: user_id={args.user_id!r}, session_id={args.session_id!r}")
        sys.exit(0)

    print("=" * 65)
    print("  Session Context Inspection (read-only)")
    print("=" * 65)
    print(f"  user_id:     {session.user_id}")
    print(f"  session_id:  {session.session_id}")
    print(f"  db_path:     {db_path.resolve()}")
    print()

    # Messages
    msgs = session.messages
    msg_count = len(msgs)
    token_est = estimate_tokens(msgs)
    role_seq = _role_sequence(msgs)
    calls, results = _find_tool_calls_and_results(msgs)

    print(f"--- Messages ---")
    print(f"  Count:                {msg_count}")
    print(f"  Estimated tokens:     {token_est}")
    print(f"  Role sequence:        {role_seq}")
    print(f"  Tool calls in msgs:   {len(calls)}")
    print(f"  Tool results in msgs: {len(results)}")
    print()

    # Tool call -> result correspondence
    call_ids = {c["id"] for c in calls}
    result_ids = {r["id"] for r in results}
    matched = call_ids & result_ids
    orphan_results = result_ids - call_ids
    missing_results = call_ids - result_ids

    if orphan_results:
        print(f"  [WARN] Orphan tool results (no matching call): {orphan_results}")
    if missing_results:
        print(f"  [WARN] Tool calls with no result: {missing_results}")
    if not orphan_results and not missing_results:
        if call_ids:
            print(f"  [OK] All {len(matched)} tool calls have matching results")
        else:
            print(f"  [OK] No tool calls to verify")

    # Individual message previews
    print(f"\n--- Per-Message Detail ---")
    for i, msg in enumerate(msgs):
        role = msg.get("role", "?")
        if role == "user":
            print(f"  [{i:3d}] user           | {_preview(msg.get('content'), 100)}")
        elif role == "assistant" and "tool_calls" in msg:
            tcs = msg["tool_calls"]
            names = [f"{tc['id']}:{tc['function']['name']}" for tc in tcs]
            print(f"  [{i:3d}] assistant(tc)  | {', '.join(names)}")
        elif role == "assistant":
            print(f"  [{i:3d}] assistant      | {_preview(msg.get('content'), 100)}")
        elif role == "tool":
            content = msg.get("content", "") or ""
            print(f"  [{i:3d}] tool           | id={msg.get('tool_call_id','?')} "
                  f"name={msg.get('name','?')} | len={len(content)} "
                  f"sha256={_sha256(content)} | {_preview(content, 60)}")
        else:
            print(f"  [{i:3d}] {role:14s} | {_preview(str(msg.get('content', '')), 100)}")

    # Summary
    print(f"\n--- Summary ---")
    if session.summary:
        print(f"  Exists:   YES")
        print(f"  Length:   {len(session.summary)} chars")
        print(f"  SHA-256:  {_sha256(session.summary)}")
        print(f"  Content:")
        for line in session.summary.split("\n"):
            print(f"    {line}")
    else:
        print(f"  Exists:   NO (empty)")

    # Todos
    print(f"\n--- Todos ---")
    todos = session.todos
    print(f"  Count:    {len(todos)}")
    if todos:
        for t in todos:
            done = "x" if t.get("done") else " "
            print(f"  [{done}] #{t.get('id', '?')} {_preview(t.get('content', ''), 100)}")

    # Traces
    print(f"\n--- Traces ---")
    traces = session.traces
    print(f"  Count:    {len(traces)}")
    if traces:
        for t in traces[-10:]:  # last 10
            etype = t.get("event_type", "?")
            step = t.get("step_number", "?")
            run_id = t.get("run_id", "?")
            ok = "OK" if t.get("success") else ("FAIL" if t.get("success") is False else "?")
            if etype == "tool_call":
                print(f"  Step {step} (run {run_id}) | tool_call  | {t.get('tool_name','?')} | {ok}")
            elif etype == "final_answer":
                print(f"  Step {step} (run {run_id}) | final_answer | {ok}")
            else:
                print(f"  Step {step} (run {run_id}) | {etype} | {ok}")
        if len(traces) > 10:
            print(f"  ... ({len(traces) - 10} older traces omitted)")

    # API key check
    print(f"\n--- Security Check ---")
    all_text = str(session.messages) + str(session.summary) + str(session.traces)
    if "DASHSCOPE_API_KEY" in all_text or "sk-" in all_text:
        print(f"  [WARN] Potential API key detected in session data!")
    else:
        print(f"  [OK] No API key found in session data")

    print(f"\n{'='*65}")
    print("Read-only inspection complete.")


if __name__ == "__main__":
    main()
