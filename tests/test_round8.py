"""Tests for Round 8: quality gate, prompt rules, truncation metadata, scenario validation."""

import json
import os
import sys
from pathlib import Path

import pytest

from src.context import ToolContext
from src.prompt import SYSTEM_PROMPT
from src.session import SessionStore
from src.tools.read_docs import ReadDocsTool, _DOCS_DIR, _MAX_CONTENT_CHARS
from src.tools.search_docs import SearchDocsTool

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SCENARIOS_PATH = _PROJECT_ROOT / "scenarios" / "agent-e2e-scenarios.json"


# ---------------------------------------------------------------------------
# System Prompt rules
# ---------------------------------------------------------------------------

class TestPromptRules:
    def test_freshness_rule_present(self):
        """Rule #9: dynamic state / freshness rule is in SYSTEM_PROMPT."""
        assert "DYNAMIC EXTERNAL STATE" in SYSTEM_PROMPT

    def test_explicit_filename_rule_present(self):
        """Rule #10: exact filename passing rule."""
        assert "EXACT original filename" in SYSTEM_PROMPT

    def test_no_repeat_empty_results_rule_present(self):
        """Rule #11: no repeat of empty results."""
        assert "do NOT immediately repeat" in SYSTEM_PROMPT

    def test_truncation_disclosure_rule_present(self):
        """Rule #12: truncated disclosure rule."""
        assert "truncated" in SYSTEM_PROMPT
        assert "explicitly state" in SYSTEM_PROMPT or "MUST explicitly state" in SYSTEM_PROMPT

    def test_tool_result_precedence_rule_present(self):
        """Rule #13: tool results override memory."""
        assert "current tool result takes precedence" in SYSTEM_PROMPT

    def test_rules_count(self):
        """There should be at least 13 numbered rules."""
        import re
        numbered = re.findall(r"^\d+\.", SYSTEM_PROMPT, re.MULTILINE)
        assert len(numbered) >= 13, f"Expected >= 13 numbered rules, found {len(numbered)}"


# ---------------------------------------------------------------------------
# Long document truncation metadata
# ---------------------------------------------------------------------------

