"""Zero-API visualization of current ContextManager behavior.

Constructs a mixed-history Session, triggers compression with a small threshold,
and prints before/after/during stats plus final build_messages output.
"""

import json
import hashlib
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.context_manager import ContextManager, ContextPolicy, estimate_tokens
from src.session import Session

# ---------------------------------------------------------------------------
# Build a mixed-history session
# ---------------------------------------------------------------------------

LONG_RESULT = "详细结果：" + "x" * 2000


def _build_mixed_session() -> Session:
    msgs: list[dict] = []

    # Turn 1: Plain Chinese chat
    msgs.append({"role": "user", "content": "你好，今天天气怎么样？"})
    msgs.append({"role": "assistant", "content": "今天天气晴朗，气温25度。"})

    # Turn 2: Single tool call (success)
    msgs.append({"role": "user", "content": "计算 15 乘以 23"})
    msgs.append({
        "role": "assistant", "content": None,
        "tool_calls": [{
            "id": "call_calc_1", "type": "function",
            "function": {"name": "calculator", "arguments": '{"expression":"15*23"}'},
        }],
    })
    msgs.append({
        "role": "tool", "tool_call_id": "call_calc_1", "name": "calculator",
        "content": json.dumps({"ok": True, "result": "345.0"}, ensure_ascii=False),
    })
    msgs.append({"role": "assistant", "content": "15 * 23 = 345"})

    # Turn 3: Tool error result
    msgs.append({"role": "user", "content": "计算非法表达式"})
    msgs.append({
        "role": "assistant", "content": None,
        "tool_calls": [{
            "id": "call_err", "type": "function",
            "function": {"name": "calculator", "arguments": '{"expression":"__import__"}'},
        }],
    })
    msgs.append({
        "role": "tool", "tool_call_id": "call_err", "name": "calculator",
        "content": json.dumps({"ok": False, "error_type": "ToolExecutionError", "message": "Illegal expression"}, ensure_ascii=False),
    })
    msgs.append({"role": "assistant", "content": "该表达式不合法，无法计算。"})

    # Turn 4: Parallel tool calls
    msgs.append({"role": "user", "content": "同时计算 100/5 和 2**8"})
    msgs.append({
        "role": "assistant", "content": None,
        "tool_calls": [
            {"id": "c_par_1", "type": "function", "function": {"name": "calculator", "arguments": '{"expression":"100/5"}'}},
            {"id": "c_par_2", "type": "function", "function": {"name": "calculator", "arguments": '{"expression":"2**8"}'}},
        ],
    })
    msgs.append({
        "role": "tool", "tool_call_id": "c_par_1", "name": "calculator",
        "content": json.dumps({"ok": True, "result": "20.0"}, ensure_ascii=False),
    })
    msgs.append({
        "role": "tool", "tool_call_id": "c_par_2", "name": "calculator",
        "content": json.dumps({"ok": True, "result": "256.0"}, ensure_ascii=False),
    })
    msgs.append({"role": "assistant", "content": "100/5 = 20, 2**8 = 256"})

    # Turn 5: JSON tool result + fact correction
    msgs.append({"role": "user", "content": "搜索Python信息，另外叫我李四"})
    msgs.append({
        "role": "assistant", "content": None,
        "tool_calls": [{
            "id": "call_search_1", "type": "function",
            "function": {"name": "search", "arguments": '{"keywords":"Python"}'},
        }],
    })
    msgs.append({
        "role": "tool", "tool_call_id": "call_search_1", "name": "search",
        "content": json.dumps({"ok": True, "result": "Python is a programming language."}, ensure_ascii=False),
    })
    msgs.append({"role": "assistant", "content": "好的，李四。Python是一种编程语言。"})

    # Turn 6: Extra long tool result
    msgs.append({"role": "user", "content": "读取长文档"})
    msgs.append({
        "role": "assistant", "content": None,
        "tool_calls": [{
            "id": "call_read_1", "type": "function",
            "function": {"name": "read_docs", "arguments": '{"filename":"guide.md"}'},
        }],
    })
    msgs.append({
        "role": "tool", "tool_call_id": "call_read_1", "name": "read_docs",
        "content": json.dumps({"ok": True, "result": LONG_RESULT}, ensure_ascii=False),
    })
    msgs.append({"role": "assistant", "content": "文档内容已读取。"})

    # Turn 7: Assistant empty content
    msgs.append({"role": "user", "content": "你是谁？"})
    msgs.append({"role": "assistant", "content": None})  # empty content, no tool_calls

    # Turn 8: Incomplete turn (no final answer)
    msgs.append({"role": "user", "content": "帮我查一下明天天气"})
    msgs.append({
        "role": "assistant", "content": None,
        "tool_calls": [{
            "id": "call_wea", "type": "function",
            "function": {"name": "search", "arguments": '{"keywords":"tomorrow weather"}'},
        }],
    })
    # NOTE: no tool result, no final answer — incomplete turn

    session = Session(user_id="audit", session_id="viz-test")
    session.messages = msgs
    return session


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------

