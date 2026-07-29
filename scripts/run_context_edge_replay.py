"""Synthetic edge-case context replay — zero API.

Constructs a mixed history with all edge cases, runs through real ContextManager
with a small threshold, and verifies structural integrity.
"""

import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from src.context_manager import ContextManager, ContextPolicy, estimate_tokens
from src.session import Session


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _preview(text: str | None, max_len: int = 80) -> str:
    if text is None:
        return "None"
    s = str(text)
    if len(s) <= max_len:
        return s
    return s[:max_len] + "..."


def _check_structure(messages: list[dict]) -> dict:
    call_ids: set[str] = set()
    result_ids: set[str] = set()
    for m in messages:
        if m.get("role") == "assistant" and "tool_calls" in m:
            for tc in m["tool_calls"]:
                call_ids.add(tc["id"])
        if m.get("role") == "tool":
            result_ids.add(m.get("tool_call_id", ""))
    return {
        "orphan_tool_results": sorted(result_ids - call_ids),
        "missing_tool_results": sorted(call_ids - result_ids),
        "tool_call_count": len(call_ids),
        "tool_result_count": len(result_ids),
    }


def _role_sequence(msgs: list[dict]) -> str:
    seq = []
    for m in msgs:
        role = m.get("role", "?")
        if role == "assistant" and "tool_calls" in m:
            seq.append("assistant(tc)")
        else:
            seq.append(role)
    return " → ".join(seq)


