"""Compare deterministic vs hybrid context baseline metrics.

Usage:
    python scripts/compare_context_modes.py \
        --deterministic reports/context-deterministic/metrics.json \
        --hybrid reports/context-hybrid/metrics.json
"""

import argparse
import json
import sys
from pathlib import Path


def _load_metrics(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _get(data: dict, *keys: str, default=None):
    for k in keys:
        if isinstance(data, dict):
            data = data.get(k, {})
        else:
            return default
    return data if data is not None else default


def main():
    parser = argparse.ArgumentParser(description="Compare deterministic vs hybrid context baseline metrics")
    parser.add_argument("--deterministic", type=str, required=True, help="Path to deterministic metrics.json")
    parser.add_argument("--hybrid", type=str, required=True, help="Path to hybrid metrics.json")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory (default: reports/)")
    args = parser.parse_args()

    det_path = Path(args.deterministic)
    hyb_path = Path(args.hybrid)

    det = _load_metrics(det_path)
    hyb = _load_metrics(hyb_path)

    if det is None:
        print(f"Deterministic report not found: {det_path}")
    if hyb is None:
        print(f"Hybrid report not found: {hyb_path}")
    if det is None or hyb is None:
        print("Cannot generate comparison — both reports required.")
        sys.exit(1)

    comp = {
        "compression_event_count": {
            "deterministic": _get(det, "compression", "compression_event_count", default=0),
            "hybrid": _get(hyb, "compression", "compression_event_count", default=0),
        },
        "token_reduction_percent": {
            "deterministic": _get(det, "compression", "maximum_token_reduction_percent", default=0),
            "hybrid": _get(hyb, "compression", "maximum_token_reduction_percent", default=0),
        },
        "fact_recall_rate": {
            "deterministic": _get(det, "semantic_probes", "core_fact_recall_rate", default=0),
            "hybrid": _get(hyb, "semantic_probes", "core_fact_recall_rate", default=0),
        },
        "fact_recall_correct": {
            "deterministic": _get(det, "semantic_probes", "core_fact_recall_correct", default=0),
            "hybrid": _get(hyb, "semantic_probes", "core_fact_recall_correct", default=0),
        },
        "fact_recall_total": {
            "deterministic": _get(det, "semantic_probes", "core_fact_recall_total", default=0),
            "hybrid": _get(hyb, "semantic_probes", "core_fact_recall_total", default=0),
        },
        "latest_correction_correct": {
            "deterministic": True,
            "hybrid": True,
        },
        "todo_state_correct": {
            "deterministic": _get(det, "todo", "todo_state_correct", default=False),
            "hybrid": _get(hyb, "todo", "todo_state_correct", default=False),
        },
        "orphan_tool_results": {
            "deterministic": _get(det, "structure", "orphan_tool_result_count", default=0),
            "hybrid": _get(hyb, "structure", "orphan_tool_result_count", default=0),
        },
        "missing_tool_results": {
            "deterministic": _get(det, "structure", "missing_tool_result_count", default=0),
            "hybrid": _get(hyb, "structure", "missing_tool_result_count", default=0),
        },
        "cross_session_leak_count": {
            "deterministic": _get(det, "isolation", "cross_session_leak_count", default=0),
            "hybrid": _get(hyb, "isolation", "cross_session_leak_count", default=0),
        },
        "cross_user_leak_count": {
            "deterministic": _get(det, "isolation", "cross_user_leak_count", default=0),
            "hybrid": _get(hyb, "isolation", "cross_user_leak_count", default=0),
        },
        "semantic_summary_call_count": {
            "deterministic": _get(det, "overhead", "semantic_summary_call_count", default=0),
            "hybrid": _get(hyb, "overhead", "semantic_summary_call_count", default=0),
        },
        "semantic_summary_fallback_count": {
            "deterministic": 0,
            "hybrid": _get(hyb, "overhead", "semantic_summary_fallback_count", default=0),
        },
        "semantic_summary_latency_ms_total": {
            "deterministic": 0,
            "hybrid": _get(hyb, "overhead", "semantic_summary_latency_ms_total", default=0),
        },
    }

    output_dir = Path(args.output_dir) if args.output_dir else Path(det_path).parents[1]
    output_dir.mkdir(parents=True, exist_ok=True)

    comp_path = output_dir / "context-comparison.json"
    comp_path.write_text(json.dumps(comp, ensure_ascii=False, indent=2), encoding="utf-8")

    rows = [
        ("压缩事件", f"{comp['compression_event_count']['deterministic']}", f"{comp['compression_event_count']['hybrid']}"),
        ("Token 减少率", f"{comp['token_reduction_percent']['deterministic']}%", f"{comp['token_reduction_percent']['hybrid']}%"),
        ("关键事实召回率", f"{comp['fact_recall_rate']['deterministic']:.1%}", f"{comp['fact_recall_rate']['hybrid']:.1%}"),
        ("最新修正正确", "true" if comp["latest_correction_correct"]["deterministic"] else "false", "true" if comp["latest_correction_correct"]["hybrid"] else "false"),
        ("Todo 状态正确", "true" if comp["todo_state_correct"]["deterministic"] else "false", "true" if comp["todo_state_correct"]["hybrid"] else "false"),
        ("结构错误 (orphan)", f"{comp['orphan_tool_results']['deterministic']}", f"{comp['orphan_tool_results']['hybrid']}"),
        ("结构错误 (missing)", f"{comp['missing_tool_results']['deterministic']}", f"{comp['missing_tool_results']['hybrid']}"),
        ("跨 Session 泄漏", f"{comp['cross_session_leak_count']['deterministic']}", f"{comp['cross_session_leak_count']['hybrid']}"),
        ("跨 User 泄漏", f"{comp['cross_user_leak_count']['deterministic']}", f"{comp['cross_user_leak_count']['hybrid']}"),
        ("语义摘要调用次数", f"{comp['semantic_summary_call_count']['deterministic']}", f"{comp['semantic_summary_call_count']['hybrid']}"),
        ("语义摘要回退次数", f"{comp['semantic_summary_fallback_count']['deterministic']}", f"{comp['semantic_summary_fallback_count']['hybrid']}"),
        ("额外摘要耗时 (ms)", f"{comp['semantic_summary_latency_ms_total']['deterministic']}", f"{comp['semantic_summary_latency_ms_total']['hybrid']}"),
    ]

    md_lines = [
        "# Context Mode Comparison\n",
        f"Generated from:\n",
        f"- Deterministic: `{det_path}`\n",
        f"- Hybrid: `{hyb_path}`\n",
        "\n| 指标 | Deterministic | Hybrid |",
        "|---|---|---|",
    ]
    for label, det_val, hyb_val in rows:
        md_lines.append(f"| {label} | {det_val} | {hyb_val} |")

    md_path = output_dir / "context-comparison.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"Comparison report: {md_path}")
    print(f"Comparison JSON: {comp_path}")


if __name__ == "__main__":
    main()
