"""Real LLM scenario runner for minimal_agent.

Reads scenarios/agent-e2e-scenarios.json and runs them against the real
OpenAICompatibleLLMClient (qwen3.6-plus) with the full AgentRuntime pipeline.

Usage:
    python scripts/run_real_agent_scenarios.py --scenario DOC-LIST-001
    python scripts/run_real_agent_scenarios.py --tag freshness
    python scripts/run_real_agent_scenarios.py --all
    python scripts/run_real_agent_scenarios.py --dry-run
"""

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Guard: require env var + API key
_RUN_REAL = os.environ.get("RUN_REAL_LLM_TESTS") == "1"
_HAS_KEY = bool(os.environ.get("DASHSCOPE_API_KEY"))


def _check_prerequisites():
    global _HAS_KEY
    if not _HAS_KEY:
        # Try loading from .env file
        from dotenv import load_dotenv
        load_dotenv()
        if os.environ.get("DASHSCOPE_API_KEY"):
            _HAS_KEY = True
    if not _RUN_REAL:
        print("SKIPPED: RUN_REAL_LLM_TESTS not set to 1")
        return False
    if not _HAS_KEY:
        print("SKIPPED: DASHSCOPE_API_KEY not configured")
        return False
    return True


def _load_scenarios(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("scenarios file must contain a JSON array")
    return data


def _validate_scenario_ids(scenarios: list[dict]) -> list[str]:
    errors = []
    seen: set[str] = set()
    for s in scenarios:
        sid = s.get("id", "")
        if not sid:
            errors.append("Scenario missing 'id'")
        elif sid in seen:
            errors.append(f"Duplicate scenario id: {sid}")
        seen.add(sid)
        # Validate setup/cleanup actions
        for phase in ("setup", "cleanup"):
            for action in s.get(phase, []):
                act = action.get("action", "")
                if act not in ("ensure_file", "remove_file", "create_file", "ensure_long_file"):
                    errors.append(f"Scenario {sid}: unknown action '{act}' in {phase}")
                if "filename" in action:
                    fn = action["filename"]
                    if ".." in fn or fn.startswith("/") or ":" in fn:
                        errors.append(f"Scenario {sid}: path traversal risk in {phase} filename: {fn}")
    return errors


def _resolve_knowledge_docs() -> Path:
    return PROJECT_ROOT / "knowledge_docs"


def _ensure_file(filename: str, content: str):
    docs_dir = _resolve_knowledge_docs()
    docs_dir.mkdir(parents=True, exist_ok=True)
    fp = docs_dir / filename
    fp.write_text(content, encoding="utf-8")
    print(f"  [setup] Created {fp}")


def _create_long_file(filename: str, target_chars: int, end_marker: str):
    docs_dir = _resolve_knowledge_docs()
    docs_dir.mkdir(parents=True, exist_ok=True)
    fp = docs_dir / filename
    line = "这是用于测试长文档截断行为的重复行。\n"
    repetitions = (target_chars // len(line)) + 1
    content = "# 长文档截断测试\n\n" + (line * repetitions) + "\n\n" + end_marker
    fp.write_text(content, encoding="utf-8")
    print(f"  [setup] Created long file {fp} ({len(content)} chars)")


def _remove_file(filename: str):
    docs_dir = _resolve_knowledge_docs()
    fp = docs_dir / filename
    if fp.exists():
        fp.unlink()
        print(f"  [cleanup] Removed {fp}")


def _apply_setup(scenario: dict):
    for action in scenario.get("setup", []):
        act = action["action"]
        fn = action["filename"]
        if act == "ensure_file":
            _ensure_file(fn, action.get("content", ""))
        elif act == "create_file":
            _ensure_file(fn, action.get("content", ""))
        elif act == "ensure_long_file":
            _create_long_file(fn, action.get("target_chars", 12000), action.get("end_marker", ""))
        elif act == "remove_file":
            _remove_file(fn)


def _apply_cleanup(scenario: dict):
    for action in scenario.get("cleanup", []):
        act = action["action"]
        fn = action["filename"]
        if act == "remove_file":
            _remove_file(fn)


def _apply_action_before(step: dict):
    """Apply action_before from a step dict."""
    action_before = step.get("action_before")
    if isinstance(action_before, str):
        # action_before is an action name, fields are at step level
        act = action_before
        fn = step.get("filename", "")
    elif isinstance(action_before, dict):
        # action_before is a dict with action/filename/content
        act = action_before.get("action", "")
        fn = action_before.get("filename", "")
    else:
        return
    if act == "create_file":
        content = ""
        if isinstance(action_before, dict):
            content = action_before.get("content", "")
        else:
            content = step.get("content", "")
        _ensure_file(fn, content)
    elif act == "remove_file":
        _remove_file(fn)


def _check_tool_in_traces(traces: list[dict], tool_name: str) -> bool:
    for t in traces:
        if t.get("event_type") == "tool_call" and t.get("tool_name") == tool_name:
            return True
    return False


def _check_forbidden_tool_in_traces(traces: list[dict], tool_name: str) -> bool:
    for t in traces:
        if t.get("event_type") == "tool_call" and t.get("tool_name") == tool_name:
            return True
    return False


def _run_scenario(scenario: dict, runtime: "AgentRuntime", user_id: str, session_id: str) -> dict:
    """Run a single scenario and return a result dict."""
    sid = scenario["id"]
    title = scenario.get("title", sid)
    print(f"\n{'='*60}")
    print(f"Scenario: {sid} — {title}")
    print(f"{'='*60}")

    # Fresh session
    if scenario.get("fresh_session", True):
        session_id = str(uuid.uuid4())[:8]

    _apply_setup(scenario)

    step_results = []
    all_passed = True

    try:
        for i, step in enumerate(scenario["steps"]):
            # Handle action_before (no user input step)
            if step.get("action_before") and "input" not in step:
                _apply_action_before(step)
                continue

            if "input" not in step:
                print(f"  [WARN] Step {i+1} has no 'input' and no 'action_before', skipping")
                continue

            print(f"\n  Step {i+1}: input = {step['input'][:80]!r}")

            # Handle action_before with input step
            if step.get("action_before"):
                _apply_action_before(step)

            # Run agent
            try:
                result = runtime.run(
                    user_id=user_id,
                    session_id=session_id,
                    user_input=step["input"],
                )
            except Exception as e:
                step_result = {
                    "step": i + 1,
                    "status": "error",
                    "error": str(e),
                    "tools_called": [],
                    "forbidden_called": [],
                }
                step_results.append(step_result)
                all_passed = False
                print(f"  [WARN] Error: {e}")
                continue

            traces = result.traces
            print(f"  Answer (first 200): {result.answer[:200]}")
            tools_called = [
                t["tool_name"] for t in traces if t.get("event_type") == "tool_call"
            ]
            print(f"  Tools: {tools_called}")

            # Check expected tools
            expected_tools = step.get("expected_tools", [])
            expected_ok = True
            for et in expected_tools:
                if not _check_tool_in_traces(traces, et):
                    expected_ok = False
                    print(f"  [FAIL] Expected tool '{et}' not called")

            # Check forbidden tools
            forbidden_tools = step.get("forbidden_tools", [])
            forbidden_ok = True
            for ft in forbidden_tools:
                if _check_forbidden_tool_in_traces(traces, ft):
                    forbidden_ok = False
                    print(f"  [FAIL] Forbidden tool '{ft}' was called")

            # Check expected answer contains
            expected_answer_contains = step.get("expected_answer_contains", [])
            answer_contains_ok = True
            if expected_answer_contains:
                for keyword in expected_answer_contains:
                    if keyword not in result.answer:
                        answer_contains_ok = False
                        print(f"  [WARN] Expected keyword not found in answer: {keyword!r}")

            # Check expected answer NOT contains
            expected_answer_not_contains = step.get("expected_answer_not_contains", [])
            answer_not_contains_ok = True
            for keyword in expected_answer_not_contains:
                if keyword in result.answer:
                    answer_not_contains_ok = False
                    print(f"  [WARN] Forbidden keyword found in answer: {keyword!r}")

            passed = expected_ok and forbidden_ok and answer_contains_ok and answer_not_contains_ok
            if not passed:
                all_passed = False

            status = "passed" if passed else "failed"
            print(f"  -> {status}")

            step_result = {
                "step": i + 1,
                "status": status,
                "input": step["input"],
                "tools_called": tools_called,
                "forbidden_called": [ft for ft in forbidden_tools if ft in tools_called],
                "expected_tools_ok": expected_ok,
                "forbidden_tools_ok": forbidden_ok,
                "answer_contains_ok": answer_contains_ok,
                "answer_not_contains_ok": answer_not_contains_ok,
            }
            step_results.append(step_result)

    finally:
        _apply_cleanup(scenario)

    overall = "passed" if all_passed else "failed"
    return {
        "id": sid,
        "title": title,
        "status": overall,
        "step_results": step_results,
    }


def main():
    parser = argparse.ArgumentParser(description="Run real LLM agent scenarios")
    parser.add_argument("--scenario", type=str, default=None, help="Run a specific scenario by ID")
    parser.add_argument("--tag", type=str, default=None, help="Run scenarios with a specific tag")
    parser.add_argument("--all", action="store_true", help="Run all scenarios")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without calling API")
    parser.add_argument("--scenarios", type=str, default=None,
                        help="Path to scenarios JSON file (default: scenarios/agent-e2e-scenarios.json)")
    args = parser.parse_args()

    scenarios_path = Path(args.scenarios) if args.scenarios else (PROJECT_ROOT / "scenarios" / "agent-e2e-scenarios.json")
    if not scenarios_path.exists():
        print(f"Scenarios file not found: {scenarios_path}")
        sys.exit(1)

    scenarios = _load_scenarios(scenarios_path)

    # Validate
    errors = _validate_scenario_ids(scenarios)
    if errors:
        for e in errors:
            print(f"Validation error: {e}")
        sys.exit(1)

    # Filter
    if args.scenario:
        scenarios = [s for s in scenarios if s["id"] == args.scenario]
    elif args.tag:
        scenarios = [s for s in scenarios if args.tag in s.get("tags", [])]
    elif not args.all:
        print("No filter specified. Use --scenario ID, --tag TAG, or --all")
        print("Add --dry-run to preview without calling API.")
        sys.exit(0)

    if not scenarios:
        print("No matching scenarios.")
        return

    # Report plan
    print(f"\nPlan: {len(scenarios)} scenario(s)")
    for s in scenarios:
        n_steps = len(s["steps"])
        cost = s.get("cost", "unknown")
        tags = ", ".join(s.get("tags", []))
        print(f"  {s['id']}: {s['title']} ({n_steps} steps, cost={cost}, tags=[{tags}])")

    if args.dry_run:
        print("\nDry run — no API calls made.")
        return

    if not _check_prerequisites():
        sys.exit(0)

    # Build real runtime
    from src.agent import AgentRuntime
    from src.bootstrap import build_default_registry
    from src.config import load_context_policy, load_llm_settings
    from src.context_manager import ContextManager
    from src.prompt import SYSTEM_PROMPT
    from src.qwen_client import OpenAICompatibleLLMClient
    from src.sqlite_session import SQLiteSessionStore

    settings = load_llm_settings()
    llm_client = OpenAICompatibleLLMClient(settings=settings)
    registry = build_default_registry()
    store = SQLiteSessionStore(db_path=":memory:")  # Independent temp DB
    context_policy = load_context_policy()
    runtime = AgentRuntime(
        llm_client=llm_client,
        tool_registry=registry,
        session_store=store,
        system_prompt=SYSTEM_PROMPT,
        max_steps=settings.max_retries + 6,
        context_manager=ContextManager(context_policy),
    )

    user_id = "scenario-runner"
    session_id = str(uuid.uuid4())[:8]

    # Run scenarios sequentially
    results = []
    for scenario in scenarios:
        result = _run_scenario(scenario, runtime, user_id, session_id)
        results.append(result)

    # Generate reports
    report_dir = PROJECT_ROOT / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    # JSON report
    report_json = {
        "generated_at": datetime.now().isoformat(),
        "total": len(results),
        "passed": sum(1 for r in results if r["status"] == "passed"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "results": results,
    }
    json_path = report_dir / "real-agent-scenario-report.json"
    json_path.write_text(json.dumps(report_json, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON report: {json_path}")

    # Markdown report
    lines = [
        "# Real Agent Scenario Report\n",
        f"Generated: {datetime.now().isoformat()}\n",
        f"Total: {report_json['total']} | Passed: {report_json['passed']} | Failed: {report_json['failed']}\n",
        "| Scenario | Title | Status | Steps |",
        "|----------|-------|--------|-------|",
    ]
    for r in results:
        n_passed = sum(1 for s in r["step_results"] if s["status"] == "passed")
        n_total = len(r["step_results"])
        status_icon = "PASS" if r["status"] == "passed" else "FAIL"
        lines.append(f"| {r['id']} | {r['title']} | {status_icon} {r['status']} | {n_passed}/{n_total} |")

    md_path = report_dir / "real-agent-scenario-report.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Markdown report: {md_path}")

    print(f"\nSummary: {report_json['passed']} passed, {report_json['failed']} failed out of {report_json['total']}")


if __name__ == "__main__":
    main()
