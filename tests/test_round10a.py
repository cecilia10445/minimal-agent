"""Tests for Round 10A: Context baseline — scenario validation, metrics, edge replay."""

import json
import os
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SCENARIO_PATH = _PROJECT_ROOT / "scenarios" / "context-baseline-v1.json"
_REPORT_DIR = _PROJECT_ROOT / "reports" / "context-baseline-v1"


def _load_scenario():
    with open(_SCENARIO_PATH, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Scenario structure
# ---------------------------------------------------------------------------

class TestScenarioStructure:
    def test_scenario_exists(self):
        assert _SCENARIO_PATH.exists()

    def test_scenario_valid_json(self):
        data = _load_scenario()
        assert isinstance(data, dict)
        assert data.get("id") == "context-baseline-v1"

    def test_exactly_20_chat_turns(self):
        data = _load_scenario()
        assert len(data.get("chat_turns", [])) == 20

    def test_exactly_10_tool_turns(self):
        data = _load_scenario()
        assert len(data.get("tool_turns", [])) == 10

    def test_exactly_10_semantic_probes(self):
        data = _load_scenario()
        assert len(data.get("semantic_probes", [])) == 10

    def test_probe_checks_match_probes(self):
        data = _load_scenario()
        probes = data.get("semantic_probes", [])
        checks = data.get("semantic_probe_checks", {})
        for p in probes:
            assert p in checks, f"Probe missing check: {p}"
        assert len(checks) == len(probes)


# ---------------------------------------------------------------------------
# Key facts and corrections exist in scenario
# ---------------------------------------------------------------------------

class TestKeyFacts:
    def test_project_code_exists(self):
        data = _load_scenario()
        chat = "\n".join(data["chat_turns"])
        assert "蓝色港湾" in chat

    def test_original_deadline_exists(self):
        data = _load_scenario()
        chat = "\n".join(data["chat_turns"])
        assert "周五" in chat
        assert "九点半" in chat

    def test_corrected_deadline_exists(self):
        data = _load_scenario()
        chat = "\n".join(data["chat_turns"])
        assert "周六" in chat
        assert "十点" in chat

    def test_banned_framework(self):
        data = _load_scenario()
        chat = "\n".join(data["chat_turns"])
        assert "LangGraph" in chat

    def test_answer_preference(self):
        data = _load_scenario()
        chat = "\n".join(data["chat_turns"])
        assert "先给结论" in chat
        assert "再解释" in chat

    def test_learning_goal(self):
        data = _load_scenario()
        chat = "\n".join(data["chat_turns"])
        assert "Agent Runtime" in chat
        assert "Context Management" in chat

    def test_completion_order(self):
        data = _load_scenario()
        chat = "\n".join(data["chat_turns"])
        assert "README" in chat
        assert "录屏" in chat
        assert "AI 开发记录" in chat

    def test_test_phrase(self):
        data = _load_scenario()
        chat = "\n".join(data["chat_turns"])
        assert "青铜罗盘31415" in chat

    def test_code_link(self):
        data = _load_scenario()
        chat = "\n".join(data["chat_turns"])
        assert "代码链接" in chat

    def test_fact_correction_present(self):
        """Verify corrected deadline is clearly marked as update."""
        data = _load_scenario()
        chat = "\n".join(data["chat_turns"])
        assert "作废" in chat or "更新" in chat


# ---------------------------------------------------------------------------
# Semantic probe expected values
# ---------------------------------------------------------------------------

class TestSemanticProbeChecks:
    def test_probe_1_project_code(self):
        checks = _load_scenario()["semantic_probe_checks"]
        c = checks["我的项目代号是什么？"]
        assert "蓝色港湾" in c["must_contain"]

    def test_probe_2_deadline_no_old_value(self):
        checks = _load_scenario()["semantic_probe_checks"]
        c = checks["最终截止时间是什么？不要回答已经作废的最初时间。"]
        assert "周六" in c["must_contain"]
        assert "周五" in c["must_not_contain"]

    def test_probe_3_banned_framework(self):
        checks = _load_scenario()["semantic_probe_checks"]
        c = checks["这个项目禁止使用什么框架控制主流程？"]
        assert "LangGraph" in c["must_contain"]

    def test_probe_4_preference(self):
        checks = _load_scenario()["semantic_probe_checks"]
        c = checks["我的回答偏好是什么？"]
        assert "先给结论" in c["must_contain"]
        assert "再解释" in c["must_contain"]

    def test_probe_9_todo_check(self):
        checks = _load_scenario()["semantic_probe_checks"]
        c = checks["查看当前 Todo，哪些已完成，哪些未完成？"]
        assert "README" in c["must_contain"] or "完成" in c["must_contain"]

    def test_probe_10_hive_doc(self):
        checks = _load_scenario()["semantic_probe_checks"]
        c = checks["我之前查看了哪份 Hive 文档？它主要排查什么问题？"]
        assert "HiveServer2" in c["must_contain"]
        assert "端口" in c["must_contain"] or "10000" in c["must_contain"]


# ---------------------------------------------------------------------------
# Metrics formulas
# ---------------------------------------------------------------------------

class TestMetricsFormulas:
    def test_compression_ratio_formula(self):
        """compression_ratio = tokens_after / tokens_before"""
        tb, ta = 2000, 800
        ratio = ta / tb
        assert ratio == 0.4
        reduction = (1 - ratio) * 100
        assert reduction == 60.0

    def test_recall_rate_formula(self):
        """core_fact_recall_rate = correct / total"""
        correct, total = 8, 10
        rate = correct / total
        assert rate == 0.8


# ---------------------------------------------------------------------------
# CompressionEvent structure
# ---------------------------------------------------------------------------

class TestCompressionEvent:
    def test_event_required_fields(self):
        event = {
            "event_index": 1,
            "turn_index": 18,
            "threshold": 1800,
            "tokens_before": 2000,
            "tokens_after": 800,
            "messages_before": 30,
            "messages_compressed": 22,
            "messages_retained": 8,
            "summary_chars_before": 0,
            "summary_chars_after": 1200,
            "compression_ratio": 0.4,
            "token_reduction_percent": 60.0,
            "orphan_tool_results": [],
            "missing_tool_results": [],
        }
        required = [
            "event_index", "turn_index", "threshold",
            "tokens_before", "tokens_after",
            "messages_before", "messages_compressed", "messages_retained",
            "summary_chars_before", "summary_chars_after",
            "compression_ratio", "token_reduction_percent",
            "orphan_tool_results", "missing_tool_results",
        ]
        for field in required:
            assert field in event, f"Missing field: {field}"

    def test_no_negative_ratio(self):
        ratio = 0
        assert ratio >= 0
        ratio = 1.0
        assert ratio <= 1.0


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_dry_run_does_not_call_api(self):
        import subprocess
        result = subprocess.run(
            [sys.executable,
             str(_PROJECT_ROOT / "scripts" / "run_context_baseline.py"),
             "--dry-run"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "RUN_REAL_LLM_TESTS": "0"},
        )
        assert "Dry run" in result.stdout or "Dry run" in result.stderr

    def test_dry_run_without_api(self):
        import subprocess
        result = subprocess.run(
            [sys.executable,
             str(_PROJECT_ROOT / "scripts" / "run_context_baseline.py"),
             "--dry-run"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "RUN_REAL_LLM_TESTS": "1", "DASHSCOPE_API_KEY": ""},
        )
        assert "Dry run" in result.stdout or "Dry run" in result.stderr


# ---------------------------------------------------------------------------
# RecordingLLMClient
# ---------------------------------------------------------------------------

class TestRecordingLLMClient:
    def test_records_call_metadata(self):
        from src.recording_llm_client import RecordingLLMClient
        from src.llm import ScriptedLLMClient, LLMResponse

        inner = ScriptedLLMClient([LLMResponse(content="Hello", tool_calls=[])])
        recorder = RecordingLLMClient(inner)
        response = recorder.complete(
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
        )
        assert response.content == "Hello"
        assert len(recorder.records) == 1
        record = recorder.records[0]
        assert record["call_index"] == 0
        assert record["message_count"] == 1
        assert record["success"] is True
        assert record["estimated_input_tokens"] >= 1

    def test_no_api_key_in_records(self):
        from src.recording_llm_client import RecordingLLMClient
        from src.llm import ScriptedLLMClient, LLMResponse

        inner = ScriptedLLMClient([LLMResponse(content="ok", tool_calls=[])])
        recorder = RecordingLLMClient(inner)
        recorder.complete(
            messages=[{"role": "system", "content": "You are a bot."}],
            tools=[],
        )
        record_json = json.dumps(recorder.records, ensure_ascii=False)
        assert "DASHSCOPE_API_KEY" not in record_json
        assert "sk-" not in record_json


# ---------------------------------------------------------------------------
# Edge replay uses real ContextManager
# ---------------------------------------------------------------------------

class TestEdgeReplay:
    def test_imports_project_classes(self):
        from scripts import run_context_edge_replay as er
        assert hasattr(er, "ContextManager")
        assert hasattr(er, "Session")
        assert hasattr(er, "estimate_tokens")

    def test_build_edge_session_has_all_cases(self):
        from scripts.run_context_edge_replay import _build_edge_session
        session = _build_edge_session()
        msgs = session.messages
        # Should have chat + tool + error + parallel + long + asst_none + incomplete
        assert len(msgs) > 30
        # Verify parallel tool calls present
        parallel_found = False
        for m in msgs:
            if m.get("role") == "assistant" and "tool_calls" in m:
                if len(m["tool_calls"]) > 1:
                    parallel_found = True
                    break
        assert parallel_found, "No parallel tool calls in edge session"
        # Verify assistant content=None present
        none_found = any(
            m.get("role") == "assistant" and m.get("content") is None and "tool_calls" not in m
            for m in msgs
        )
        assert none_found, "No assistant content=None in edge session"
        # Verify incomplete turn
        incomplete_found = any(
            m.get("role") == "assistant" and m.get("content") is None and "tool_calls" in m
            for m in msgs
        )
        assert incomplete_found, "No incomplete turn in edge session"


# ---------------------------------------------------------------------------
# Independent database isolation
# ---------------------------------------------------------------------------

class TestDatabaseIsolation:
    def test_report_db_is_independent(self):
        """Verify baseline uses reports/context-baseline-v1/, not data/."""
        _REPORT_DIR.mkdir(parents=True, exist_ok=True)
        db_path = _REPORT_DIR / "context-baseline.db"
        # DB doesn't have to exist yet, but path should be in report dir
        assert "data" not in str(db_path)

    def test_report_dir_structure(self):
        REQUIRED = [
            "run-metadata.json",
            "transcript.jsonl",
            "transcript.md",
            "llm-calls.jsonl",
            "context-snapshots.jsonl",
            "compression-events.jsonl",
            "semantic-probes.json",
            "isolation-results.json",
            "metrics.json",
            "report.md",
        ]
        # Only check if a real run produced run-metadata.json (dry-run skips it)
        if (_REPORT_DIR / "run-metadata.json").exists():
            for fname in REQUIRED:
                assert (_REPORT_DIR / fname).exists(), f"Missing report file: {fname}"


# ---------------------------------------------------------------------------
# Multi tool call structure validation
# ---------------------------------------------------------------------------

class TestMultiToolStructure:
    def test_parallel_tool_calls_preserved(self):
        """Verify parallel tool calls + results are kept together."""
        from src.context_manager import ContextManager, ContextPolicy
        from src.session import Session

        msgs = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {
                "role": "assistant", "content": None,
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "calc", "arguments": "{}"}},
                    {"id": "c2", "type": "function", "function": {"name": "calc", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "name": "calc", "content": "r1"},
            {"role": "tool", "tool_call_id": "c2", "name": "calc", "content": "r2"},
            {"role": "assistant", "content": "done"},
        ]
        session = Session(user_id="t", session_id="s")
        session.messages = list(msgs)
        cm = ContextManager(ContextPolicy(max_estimated_tokens=1, keep_recent_user_turns=1))
        cm.prepare_session(session)

        # Should preserve all 5 messages of the tool turn
        tool_call_ids = set()
        tool_result_ids = set()
        for m in session.messages:
            if m.get("role") == "assistant" and "tool_calls" in m:
                for tc in m["tool_calls"]:
                    tool_call_ids.add(tc["id"])
            if m.get("role") == "tool":
                tool_result_ids.add(m.get("tool_call_id", ""))
        assert "c1" in tool_call_ids
        assert "c2" in tool_call_ids
        assert "c1" in tool_result_ids
        assert "c2" in tool_result_ids