def _build_edge_session() -> Session:
    """Build a message history covering all specified edge cases."""
    import json as _json
    msgs: list[dict] = []

    # Turns 1-20: Plain chat (English + Chinese + Unicode)
    chat_lines = [
        ("user", "Hello, how are you?"),
        ("assistant", "I am fine, thank you!"),
        ("user", "今天天气怎么样？"),
        ("assistant", "今天天气晴朗，气温28度。"),
        ("user", "What is the capital of France?"),
        ("assistant", "Paris."),
        ("user", "日本語を話せますか？"),
        ("assistant", "はい、少し話せます。"),
        ("user", "Python is great for data science."),
        ("assistant", "I agree! Pandas and NumPy are essential."),
        ("user", "我的名字是张三。"),
        ("assistant", "你好张三！"),
        ("user", "实际上请叫我李四。"),  # Fact correction
        ("assistant", "好的李四。"),
        ("user", "Remember the code: 42 is the answer."),
        ("assistant", "I will remember: 42 is the answer."),
        ("user", "Constraint: always respond in Chinese."),
        ("assistant", "好的，我将用中文回答。"),
        ("user", "Special chars: ñoño & 中文 & あいうえお"),
        ("assistant", "All special chars received: ñoño, 中文, あいうえお"),
        ("user", "Testing emoji: αβγ"),
        ("assistant", "Greek letters received: αβγ"),
    ]
    for role, content in chat_lines:
        msgs.append({"role": role, "content": content})

    # Turn 11-15: Tool calls (single + parallel + error + empty result + long result)
    # Single tool call
    msgs.append({"role": "user", "content": "Calculate 15 * 23"})
    msgs.append({
        "role": "assistant", "content": None,
        "tool_calls": [{
            "id": "tc_single", "type": "function",
            "function": {"name": "calculator", "arguments": '{"expression":"15*23"}'},
        }],
    })
    msgs.append({
        "role": "tool", "tool_call_id": "tc_single", "name": "calculator",
        "content": _json.dumps({"ok": True, "result": "345.0"}, ensure_ascii=False),
    })
    msgs.append({"role": "assistant", "content": "15 * 23 = 345"})

    # Parallel tool calls
    msgs.append({"role": "user", "content": "Calculate 100/5 and 2**8"})
    msgs.append({
        "role": "assistant", "content": None,
        "tool_calls": [
            {"id": "tc_par1", "type": "function", "function": {"name": "calculator", "arguments": '{"expression":"100/5"}'}},
            {"id": "tc_par2", "type": "function", "function": {"name": "calculator", "arguments": '{"expression":"2**8"}'}},
        ],
    })
    msgs.append({
        "role": "tool", "tool_call_id": "tc_par1", "name": "calculator",
        "content": _json.dumps({"ok": True, "result": "20.0"}, ensure_ascii=False),
    })
    msgs.append({
        "role": "tool", "tool_call_id": "tc_par2", "name": "calculator",
        "content": _json.dumps({"ok": True, "result": "256.0"}, ensure_ascii=False),
    })
    msgs.append({"role": "assistant", "content": "100/5=20, 2**8=256"})

    # Tool error result (JSON with ok=false)
    msgs.append({"role": "user", "content": "Run illegal expression"})
    msgs.append({
        "role": "assistant", "content": None,
        "tool_calls": [{
            "id": "tc_err", "type": "function",
            "function": {"name": "calculator", "arguments": '{"expression":"__import__"}'},
        }],
    })
    msgs.append({
        "role": "tool", "tool_call_id": "tc_err", "name": "calculator",
        "content": _json.dumps({"ok": False, "error_type": "ToolExecutionError", "message": "Illegal expression"}, ensure_ascii=False),
    })
    msgs.append({"role": "assistant", "content": "Illegal expression. Cannot compute."})

    # Tool success but empty result
    msgs.append({"role": "user", "content": "Search with empty result"})
    msgs.append({
        "role": "assistant", "content": None,
        "tool_calls": [{
            "id": "tc_empty", "type": "function",
            "function": {"name": "search", "arguments": '{"keywords":"__nonexistent__"}'},
        }],
    })
    msgs.append({
        "role": "tool", "tool_call_id": "tc_empty", "name": "search",
        "content": _json.dumps({"ok": True, "result": "No results found."}, ensure_ascii=False),
    })
    msgs.append({"role": "assistant", "content": "No results found for the query."})

    # Extra long tool result
    long_result = "x" * 2000
    msgs.append({"role": "user", "content": "Read very long document"})
    msgs.append({
        "role": "assistant", "content": None,
        "tool_calls": [{
            "id": "tc_long", "type": "function",
            "function": {"name": "read_docs", "arguments": '{"filename":"long.md"}'},
        }],
    })
    msgs.append({
        "role": "tool", "tool_call_id": "tc_long", "name": "read_docs",
        "content": _json.dumps({"ok": True, "result": long_result}, ensure_ascii=False),
    })
    msgs.append({"role": "assistant", "content": "Long document read."})

    # Assistant content = None (no tool_calls either — degenerate case)
    msgs.append({"role": "user", "content": "Say something"})
    msgs.append({"role": "assistant", "content": None})

    # Incomplete turn — no final answer
    msgs.append({"role": "user", "content": "Search for tomorrow's weather"})
    msgs.append({
        "role": "assistant", "content": None,
        "tool_calls": [{
            "id": "tc_incomplete", "type": "function",
            "function": {"name": "search", "arguments": '{"keywords":"tomorrow weather"}'},
        }],
    })
    # NOTE: No tool result, no final answer

    session = Session(user_id="edge-test", session_id="edge-replay")
    session.messages = msgs
    return session


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Synthetic edge case context replay (zero API)")
    parser.add_argument("--max-estimated-tokens", type=int, default=1,
                        help="Threshold to force compression (default: 1)")
    parser.add_argument("--keep-recent-user-turns", type=int, default=3,
                        help="Number of user turns to keep (default: 3)")
    parser.add_argument("--max-summary-chars", type=int, default=800,
                        help="Max summary chars (default: 800)")
    parser.add_argument("--max-item-chars", type=int, default=100,
                        help="Max item chars (default: 100)")
    parser.add_argument("--continue-with-real-llm", action="store_true",
                        help="After replay, send one question to real Qwen to verify structure usability")
    args = parser.parse_args()

    print("=" * 65)
    print("  Context Edge Case Replay (zero API)")
    print("=" * 65)

    policy = ContextPolicy(
        max_estimated_tokens=args.max_estimated_tokens,
        keep_recent_user_turns=args.keep_recent_user_turns,
        max_summary_chars=args.max_summary_chars,
        max_item_chars=args.max_item_chars,
    )
    cm = ContextManager(policy)
    session = _build_edge_session()

    # ── Before ──
    bcount = len(session.messages)
    btokens = estimate_tokens(session.messages)
    bseq = _role_sequence(session.messages)
    bstruct = _check_structure(session.messages)

    print(f"\n{'─'*65}")
    print("BEFORE COMPRESSION")
    print(f"{'─'*65}")
    print(f"  Messages:        {bcount}")
    print(f"  Estimated tokens: {btokens}")
    print(f"  Role sequence:    {bseq}")
    print(f"  Tool calls:       {bstruct['tool_call_count']}")
    print(f"  Tool results:     {bstruct['tool_result_count']}")
    print(f"  Orphans:          {bstruct['orphan_tool_results']}")
    print(f"  Missing results:  {bstruct['missing_tool_results']}")

    # ── Compress ──
    compressed = cm.prepare_session(session)

    # ── After ──
    acount = len(session.messages)
    atokens = estimate_tokens(session.messages)
    aseq = _role_sequence(session.messages)
    astruct = _check_structure(session.messages)

    msg_diff = bcount - acount
    ratio = atokens / btokens if btokens > 0 else 1.0

    print(f"\n{'─'*65}")
    print(f"COMPRESSION: {'YES' if compressed else 'NO'}")
    print(f"{'─'*65}")
    print(f"  Compressed msgs: {msg_diff}")
    print(f"  Retained msgs:   {acount}")
    print(f"  Tokens:          {btokens} -> {atokens} ({ratio*100:.1f}%)")
    print(f"  Summary chars:   {len(session.summary)}")
    print(f"  Summary content:")
    for line in session.summary.split("\n"):
        print(f"    {line}")

    print(f"\n{'─'*65}")
    print("AFTER COMPRESSION")
    print(f"{'─'*65}")
    print(f"  Messages:        {acount}")
    print(f"  Estimated tokens: {atokens}")
    print(f"  Role sequence:    {aseq}")
    print(f"  Tool calls:       {astruct['tool_call_count']}")
    print(f"  Tool results:     {astruct['tool_result_count']}")
    print(f"  Orphans:          {astruct['orphan_tool_results']}")
    print(f"  Missing results:  {astruct['missing_tool_results']}")

    # ── Per-message detail ──
    print(f"\n{'─'*65}")
    print("RETAINED MESSAGES")
    print(f"{'─'*65}")
    for i, m in enumerate(session.messages):
        role = m.get("role", "?")
        if role == "assistant" and "tool_calls" in m:
            tcs = m["tool_calls"]
            names = [f"{tc['id']}:{tc['function']['name']}" for tc in tcs]
            print(f"  [{i}] assistant(tc)  | {', '.join(names)}")
        elif role == "tool":
            content = m.get("content", "") or ""
            print(f"  [{i}] tool           | id={m.get('tool_call_id','?')} "
                  f"name={m.get('name','?')} | len={len(content)} sha256={_sha256(content)}")
        else:
            print(f"  [{i}] {role:17s} | {_preview(m.get('content'), 80)}")

    # ── Integrity checks ──
    print(f"\n{'─'*65}")
    print("INTEGRITY CHECKS")
    print(f"{'─'*65}")
    integrity_ok = True
    if astruct["orphan_tool_results"]:
        print(f"  [FAIL] Orphan tool results: {astruct['orphan_tool_results']}")
        integrity_ok = False
    else:
        print(f"  [OK] No orphan tool results")
    if astruct["missing_tool_results"]:
        # The incomplete turn (tc_incomplete) will show here if kept
        if "tc_incomplete" in astruct["missing_tool_results"]:
            print(f"  [OK] Expected missing result tc_incomplete (incomplete turn kept)")
        else:
            print(f"  [FAIL] Missing tool results: {astruct['missing_tool_results']}")
            integrity_ok = False
    else:
        print(f"  [OK] No missing tool results")
    if compressed and len(session.summary) > 0:
        print(f"  [OK] Summary created ({len(session.summary)} chars)")
    print(f"  [OK] First retained is user" if session.messages and session.messages[0].get("role") == "user" else "  [WARN] First retained not user")
    print(f"\n  Overall: {'PASS' if integrity_ok else 'FAIL'}")

    # ── Reports ──
    report_dir = _PROJECT_ROOT / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "generated_at": datetime.now().isoformat(),
        "policy": {
            "max_estimated_tokens": policy.max_estimated_tokens,
            "keep_recent_user_turns": policy.keep_recent_user_turns,
            "max_summary_chars": policy.max_summary_chars,
            "max_item_chars": policy.max_item_chars,
        },
        "before": {
            "message_count": bcount,
            "estimated_tokens": btokens,
            "role_sequence": bseq,
            "tool_call_count": bstruct["tool_call_count"],
            "tool_result_count": bstruct["tool_result_count"],
            "orphan_tool_results": bstruct["orphan_tool_results"],
            "missing_tool_results": bstruct["missing_tool_results"],
        },
        "compression": {
            "triggered": compressed,
            "messages_compressed": msg_diff if compressed else 0,
            "messages_retained": acount,
            "tokens_before": btokens,
            "tokens_after": atokens,
            "compression_ratio": round(ratio, 4),
            "summary_chars": len(session.summary),
        },
        "after": {
            "message_count": acount,
            "estimated_tokens": atokens,
            "role_sequence": aseq,
            "tool_call_count": astruct["tool_call_count"],
            "tool_result_count": astruct["tool_result_count"],
            "orphan_tool_results": astruct["orphan_tool_results"],
            "missing_tool_results": astruct["missing_tool_results"],
        },
        "integrity": {
            "passed": integrity_ok,
            "orphan_tool_result_count": len(astruct["orphan_tool_results"]),
            "missing_tool_result_count": len(astruct["missing_tool_results"]),
        },
    }

    report_json_path = report_dir / "context-edge-replay.json"
    report_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    report_md_lines = [
        "# Context Edge Case Replay Report\n",
        f"Generated: {datetime.now().isoformat()}\n",
        f"Integrity: {'PASS' if integrity_ok else 'FAIL'}\n",
        "\n## Policy\n",
        f"| max_estimated_tokens | {policy.max_estimated_tokens} |",
        f"| keep_recent_user_turns | {policy.keep_recent_user_turns} |",
        "\n## Before\n",
        f"| Messages | {bcount} |",
        f"| Tokens | {btokens} |",
        f"| Tool calls | {bstruct['tool_call_count']} |",
        f"| Tool results | {bstruct['tool_result_count']} |",
        "\n## Compression\n",
        f"| Triggered | {compressed} |",
        f"| Compressed msgs | {msg_diff if compressed else 0} |",
        f"| Retained msgs | {acount} |",
        f"| Tokens | {btokens} → {atokens} ({ratio*100:.1f}%) |",
        f"| Summary chars | {len(session.summary)} |",
        "\n## After\n",
        f"| Messages | {acount} |",
        f"| Tokens | {atokens} |",
        f"| Orphan tool results | {astruct['orphan_tool_results']} |",
        f"| Missing tool results | {astruct['missing_tool_results']} |",
    ]
    report_md_path = report_dir / "context-edge-replay.md"
    report_md_path.write_text("\n".join(report_md_lines) + "\n", encoding="utf-8")

    print(f"\n  JSON report: {report_json_path}")
    print(f"  MD report:   {report_md_path}")

    # ── Optional real LLM continuation ──
    if args.continue_with_real_llm:
        if not os.environ.get("DASHSCOPE_API_KEY"):
            print("\n  --continue-with-real-llm: DASHSCOPE_API_KEY not set, skipped")
        else:
            print(f"\n{'─'*65}")
            print("  CONTINUE WITH REAL LLM")
            print(f"{'─'*65}")
            from dotenv import load_dotenv
            load_dotenv()
            from src.agent import AgentRuntime
            from src.bootstrap import build_default_registry
            from src.config import load_llm_settings
            from src.prompt import SYSTEM_PROMPT
            from src.qwen_client import OpenAICompatibleLLMClient
            from src.sqlite_session import SQLiteSessionStore
            from src.recording_llm_client import RecordingLLMClient

            settings = load_llm_settings()
            raw = OpenAICompatibleLLMClient(settings=settings)
            recorder = RecordingLLMClient(raw)
            registry = build_default_registry()
            store = SQLiteSessionStore(db_path=":memory:")

            runtime = AgentRuntime(
                llm_client=recorder,
                tool_registry=registry,
                session_store=store,
                system_prompt=SYSTEM_PROMPT,
                max_steps=5,
                context_manager=cm,
            )

            user_id = "edge-replay"
            session_id = "edge-continue"
            store.get_or_create(user_id, session_id)

            # Inject the compressed messages into the new session
            s = store.get_or_create(user_id, session_id)
            s.messages = list(session.messages)
            s.summary = session.summary
            store.save(s)

            probe_input = "What is the capital of France?"
            print(f"\n  Sending: {probe_input}")
            try:
                result = runtime.run(user_id=user_id, session_id=session_id, user_input=probe_input)
                print(f"  Answer: {_preview(result.answer, 200)}")
                print(f"  [OK] Real LLM continued from compressed context")
                report["real_llm_continuation"] = {
                    "input": probe_input,
                    "answer_preview": _preview(result.answer, 200),
                    "steps_used": result.steps_used,
                    "llm_calls": recorder.total_calls,
                }
            except Exception as e:
                print(f"  [FAIL] Real LLM continuation failed: {e}")
                report["real_llm_continuation"] = {"error": str(e)}

            report_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'='*65}")


if __name__ == "__main__":
    main()
