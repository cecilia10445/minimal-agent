"""Context baseline runner — runs fixed 20 chat + 10 tool turn scenario against real Qwen.

Records per-turn context snapshots, compression events, LLM call metadata,
and semantic probe results. Generates full report in reports/context-baseline-v1/.

Usage:
    $env:RUN_REAL_LLM_TESTS="1"
    python scripts/run_context_baseline.py --scenario scenarios/context-baseline-v1.json
    python scripts/run_context_baseline.py --dry-run
"""

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

_RUN_REAL = os.environ.get("RUN_REAL_LLM_TESTS") == "1"
_HAS_KEY = bool(os.environ.get("DASHSCOPE_API_KEY"))


def _check_env():
    global _HAS_KEY
    if not _RUN_REAL:
        print("SKIPPED: RUN_REAL_LLM_TESTS not set to 1")
        return False
    if not _HAS_KEY:
        # Try loading from .env
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except Exception:
            pass
        _HAS_KEY = bool(os.environ.get("DASHSCOPE_API_KEY"))
    if not _HAS_KEY:
        print("SKIPPED: DASHSCOPE_API_KEY not configured")
        return False
    return True


def _sha256(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _preview(text: str, max_len: int = 80) -> str:
    if not text:
        return ""
    s = str(text)
    if len(s) <= max_len:
        return s
    return s[:max_len] + "..."


def _check_structure(messages: list[dict]) -> dict:
    """Validate tool call <-> tool result correspondence."""
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


def _load_scenario(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _snapshot(session: Any, context_manager: Any, summary_field: str = "summary") -> dict:
    """Capture context snapshot from a session."""
    from src.context_manager import estimate_tokens
    msgs = session.messages
    tokens = estimate_tokens(msgs)
    summary = getattr(session, summary_field, "")
    structure = _check_structure(msgs)
    return {
        "message_count": len(msgs),
        "estimated_tokens": tokens,
        "summary_chars": len(summary),
        "summary_content": summary[-200:] if summary else "",
        **structure,
    }


def _write_jsonl(path: Path, records: list[dict]):
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _check_probe(probe_input: str, answer: str, checks: dict) -> dict:
    probe_checks = checks.get(probe_input, {})
    must_contain = probe_checks.get("must_contain", [])
    must_not_contain = probe_checks.get("must_not_contain", [])
    results = {}
    all_ok = True
    for kw in must_contain:
        found = kw.lower() in answer.lower()
        results[f"must_contain:{kw}"] = found
        if not found:
            all_ok = False
    for kw in must_not_contain:
        found = kw.lower() in answer.lower()
        results[f"must_not_contain:{kw}"] = not found
        if found:
            all_ok = False
    return {"passed": all_ok, "details": results, "answer_preview": _preview(answer, 200)}


def main():
    parser = argparse.ArgumentParser(description="Run context baseline scenario")
    parser.add_argument("--scenario", type=str, default=None,
                        help="Path to scenario JSON (default: scenarios/context-baseline-v1.json)")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without calling API")
    parser.add_argument("--max-estimated-tokens", type=int, default=None,
                        help="Override max_estimated_tokens (default: 1800 for test acceleration)")
    parser.add_argument("--keep-recent-user-turns", type=int, default=None,
                        help="Override keep_recent_user_turns (default: 4)")
    parser.add_argument("--max-summary-chars", type=int, default=None,
                        help="Override max_summary_chars (default: 3000)")
    parser.add_argument("--max-item-chars", type=int, default=None,
                        help="Override max_item_chars (default: 300)")
    parser.add_argument("--db-path", type=str, default=None,
                         help="Override DB path (default: <report-dir>/context-baseline.db)")
    parser.add_argument("--summary-mode", type=str, default=None,
                        choices=["deterministic", "hybrid"],
                        help="Context summary mode (default: deterministic)")
    parser.add_argument("--report-dir", type=str, default=None,
                        help="Override report directory (default: reports/context-<summary-mode>)")
    args = parser.parse_args()

    # Determine summary mode
    summary_mode = args.summary_mode or "deterministic"

    # Determine scenario path
    scenario_path = Path(args.scenario) if args.scenario else (
        _PROJECT_ROOT / "scenarios" / "context-baseline-v1.json"
    )
    if not scenario_path.exists():
        print(f"Scenario not found: {scenario_path}")
        sys.exit(1)

    scenario = _load_scenario(scenario_path)

    report_dir = Path(args.report_dir) if args.report_dir else (
        _PROJECT_ROOT / "reports" / f"context-{summary_mode}"
    )
    report_dir.mkdir(parents=True, exist_ok=True)

    db_path = args.db_path or str(report_dir / "context-baseline.db")

    # Policy: use CLI overrides or test acceleration defaults
    max_tokens = args.max_estimated_tokens or 1800
    keep_turns = args.keep_recent_user_turns or 4
    max_summary = args.max_summary_chars or 3000
    max_item = args.max_item_chars or 300

    is_accelerated = max_tokens < 6000

    print("=" * 65)
    print("  Context Baseline Runner — Round 10B")
    print("=" * 65)
    print(f"  Scenario:       {scenario_path}")
    print(f"  user_id:        {scenario.get('user_id', 'user-c')}")
    print(f"  session_id:     {scenario.get('session_id', 'context-baseline-v1')}")
    print(f"  db_path:        {db_path}")
    print(f"  report_dir:     {report_dir}")
    print(f"  max_tokens:     {max_tokens}")
    print(f"  keep_turns:     {keep_turns}")
    print(f"  max_summary:    {max_summary}")
    print(f"  max_item:       {max_item}")
    print(f"  summary_mode:   {summary_mode}")
    if is_accelerated:
        print(f"\n  ** NOTICE: Using test acceleration threshold (max_tokens=1800)")
        print(f"     Production default is max_tokens=6000. This is NOT the production value.")
        print(f"     The lower threshold ensures compression triggers within 30 turns.")
    print()

    chat_turns = scenario.get("chat_turns", [])
    tool_turns = scenario.get("tool_turns", [])
    semantic_probes = scenario.get("semantic_probes", [])
    probe_checks = scenario.get("semantic_probe_checks", {})
    isolation_questions = scenario.get("isolation_questions", [])
    isolation_forbidden = scenario.get("isolation_forbidden", [])

    print(f"  Chat turns:     {len(chat_turns)}")
    print(f"  Tool turns:     {len(tool_turns)}")
    print(f"  Semantic probes: {len(semantic_probes)}")
    print(f"  Isolation checks: {len(isolation_questions)}")

    if args.dry_run:
        print("\n  Dry run — no API calls.")
        return

    if not _check_env():
        sys.exit(0)

    # ── Build real runtime ──
    from dotenv import load_dotenv
    load_dotenv()

    from src.agent import AgentRuntime
    from src.bootstrap import build_default_registry
    from src.config import load_context_policy, load_llm_settings
    from src.context_manager import ContextManager, ContextPolicy
    from src.context_summarizer import QwenSemanticSummarizer
    from src.prompt import SYSTEM_PROMPT
    from src.qwen_client import OpenAICompatibleLLMClient
    from src.sqlite_session import SQLiteSessionStore
    from src.recording_llm_client import RecordingLLMClient

    settings = load_llm_settings()
    raw_client = OpenAICompatibleLLMClient(settings=settings)
    llm_client = RecordingLLMClient(raw_client)
    registry = build_default_registry()
    store = SQLiteSessionStore(db_path=db_path)

    context_policy = ContextPolicy(
        max_estimated_tokens=max_tokens,
        keep_recent_user_turns=keep_turns,
        max_summary_chars=max_summary,
        max_item_chars=max_item,
    )
    summarizer = None
    if summary_mode == "hybrid":
        summary_model = os.environ.get("AGENT_CONTEXT_SUMMARY_MODEL", "") or settings.model
        summarizer = QwenSemanticSummarizer(settings=settings, summary_model=summary_model)
    cm = ContextManager(
        context_policy,
        summarizer=summarizer,
        summary_mode=summary_mode,
    )

    runtime = AgentRuntime(
        llm_client=llm_client,
        tool_registry=registry,
        session_store=store,
        system_prompt=SYSTEM_PROMPT,
        max_steps=8,
        context_manager=cm,
    )

    user_id = scenario.get("user_id", "user-c")
    session_id = scenario.get("session_id", "context-baseline-v1")

    # ── Run metadata ──
    run_metadata = {
        "scenario_id": scenario.get("id"),
        "user_id": user_id,
        "session_id": session_id,
        "db_path": db_path,
        "started_at": datetime.now().isoformat(),
        "context_policy": {
            "max_estimated_tokens": max_tokens,
            "keep_recent_user_turns": keep_turns,
            "max_summary_chars": max_summary,
            "max_item_chars": max_item,
            "is_accelerated": is_accelerated,
            "production_default_max_tokens": 6000,
        },
    }

    # ── Data collectors ──
    transcript: list[dict] = []
    context_snapshots: list[dict] = []
    compression_events: list[dict] = []
    all_turns = chat_turns + tool_turns
    event_counter = 0

    # ── Run all turns ──
    for turn_index, user_input in enumerate(all_turns):
        category = "chat" if turn_index < len(chat_turns) else "tool"

        # Snapshot BEFORE run (for transcript logging only)
        session = store.get_or_create(user_id, session_id)
        snap_before = _snapshot(session, cm)
        snap_before["category"] = category
        snap_before["turn_index"] = turn_index

        # Clear so we can detect compression from this turn
        cm.last_compression_event = None

        # Run
        step_start = time.monotonic()
        try:
            result = runtime.run(user_id=user_id, session_id=session_id, user_input=user_input)
            step_latency = (time.monotonic() - step_start) * 1000
            success = True
            error = None
        except Exception as e:
            step_latency = (time.monotonic() - step_start) * 1000
            success = False
            error = str(e)
            session = store.get_or_create(user_id, session_id)
            result = None

        # Snapshot AFTER run (includes new user + LLM messages)
        session = store.get_or_create(user_id, session_id)
        snap_after = _snapshot(session, cm)
        snap_after["category"] = category
        snap_after["turn_index"] = turn_index

        # Detect compression via last_compression_event (set by prepare_session)
        comp = cm.last_compression_event
        if comp is not None:
            event_counter += 1
            ce = {
                "event_index": event_counter,
                "turn_index": turn_index,
                "threshold": max_tokens,
                "tokens_before": comp["estimated_tokens_before"],
                "tokens_after": comp["estimated_tokens_after"],
                "messages_before": snap_before["message_count"],
                "messages_compressed": comp["messages_compressed"],
                "messages_retained": snap_before["message_count"] - comp["messages_compressed"],
                "summary_chars_before": comp["summary_chars_before"],
                "summary_chars_after": comp["summary_chars_after"],
                "compression_ratio": round(
                    comp["estimated_tokens_after"] / comp["estimated_tokens_before"], 4
                ),
                "token_reduction_percent": round(
                    (1 - comp["estimated_tokens_after"] / comp["estimated_tokens_before"]) * 100, 1
                ),
                "summary_mode": comp["summary_mode"],
                "semantic_summary_attempted": comp["semantic_summary_attempted"],
                "semantic_summary_succeeded": comp.get("semantic_summary_succeeded", False),
                "fallback_used": comp.get("fallback_used", False),
                "semantic_summary_latency_ms": comp.get("semantic_summary_latency_ms", 0),
            }
            compression_events.append(ce)

        # Build transcript entry
        tools_called = []
        if result:
            tools_called = [
                t["tool_name"] for t in result.traces
                if t.get("event_type") == "tool_call"
            ]

        compress_detected = comp is not None
        compressed_msg_count = comp["messages_compressed"] if comp else 0
        transcript_entry = {
            "turn_index": turn_index,
            "category": category,
            "user_input": user_input,
            "tools_called": list(set(tools_called)),
            "answer": result.answer if result else "",
            "steps_used": result.steps_used if result else 0,
            "success": success,
            "error": error,
            "latency_ms": round(step_latency, 1),
            "message_count_before_run": snap_before["message_count"],
            "message_count_after_run": snap_after["message_count"],
            "estimated_tokens_at_run_start": snap_before["estimated_tokens"],
            "estimated_tokens_after_run": snap_after["estimated_tokens"],
            "compression_detected": compress_detected,
            "compressed_message_count": compressed_msg_count,
            "summary_chars_before": snap_before["summary_chars"],
            "summary_chars_after": snap_after["summary_chars"],
            "orphan_tool_results": snap_after.get("orphan_tool_results", []),
            "missing_tool_results": snap_after.get("missing_tool_results", []),
        }
        transcript.append(transcript_entry)

        # Brief terminal output
        summary_indicator = "YES" if snap_after["summary_chars"] > 0 else "no"
        compressed_ind = "yes" if compress_detected else "no "
        if comp:
            extra_info = ""
            if comp.get("semantic_summary_attempted"):
                extra_info = " sem" if comp.get("semantic_summary_succeeded") else " sem-FAIL"
        tools_str = ",".join(tools_called) if tools_called else "-"
        print(f"  Turn {turn_index+1:2d}/{len(all_turns)} | {category:4s} | {tools_str:25s} | "
              f"msgs={snap_after['message_count']:3d} | tok={snap_after['estimated_tokens']:5d} | "
              f"sum={summary_indicator:3s} | cmp={compressed_ind}")

        if compress_detected:
            ce = compression_events[-1]
            reduction_str = f"{ce['token_reduction_percent']:+.1f}%"
            sem_info = ""
            if ce.get("semantic_summary_attempted"):
                sem_info = " [semantic]" if ce.get("semantic_summary_succeeded") else " [sem-FALLBACK]"
            print(f"  >>> COMPRESSION #{ce['event_index']}: "
                  f"tokens {ce['tokens_before']} -> {ce['tokens_after']} | "
                  f"{reduction_str}{sem_info}")

    print()

    # ── Semantic Probes ──
    probe_results: list[dict] = []
    for probe_input in semantic_probes:
        step_start = time.monotonic()
        try:
            result = runtime.run(user_id=user_id, session_id=session_id, user_input=probe_input)
            latency = (time.monotonic() - step_start) * 1000
        except Exception as e:
            latency = (time.monotonic() - step_start) * 1000
            probe_results.append({
                "probe": probe_input,
                "error": str(e),
                "passed": False,
                "details": {},
                "answer_preview": "",
            })
            continue

        check_result = _check_probe(probe_input, result.answer, probe_checks)
        check_result["probe"] = probe_input
        check_result["latency_ms"] = round(latency, 1)
        probe_results.append(check_result)

        icon = "PASS" if check_result["passed"] else "FAIL"
        print(f"  Probe '{_preview(probe_input, 60)}': {icon}")

    # ── Isolation Checks ──
    isolation_results: list[dict] = []

    # Same user, different session
    from src.session import SessionStore as MemorySessionStore
    iso_store = SQLiteSessionStore(db_path=db_path)
    iso_runtime = AgentRuntime(
        llm_client=RecordingLLMClient(OpenAICompatibleLLMClient(settings=settings)),
        tool_registry=build_default_registry(),
        session_store=iso_store,
        system_prompt=SYSTEM_PROMPT,
        max_steps=5,
        context_manager=ContextManager(context_policy),
    )

    for i, iso_q in enumerate(isolation_questions):
        # Same user diff session
        iso_sid = "context-isolation-check"
        try:
            r = iso_runtime.run(user_id=user_id, session_id=iso_sid, user_input=iso_q)
            answer = r.answer
        except Exception as e:
            answer = f"ERROR: {e}"
        leaked = [k for k in isolation_forbidden if k.lower() in answer.lower()]
        isolation_results.append({
            "check_type": "same_user_diff_session",
            "user_id": user_id,
            "session_id": iso_sid,
            "question": iso_q,
            "leaked_keywords": leaked,
            "leak_count": len(leaked),
        })
        if leaked:
            print(f"  [ISOLATION] SAME USER diff session LEAK: {leaked}")

        # Different user same session ID
        diff_user = "user-d"
        try:
            r = iso_runtime.run(user_id=diff_user, session_id=session_id, user_input=iso_q)
            answer = r.answer
        except Exception as e:
            answer = f"ERROR: {e}"
        leaked = [k for k in isolation_forbidden if k.lower() in answer.lower()]
        isolation_results.append({
            "check_type": "diff_user_same_session",
            "user_id": diff_user,
            "session_id": session_id,
            "question": iso_q,
            "leaked_keywords": leaked,
            "leak_count": len(leaked),
        })
        if leaked:
            print(f"  [ISOLATION] DIFF USER LEAK: {leaked}")

    cross_session_leak = sum(r["leak_count"] for r in isolation_results if r["check_type"] == "same_user_diff_session")
    cross_user_leak = sum(r["leak_count"] for r in isolation_results if r["check_type"] == "diff_user_same_session")

    # ── Metrics ──
    compression_count = len(compression_events)
    if compression_events:
        tokens_before_total = sum(e["tokens_before"] for e in compression_events)
        tokens_after_total = sum(e["tokens_after"] for e in compression_events)
        avg_ratio = sum(e["compression_ratio"] for e in compression_events) / compression_count
        reductions = [e["token_reduction_percent"] for e in compression_events]
        max_reduction = max(reductions)
        min_reduction = min(reductions)
        avg_reduction = sum(reductions) / len(reductions)
    else:
        tokens_before_total = 0
        tokens_after_total = 0
        avg_ratio = 0
        max_reduction = 0
        min_reduction = 0
        avg_reduction = 0

    # Structural integrity (from transcript snapshots, not compression events)
    orphan_total = sum(len(t.get("orphan_tool_results", [])) for t in transcript)
    missing_total = sum(len(t.get("missing_tool_results", [])) for t in transcript)

    # Semantic probes
    probe_passed = sum(1 for p in probe_results if p.get("passed"))
    probe_total = len(probe_results)

    # Hybrid overhead
    semantic_call_count = sum(1 for e in compression_events if e.get("semantic_summary_attempted"))
    semantic_success_count = sum(1 for e in compression_events if e.get("semantic_summary_succeeded"))
    semantic_fallback_count = sum(1 for e in compression_events if e.get("fallback_used"))
    semantic_latency_total = sum(e.get("semantic_summary_latency_ms", 0) for e in compression_events)

    # Todo state
    session_final = store.get(user_id, session_id)
    todo_state_correct = False
    todo_tool_was_called = False
    if session_final:
        for t in session_final.traces:
            if t.get("tool_name") == "todo_list":
                todo_tool_was_called = True
                break

    metrics = {
        "compression": {
            "compression_event_count": compression_count,
            "tokens_before_total": tokens_before_total,
            "tokens_after_total": tokens_after_total,
            "average_compression_ratio": round(avg_ratio, 4),
            "average_token_reduction_percent": round(avg_reduction, 1),
            "maximum_token_reduction_percent": round(max_reduction, 1),
            "minimum_token_reduction_percent": round(min_reduction, 1),
        },
        "structure": {
            "orphan_tool_result_count": orphan_total,
            "missing_tool_result_count": missing_total,
        },
        "semantic_probes": {
            "core_fact_recall_correct": probe_passed,
            "core_fact_recall_total": probe_total,
            "core_fact_recall_rate": round(probe_passed / probe_total, 3) if probe_total > 0 else 0,
        },
        "isolation": {
            "cross_session_leak_count": cross_session_leak,
            "cross_user_leak_count": cross_user_leak,
        },
        "todo": {
            "todo_state_correct": todo_state_correct,
            "todo_tool_was_called": todo_tool_was_called,
        },
        "overhead": {
            "real_llm_call_count": llm_client.total_calls,
            "answer_chars_total": sum(len(t.get("answer", "")) for t in transcript),
            "total_latency_ms": sum(t.get("latency_ms", 0) for t in transcript),
            "compression_api_call_count": 0,
            "semantic_summary_call_count": semantic_call_count,
            "semantic_summary_success_count": semantic_success_count,
            "semantic_summary_fallback_count": semantic_fallback_count,
            "semantic_summary_latency_ms_total": round(semantic_latency_total, 1),
        },
    }

    # ── Overall status ──
    status = "passed"
    notes = []
    if compression_count == 0:
        status = "inconclusive"
        notes.append("No compression triggered")
    if orphan_total > 0 or missing_total > 0:
        status = "failed"
        notes.append(f"Structure errors: orphan={orphan_total}, missing={missing_total}")
    if metrics["structure"]["missing_tool_result_count"] > 0:
        status = "failed"
        notes.append("Missing tool results detected")
    # Check if probe questions were asked and answered
    if probe_total > 0 and probe_passed < probe_total:
        status = "failed"
        notes.append(f"Semantic probe recall: {probe_passed}/{probe_total}")
    if cross_session_leak > 0 or cross_user_leak > 0:
        status = "failed"
        notes.append("Session/user isolation leak detected")

    run_metadata["finished_at"] = datetime.now().isoformat()
    run_metadata["status"] = status
    run_metadata["notes"] = notes

    # ── Write reports ──
    run_metadata_path = report_dir / "run-metadata.json"
    run_metadata_path.write_text(json.dumps(run_metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    transcript_path = report_dir / "transcript.jsonl"
    _write_jsonl(transcript_path, transcript)

    # Transcript MD
    md_lines = [
        "# Context Baseline Transcript\n",
        f"Scenario: {scenario.get('id')} | user: {user_id} | session: {session_id}\n",
        f"Policy: max_tokens={max_tokens}, keep_turns={keep_turns}\n",
        f"**NOTICE**: {'Test acceleration threshold' if is_accelerated else 'Production default'}\n",
        "\n| Turn | Category | User Input | Tools | Answer | Tokens | Summary | Compressed |",
        "|------|----------|------------|-------|--------|--------|---------|------------|",
    ]
    for t in transcript:
        tools_str = ", ".join(t.get("tools_called", [])) or "-"
        sum_str = "yes" if t["summary_chars_after"] > 0 else "no"
        cmp_str = "yes" if t["compressed_message_count"] > 0 else "no"
        md_lines.append(
            f"| {t['turn_index']+1} | {t['category']} | {_preview(t['user_input'], 50)} | "
            f"{tools_str} | {_preview(t['answer'], 80)} | {t['estimated_tokens_after_run']} | "
            f"{sum_str} | {cmp_str} |"
        )
    transcript_md_path = report_dir / "transcript.md"
    transcript_md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    # LLM calls
    llm_calls_path = report_dir / "llm-calls.jsonl"
    _write_jsonl(llm_calls_path, llm_client.records)

    # Context snapshots
    snapshots_path = report_dir / "context-snapshots.jsonl"
    # Snapshots were discrete; collect them
    all_snaps = []
    for t in transcript:
        all_snaps.append({
            "turn_index": t["turn_index"],
            "before": {
                "message_count": t["message_count_before_run"],
                "estimated_tokens": t["estimated_tokens_at_run_start"],
                "summary_chars": t["summary_chars_before"],
            },
            "after": {
                "message_count": t["message_count_after_run"],
                "estimated_tokens": t["estimated_tokens_after_run"],
                "summary_chars": t["summary_chars_after"],
            },
        })
    _write_jsonl(snapshots_path, all_snaps)

    # Compression events
    comp_path = report_dir / "compression-events.jsonl"
    _write_jsonl(comp_path, compression_events)

    # Semantic probes
    probes_path = report_dir / "semantic-probes.json"
    probes_path.write_text(json.dumps(probe_results, ensure_ascii=False, indent=2), encoding="utf-8")

    # Isolation results
    isolation_path = report_dir / "isolation-results.json"
    isolation_path.write_text(json.dumps(isolation_results, ensure_ascii=False, indent=2), encoding="utf-8")

    # Metrics
    metrics_path = report_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    # Report MD — all files UTF-8, no encoding artifacts
    report_lines = [
        "# Context Baseline Report\n",
        f"Generated: {datetime.now().isoformat()}\n",
        f"Status: **{status.upper()}**\n",
    ]
    if notes:
        for n in notes:
            report_lines.append(f"- {n}")
    report_lines += [
        "\n## Run Metadata\n",
        f"| Field | Value |",
        f"|---|---|",
        f"| user_id | {user_id} |",
        f"| session_id | {session_id} |",
        f"| db_path | {db_path} |",
        f"| max_estimated_tokens | {max_tokens} |",
        f"| keep_recent_user_turns | {keep_turns} |",
        f"| is_accelerated threshold | {is_accelerated} |",
        f"| production default max_tokens | 6000 |",
        "\n## Compression\n",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Compression events | {compression_count} |",
        f"| Tokens before (total) | {tokens_before_total} |",
        f"| Tokens after (total) | {tokens_after_total} |",
        f"| Avg compression ratio | {avg_ratio:.3f} |",
        f"| Avg token reduction | {avg_reduction:.1f}% |",
        f"| Max token reduction | {max_reduction:.1f}% |",
        f"| Min token reduction | {min_reduction:.1f}% |",
        "\n## Structural Integrity\n",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Orphan tool results | {orphan_total} |",
        f"| Missing tool results | {missing_total} |",
        "\n## Semantic Probes\n",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Recall | {probe_passed}/{probe_total} |",
        f"| Rate | {round(probe_passed/probe_total, 3) if probe_total > 0 else 0} |",
        "\n## Isolation\n",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Cross-session leak count | {cross_session_leak} |",
        f"| Cross-user leak count | {cross_user_leak} |",
        "\n## Overhead\n",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Real LLM calls | {llm_client.total_calls} |",
        f"| Answer chars total | {metrics['overhead']['answer_chars_total']} |",
        f"| Total latency | {metrics['overhead']['total_latency_ms']:.0f}ms |",
        f"| Semantic summary calls | {semantic_call_count} |",
        f"| Semantic summary successes | {semantic_success_count} |",
        f"| Semantic summary fallbacks | {semantic_fallback_count} |",
        f"| Semantic summary latency | {semantic_latency_total:.0f}ms |",
    ]
    report_md_path = report_dir / "report.md"
    report_md_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(f"\n  Report: {report_dir / 'report.md'}")
    print(f"  Metrics: {metrics_path}")
    print(f"  Status: {status.upper()}")

    # Print final metrics overview
    print(f"\n{'='*65}")
    print("  METRICS OVERVIEW")
    print(f"{'='*65}")
    print(f"  Compression events:      {compression_count}")
    print(f"  Token reduction max:     {max_reduction:.1f}%")
    print(f"  Token reduction avg:     {avg_reduction:.1f}%")
    print(f"  Structure errors:        orphan={orphan_total}, missing={missing_total}")
    print(f"  Semantic recall:         {probe_passed}/{probe_total}")
    print(f"  Cross-session leak:      {cross_session_leak}")
    print(f"  Cross-user leak:         {cross_user_leak}")
    print(f"  LLM calls:               {llm_client.total_calls}")
    print(f"  Total latency:           {metrics['overhead']['total_latency_ms']:.0f}ms")


if __name__ == "__main__":
    main()