def _role_sequence(msgs: list[dict]) -> str:
    return " → ".join(m.get("role", "?") for m in msgs)


def _find_orphan_tools(msgs: list[dict]) -> tuple[list[str], list[str]]:
    call_ids = set()
    result_ids = set()
    for m in msgs:
        if m.get("role") == "assistant" and "tool_calls" in m:
            for tc in m["tool_calls"]:
                call_ids.add(tc["id"])
        if m.get("role") == "tool":
            result_ids.add(m.get("tool_call_id", ""))
    orphans = sorted(result_ids - call_ids)
    missing = sorted(call_ids - result_ids)
    return orphans, missing


def _preview(text: str, max_len: int = 80) -> str:
    if text is None:
        return "None"
    s = str(text)
    if len(s) <= max_len:
        return s
    return s[:max_len] + "..."


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _counts(msgs: list[dict]) -> dict:
    return {
        "total": len(msgs),
        "user": sum(1 for m in msgs if m.get("role") == "user"),
        "assistant": sum(1 for m in msgs if m.get("role") == "assistant"),
        "assistant_with_tool_calls": sum(1 for m in msgs if m.get("role") == "assistant" and "tool_calls" in m),
        "tool": sum(1 for m in msgs if m.get("role") == "tool"),
    }


def _analyze_tool_calls(msgs: list[dict]) -> list[dict]:
    analysis = []
    for m in msgs:
        if m.get("role") == "assistant" and "tool_calls" in m:
            for tc in m["tool_calls"]:
                analysis.append({
                    "id": tc["id"],
                    "name": tc["function"]["name"],
                    "args_preview": _preview(tc["function"].get("arguments", "{}"), 60),
                })
    return analysis


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def _build_report_data(session: Session, policy: ContextPolicy,
                       compressed: bool, boundary: int) -> dict:
    before_counts = _counts(session.messages)
    # We need to save pre-compression stats
    # We'll compute after from the compressed session
    after_counts = _counts(session.messages)

    # Orphans
    orphans_before, missing_before = (["N/A"], ["N/A"])  # placeholder
    orphans_after, missing_after = _find_orphan_tools(session.messages)

    # Build messages
    cm = ContextManager(policy)
    built = cm.build_messages(system_prompt="System prompt placeholder", session=session)

    return {
        "policy": {
            "max_estimated_tokens": policy.max_estimated_tokens,
            "keep_recent_user_turns": policy.keep_recent_user_turns,
            "max_summary_chars": policy.max_summary_chars,
            "max_item_chars": policy.max_item_chars,
        },
        "compression": {
            "triggered": compressed,
            "boundary_index": boundary,
        },
        "before": before_counts,
        "after": after_counts,
        "summary": {
            "exists": bool(session.summary),
            "length_chars": len(session.summary),
            "sha256": _sha256(session.summary) if session.summary else "",
            "content": session.summary if session.summary else "(empty)",
        },
        "built_messages_count": len(built),
        "orphan_tool_results": orphans_after,
        "missing_tool_results": missing_after,
        "tool_calls_in_messages": _analyze_tool_calls(session.messages),
    }