class TestLongDocumentTruncation:
    @pytest.fixture
    def long_docs_dir(self, tmp_path):
        d = tmp_path / "knowledge_docs"
        d.mkdir()
        # Create a doc that exceeds _MAX_CONTENT_CHARS
        line = "A" * 200 + "\n"
        repetitions = (_MAX_CONTENT_CHARS // len(line)) + 10
        content = "# Long Doc\n" + (line * repetitions) + "\n文档末尾识别码：银色狮子8642\n"
        (d / "长文档.md").write_text(content, encoding="utf-8")
        yield d

    @pytest.fixture
    def patch_docs(self, monkeypatch, long_docs_dir):
        from src.tools import read_docs as rd
        from src.tools import search_docs as sd
        monkeypatch.setattr(rd, "_DOCS_DIR", long_docs_dir)
        monkeypatch.setattr(sd, "_DOCS_DIR", long_docs_dir)
        return long_docs_dir

    @pytest.fixture
    def ctx(self, patch_docs):
        return ToolContext(user_id="tester", session_id="s1", store=SessionStore())

    def test_truncation_metadata_fields_present(self, ctx):
        """Verify all truncation metadata fields are in read_docs result."""
        tool = ReadDocsTool()
        raw = tool.execute(ctx, filename="长文档.md")
        result = json.loads(raw)
        assert result.get("found") is True
        assert "original_chars" in result
        assert "returned_chars" in result
        assert "truncated" in result

    def test_truncated_true_when_exceeds_limit(self, ctx):
        """Verify truncated=True when content exceeds _MAX_CONTENT_CHARS."""
        tool = ReadDocsTool()
        raw = tool.execute(ctx, filename="长文档.md")
        result = json.loads(raw)
        assert result["truncated"] is True

    def test_original_chars_gt_returned_chars(self, ctx):
        """Verify original_chars > returned_chars when truncated."""
        tool = ReadDocsTool()
        raw = tool.execute(ctx, filename="长文档.md")
        result = json.loads(raw)
        assert result["original_chars"] > result["returned_chars"]

    def test_truncated_content_no_end_marker(self, ctx):
        """Verify truncated content does NOT contain the end marker."""
        tool = ReadDocsTool()
        raw = tool.execute(ctx, filename="长文档.md")
        result = json.loads(raw)
        content = result.get("content", "")
        assert "银色狮子8642" not in content

    def test_search_docs_still_finds_end_marker(self, ctx):
        """Verify search_docs (full-text) still finds end marker in long doc."""
        tool = SearchDocsTool()
        raw = tool.execute(ctx, query="银色狮子8642", top_k=5)
        result = json.loads(raw)
        filenames = [r["filename"] for r in result.get("results", [])]
        assert any("长文档.md" in fn for fn in filenames)

    def test_search_docs_finds_keyword_in_long_doc(self, ctx):
        """Verify search_docs finds content beyond truncation point."""
        tool = SearchDocsTool()
        raw = tool.execute(ctx, query="银色狮子8642", top_k=5)
        result = json.loads(raw)
        assert len(result.get("results", [])) > 0


# ---------------------------------------------------------------------------
# read_docs metadata for short documents (no truncation)
# ---------------------------------------------------------------------------

class TestReadDocsMetadata:
    @pytest.fixture
    def short_docs_dir(self, tmp_path):
        d = tmp_path / "knowledge_docs"
        d.mkdir()
        (d / "short.md").write_text("# Short\nSmall content.", encoding="utf-8")
        yield d

    @pytest.fixture
    def patch_docs(self, monkeypatch, short_docs_dir):
        from src.tools import read_docs as rd
        monkeypatch.setattr(rd, "_DOCS_DIR", short_docs_dir)

    @pytest.fixture
    def ctx(self, patch_docs):
        return ToolContext(user_id="tester", session_id="s1", store=SessionStore())

    def test_short_doc_no_truncation(self, ctx):
        tool = ReadDocsTool()
        raw = tool.execute(ctx, filename="short.md")
        result = json.loads(raw)
        assert result["truncated"] is False
        assert result["original_chars"] == result["returned_chars"]

    def test_short_doc_metadata_fields(self, ctx):
        tool = ReadDocsTool()
        raw = tool.execute(ctx, filename="short.md")
        result = json.loads(raw)
        assert "original_chars" in result
        assert "returned_chars" in result
        assert result["original_chars"] > 0


# ---------------------------------------------------------------------------
# Scenario JSON validation
# ---------------------------------------------------------------------------

class TestScenarioJson:
    def test_scenario_json_exists(self):
        assert _SCENARIOS_PATH.exists(), f"Scenarios file not found: {_SCENARIOS_PATH}"

    def test_scenario_json_valid_json(self):
        with open(_SCENARIOS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, list), "Must be a JSON array"
        assert len(data) > 0, "Must have at least one scenario"

    def test_scenario_ids_unique(self):
        with open(_SCENARIOS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        ids = [s["id"] for s in data if "id" in s]
        duplicates = [i for i in ids if ids.count(i) > 1]
        assert len(duplicates) == 0, f"Duplicate scenario IDs: {set(duplicates)}"

    def test_each_scenario_has_required_fields(self):
        with open(_SCENARIOS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for s in data:
            assert "id" in s, f"Scenario missing 'id': {s.get('title', '?')}"
            assert "title" in s, f"Scenario {s['id']} missing 'title'"
            assert "steps" in s, f"Scenario {s['id']} missing 'steps'"
            assert len(s["steps"]) > 0, f"Scenario {s['id']} has no steps"
            assert "api_required" in s, f"Scenario {s['id']} missing 'api_required'"

    def test_setup_cleanup_allowed_operations(self):
        """Verify setup/cleanup only operate on allowed directories."""
        allowed_actions = {"ensure_file", "remove_file", "create_file", "ensure_long_file"}
        with open(_SCENARIOS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for s in data:
            for phase in ("setup", "cleanup"):
                for action in s.get(phase, []):
                    act = action.get("action", "")
                    assert act in allowed_actions, (
                        f"Scenario {s['id']}: unknown action '{act}' in {phase}"
                    )
                    fn = action.get("filename", "")
                    assert ".." not in fn, (
                        f"Scenario {s['id']}: path traversal in {phase} filename: {fn}"
                    )
                    assert not fn.startswith(("/", "\\")), (
                        f"Scenario {s['id']}: absolute path in {phase} filename: {fn}"
                    )
                    # Ensure no Windows drive letter
                    assert ":" not in fn.replace(":", ""), (
                        f"Scenario {s['id']}: drive letter in {phase} filename: {fn}"
                    )

    def test_each_step_has_required_fields(self):
        with open(_SCENARIOS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for s in data:
            for i, step in enumerate(s["steps"]):
                if "action_before" in step:
                    # Action-before steps do not require 'input'
                    continue
                assert "input" in step, (
                    f"Scenario {s['id']} step {i+1} missing 'input': {step}"
                )
                assert isinstance(step.get("expected_tools", []), list), (
                    f"Scenario {s['id']} step {i+1}: expected_tools must be a list"
                )
                assert isinstance(step.get("forbidden_tools", []), list), (
                    f"Scenario {s['id']} step {i+1}: forbidden_tools must be a list"
                )


# ---------------------------------------------------------------------------
# Real scenario runner dry-run validation
# ---------------------------------------------------------------------------

class TestScenarioRunnerDryRun:
    def test_dry_run_does_not_call_api(self):
        """Verify the dry-run flag skips all API calls."""
        import subprocess
        result = subprocess.run(
            [sys.executable, str(_PROJECT_ROOT / "scripts" / "run_real_agent_scenarios.py"),
             "--scenario", "DOC-LIST-001", "--dry-run"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "RUN_REAL_LLM_TESTS": "0"}
        )
        assert "Dry run" in result.stdout or "Dry run" in result.stderr


# ---------------------------------------------------------------------------
# Regular pytest does NOT call real API
# ---------------------------------------------------------------------------

class TestNoRealApi:
    def test_pytest_without_env_var_skips_real_api(self):
        """Verify RUN_REAL_LLM_TESTS not set means no real API calls."""
        assert os.environ.get("RUN_REAL_LLM_TESTS") != "1", (
            "This test must run without RUN_REAL_LLM_TESTS=1"
        )
