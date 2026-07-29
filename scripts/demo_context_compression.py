"""
Demo script for context compression (zero API calls).

Constructs multi-turn messages with tool calls, triggers compression
via a small-token ContextPolicy, and prints before/after stats.
"""

import json
from src.context_manager import ContextManager, ContextPolicy, estimate_tokens
from src.session import Session


def _build_demo_session() -> Session:
    messages: list[dict] = []

    # Turn 1: Plain chat
    messages.append({"role": "user", "content": "What is the weather today?"})
    messages.append({"role": "assistant", "content": "It is sunny and 25 degrees."})

    # Turn 2: Tool call (calculator)
    messages.append({"role": "user", "content": "Calculate 15 * 23"})
    messages.append({
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_calc",
                "type": "function",
                "function": {"name": "calculator", "arguments": '{"expression":"15*23"}'},
            }
        ],
    })
    messages.append({
        "role": "tool",
        "tool_call_id": "call_calc",
        "name": "calculator",
        "content": json.dumps({"ok": True, "result": "345.0"}, ensure_ascii=False),
    })
    messages.append({"role": "assistant", "content": "15 * 23 = 345"})

    # Turn 3: Another tool call (search)
    messages.append({"role": "user", "content": "Search for Python language"})
    messages.append({
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_search",
                "type": "function",
                "function": {"name": "search", "arguments": '{"keywords":"Python"}'},
            }
        ],
    })
    messages.append({
        "role": "tool",
        "tool_call_id": "call_search",
        "name": "search",
        "content": json.dumps({"ok": True, "result": "Python is a programming language."}, ensure_ascii=False),
    })
    messages.append({"role": "assistant", "content": "Python is a programming language."})

    # Turn 4: Parallel tool calls
    messages.append({"role": "user", "content": "Calculate 100 / 5 and 2 ** 8"})
    messages.append({
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "c1",
                "type": "function",
                "function": {"name": "calculator", "arguments": '{"expression":"100/5"}'},
            },
            {
                "id": "c2",
                "type": "function",
                "function": {"name": "calculator", "arguments": '{"expression":"2**8"}'},
            },
        ],
    })
    messages.append({
        "role": "tool",
        "tool_call_id": "c1",
        "name": "calculator",
        "content": json.dumps({"ok": True, "result": "20.0"}, ensure_ascii=False),
    })
    messages.append({
        "role": "tool",
        "tool_call_id": "c2",
        "name": "calculator",
        "content": json.dumps({"ok": True, "result": "256.0"}, ensure_ascii=False),
    })
    messages.append({"role": "assistant", "content": "100 / 5 = 20, 2 ** 8 = 256"})

    # Turn 5: Plain question
    messages.append({"role": "user", "content": "What is the capital of France?"})
    messages.append({"role": "assistant", "content": "The capital of France is Paris."})

    session = Session(user_id="demo_user", session_id="demo_session")
    session.messages = messages
    return session


def _check_isolated_tool_messages(messages: list[dict]) -> list[str]:
    issues: list[str] = []
    tool_call_ids = set()
    tool_result_ids = set()
    for msg in messages:
        if msg.get("role") == "assistant" and "tool_calls" in msg:
            for tc in msg["tool_calls"]:
                tool_call_ids.add(tc["id"])
        if msg.get("role") == "tool":
            tool_result_ids.add(msg.get("tool_call_id", ""))
    orphan_results = tool_result_ids - tool_call_ids
    missing_results = tool_call_ids - tool_result_ids
    if orphan_results:
        issues.append(f"Orphan tool result(s) without matching call: {orphan_results}")
    if missing_results:
        issues.append(f"Missing tool result(s) for call(s): {missing_results}")
    return issues


def main() -> None:
    policy = ContextPolicy(
        max_estimated_tokens=1,
        keep_recent_user_turns=1,
        max_summary_chars=500,
        max_item_chars=200,
    )
    cm = ContextManager(policy)
    session = _build_demo_session()

    before_count = len(session.messages)
    before_tokens = estimate_tokens(session.messages)

    print("=== Context Compression Demo (zero API calls) ===\n")
    print(f"Policy: max_estimated_tokens={policy.max_estimated_tokens}, "
          f"keep_recent_user_turns={policy.keep_recent_user_turns}")
    print(f"Before compression:")
    print(f"  Messages: {before_count}")
    print(f"  Estimated tokens: {before_tokens}")
    print(f"  Summary length: {len(session.summary)} chars")
    print(f"  Summary: {session.summary!r}\n")

    compressed = cm.prepare_session(session)

    print(f"Compression triggered: {compressed}\n")

    after_count = len(session.messages)
    after_tokens = estimate_tokens(session.messages)

    print(f"After compression:")
    print(f"  Messages: {after_count}")
    print(f"  Estimated tokens: {after_tokens}")
    print(f"  Kept {policy.keep_recent_user_turns} recent user turn(s)")

    kept_user_turns = sum(1 for m in session.messages if m.get("role") == "user")
    print(f"  User turns remaining: {kept_user_turns}")
    print(f"  Summary length: {len(session.summary)} chars")
    print(f"  Summary:")
    for line in session.summary.split("\n"):
        print(f"    {line}")

    issues = _check_isolated_tool_messages(session.messages)
    if issues:
        print(f"\nIssues found:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print(f"\nNo orphan tool messages or missing results.")

    print()


if __name__ == "__main__":
    main()