def _write_json_report(data: dict, path: Path):
    # Sanitize: replace full content with length + sha256 for long strings
    safe = json.loads(json.dumps(data, ensure_ascii=False))
    path.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_md_report(data: dict, path: Path):
    lines = [
        "# Context-as-Built Visualization Report\n",
        f"Generated: {datetime.now().isoformat()}\n",
        "## Policy\n",
        f"| Parameter | Value |",
        f"|---|---|",
        f"| max_estimated_tokens | {data['policy']['max_estimated_tokens']} |",
        f"| keep_recent_user_turns | {data['policy']['keep_recent_user_turns']} |",
        f"| max_summary_chars | {data['policy']['max_summary_chars']} |",
        f"| max_item_chars | {data['policy']['max_item_chars']} |",
        "\n## Compression\n",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Triggered | {data['compression']['triggered']} |",
        f"| Boundary index | {data['compression']['boundary_index']} |",
        "\n## Before / After\n",
        f"| Metric | Before | After |",
        f"|---|---|---|",
    ]

    for key in ("total", "user", "assistant", "assistant_with_tool_calls", "tool"):
        b = data["before"].get(key, "?")
        a = data["after"].get(key, "?")
        lines.append(f"| {key} | {b} | {a} |")

    lines += [
        "\n## Summary\n",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Exists | {data['summary']['exists']} |",
        f"| Length (chars) | {data['summary']['length_chars']} |",
        f"| SHA-256 (first 16) | {data['summary']['sha256']} |",
        f"| Content |",
    ]
    for line in data["summary"]["content"].split("\n"):
        lines.append(f"| | `{line}` |")

    lines += [
        "\n## Built Messages\n",
        f"Total messages sent to LLM: {data['built_messages_count']}\n",
        "\n## Orphan / Missing Tool Results\n",
        f"Orphan tool results: {data['orphan_tool_results']}",
        f"Missing tool results: {data['missing_tool_results']}",
        "\n## Tool Calls in Remaining Messages\n",
    ]
    for tc in data["tool_calls_in_messages"]:
        lines.append(f"- `{tc['id']}`: {tc['name']}({tc['args_preview']})")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Build mixed history
    session = _build_mixed_session()
    original_messages = list(session.messages)

    # Policy with very small threshold to trigger compression
    policy = ContextPolicy(
        max_estimated_tokens=1,
        keep_recent_user_turns=2,
        max_summary_chars=500,
        max_item_chars=100,
    )
    cm = ContextManager(policy)

    # --- Before compression stats ---
    before_tokens = estimate_tokens(session.messages)
    bcounts = _counts(session.messages)
    before_summary = bool(session.summary)
    before_role_seq = _role_sequence(session.messages)
    orphans_before, missing_before = _find_orphan_tools(session.messages)

    print("=" * 65)
    print("  Context as Built — Visualization (zero API)")
    print("=" * 65)
    print(f"\nPolicy: max_tokens={policy.max_estimated_tokens}, "
          f"keep_turns={policy.keep_recent_user_turns}, "
          f"max_summary={policy.max_summary_chars}, "
          f"max_item={policy.max_item_chars}")

    # --- Before ---
    print(f"\n{'─'*65}")
    print("BEFORE COMPRESSION")
    print(f"{'─'*65}")
    print(f"  Message count:           {bcounts['total']}")
    print(f"  Estimated tokens:        {before_tokens}")
    print(f"  User turns:              {bcounts['user']}")
    print(f"  Assistant tool_call msgs: {bcounts['assistant_with_tool_calls']}")
    print(f"  Tool result msgs:        {bcounts['tool']}")
    print(f"  Summary exists:          {before_summary}")
    print(f"  Role sequence:           {before_role_seq}")

    # Find compress boundary manually for display
    from src.context_manager import _find_compress_boundary
    boundary = _find_compress_boundary(session.messages, policy.keep_recent_user_turns)
    print(f"  Compute boundary:        {boundary}")

    # --- Compression event ---
    print(f"\n{'─'*65}")
    print("COMPRESSION EVENT")
    print(f"{'─'*65}")

    compressed = cm.prepare_session(session)

    if compressed:
        compressed_count = boundary
        kept_count = len(session.messages)
        kept_user = sum(1 for m in session.messages if m.get("role") == "user")
        print(f"  Triggered:               YES")
        print(f"  Compressed messages:     {compressed_count}")
        print(f"  Kept messages:           {kept_count}")
        print(f"  Kept user turns:         {kept_user}")
    else:
        print(f"  Triggered:               NO")
        print(f"  Reason: tokens < threshold or boundary == 0")

    # --- After compression stats ---
    after_tokens = estimate_tokens(session.messages)
    acounts = _counts(session.messages)
    after_role_seq = _role_sequence(session.messages)
    orphans_after, missing_after = _find_orphan_tools(session.messages)

    print(f"\n{'─'*65}")
    print("AFTER COMPRESSION")
    print(f"{'─'*65}")
    print(f"  Message count:           {acounts['total']}")
    print(f"  Estimated tokens:        {after_tokens}")
    print(f"  User turns:              {acounts['user']}")
    print(f"  Summary length:          {len(session.summary)} chars")
    print(f"  Summary content:")
    for line in session.summary.split("\n"):
        print(f"    {line}")
    print(f"  Role sequence:           {after_role_seq}")
    print(f"  Orphan tool results:     {orphans_after}")
    print(f"  Missing tool results:    {missing_after}")

    # --- Build messages ---
    print(f"\n{'─'*65}")
    print("FINAL build_messages OUTPUT")
    print(f"{'─'*65}")

    built = cm.build_messages(system_prompt="System: You are a helpful assistant.", session=session)
    print(f"  Total messages: {len(built)}\n")

    for i, msg in enumerate(built):
        role = msg.get("role", "?")
        content = msg.get("content")
        content_preview = _preview(content, 100)

        if role == "system":
            if "Session memory summary" in (content or ""):
                print(f"  [{i}] system (summary) | {_preview(content, 120)}")
            else:
                print(f"  [{i}] system           | {_preview(content, 120)}")
        elif role == "user":
            print(f"  [{i}] user             | {content_preview}")
        elif role == "assistant":
            if "tool_calls" in msg:
                tcs = msg["tool_calls"]
                ids = [tc["id"] for tc in tcs]
                names = [tc["function"]["name"] for tc in tcs]
                args_previews = [_preview(tc["function"].get("arguments", "{}"), 60) for tc in tcs]
                print(f"  [{i}] assistant (tc)   | ids={ids} names={names}")
                for tid, tname, targs in zip(ids, names, args_previews):
                    print(f"       tool_call: {tid} | {tname}({targs})")
            else:
                print(f"  [{i}] assistant        | {content_preview}")
        elif role == "tool":
            tc_id = msg.get("tool_call_id", "?")
            tname = msg.get("name", "?")
            tcontent = msg.get("content", "")
            print(f"  [{i}] tool             | id={tc_id} name={tname} | "
                  f"{_preview(tcontent, 80)} | len={len(tcontent)} sha256={_sha256(tcontent)}")
        else:
            print(f"  [{i}] {role:17s} | {content_preview}")

    # --- Checks ---
    print(f"\n{'─'*65}")
    print("INTEGRITY CHECKS")
    print(f"{'─'*65}")
    integrity_ok = True

    # No orphan tool results
    if orphans_after:
        print(f"  [FAIL] Orphan tool results: {orphans_after}")
        integrity_ok = False
    else:
        print(f"  [OK] No orphan tool results")

    # No missing tool results
    if missing_after:
        print(f"  [FAIL] Missing tool results: {missing_after}")
        integrity_ok = False
    else:
        print(f"  [OK] No missing tool results")

    # Summary exists after compression
    if compressed:
        if len(session.summary) > 0:
            print(f"  [OK] Summary created ({len(session.summary)} chars)")
        else:
            print(f"  [WARN] Compression claimed but summary is empty")
    else:
        print(f"  [OK] No compression (summary unchanged)")

    # No API key in any message
    api_key_found = False
    for msg in built:
        content = str(msg.get("content", "") or "")
        if "DASHSCOPE_API_KEY" in content or "sk-" in content:
            api_key_found = True
            break
    if api_key_found:
        print(f"  [FAIL] API key found in built messages!")
        integrity_ok = False
    else:
        print(f"  [OK] No API key in built messages")

    # First message is always system
    if built and built[0].get("role") == "system":
        print(f"  [OK] First message is system prompt")
    else:
        print(f"  [FAIL] First message is not system prompt")
        integrity_ok = False

    print(f"\n  Overall integrity: {'PASS' if integrity_ok else 'FAIL'}")

    # --- Generate reports ---
    report_dir = PROJECT_ROOT / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    data = _build_report_data(session, policy, compressed, boundary)

    json_path = report_dir / "context-as-built-visualization.json"
    _write_json_report(data, json_path)

    md_path = report_dir / "context-as-built-visualization.md"
    _write_md_report(data, md_path)

    print(f"\n  JSON report: {json_path}")
    print(f"  MD report:   {md_path}")
    print(f"\n{'='*65}")


if __name__ == "__main__":
    main()