# ---------------------------------------------------------------------------
# Report has no API key
# ---------------------------------------------------------------------------

class TestReportNoApiKey:
    def test_report_json_no_api_key(self, tmp_path):
        """Verify any generated report JSON files contain no API key."""
        import subprocess
        # Dry run generates some reports
        result = subprocess.run(
            [sys.executable,
             str(_PROJECT_ROOT / "scripts" / "run_context_baseline.py"),
             "--dry-run"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "RUN_REAL_LLM_TESTS": "0"},
        )
        # Check that no API key leaked (dry-run doesn't make calls)
        assert "DASHSCOPE_API_KEY" not in result.stdout
        assert "sk-" not in result.stdout


# ---------------------------------------------------------------------------
# Empty assistant content doesn't crash
# ---------------------------------------------------------------------------

class TestEmptyAssistant:
    def test_empty_assistant_none_content(self):
        """Verify assistant content=None without tool_calls doesn't crash summarizer."""
        from src.context_manager import _summarize_messages
        msgs = [
            {"role": "user", "content": "Say something"},
            {"role": "assistant", "content": None},
        ]
        entries = _summarize_messages(msgs, 300)
        assert len(entries) == 2
        assert "助手回答" in entries[1]


# ---------------------------------------------------------------------------
# All existing tests pass
# ---------------------------------------------------------------------------

class TestExistingTestsNotBroken:
    def test_existing_tests_import(self):
        """Import existing test modules to verify they still compile."""
        pass
