# Context Baseline Test Plan — Round 10A

## Why not rely on manual chatting?

Manual chat is:
- **Non-reproducible** — different users give different inputs, making comparisons meaningless
- **Time-consuming** — 30+ turns of manual conversation is impractical
- **Inconsistent** — users forget what facts were stated and when
- **Poor baseline** — cannot be re-run identically for A/B comparison

Instead, we use a **fixed 30-turn script** (20 chat + 10 tool) executed against real qwen3.6-plus. Every run uses the exact same inputs, session_id, and user_id. This gives a fully reproducible baseline.

## Scenario Design: 20 + 10

### 20 Chat Turns

Purpose: Build a rich session history that:
1. Establishes key facts (project code, deadline, preferences, constraints)
2. Includes a **fact correction** (deadline changes from Friday to Saturday)
3. Includes a **sequence change** (order of tasks)
4. Discusses conceptual topics about Agent Runtime design (turns 9-16)
5. Provides enough turns to trigger context compression within 30 rounds

Key facts planted:
- Project code: 蓝色港湾
- Original deadline: 周五晚上九点半 (later corrected)
- Final deadline: 周六上午十点
- Answer preference: 先给结论，再解释原因
- Banned framework: LangGraph
- Learning goal: Agent Runtime + Context Management
- Completion order: README → 录屏 → AI 开发记录
- Test phrase: 青铜罗盘31415
- Final requirement: 代码链接

### 10 Tool Turns

Purpose: Verify that compression does not break tool functionality:
1. calculator — single tool call
2. search — public info search (may return empty)
3-4. todo_add — two sequential adds
5. todo_list — state query
6. todo_complete — state modification
7. todo_list — state verification
8. read_docs (not found) → list_docs — error recovery
9. search_docs → read_docs — multi-tool chain (HiveServer2)
10. read_docs (truncated) → search_docs — long doc + end marker

### 10 Semantic Probes

After the 30 turns, the same session continues with 10 questions:
1. Project code recall
2. Final deadline (must NOT use the superceded value)
3. Banned framework
4. Answer preference
5. Learning goal
6. Completion order
7. Test phrase
8. Missing link
9. Todo state with tool call
10. Earlier document recall

## Real API vs Synthetic Edge Replay

### Real API (`scripts/run_context_baseline.py`)

- Calls real qwen3.6-plus for all 30 turns + probes + isolation checks
- Measures actual compression timing, LLM behavior, and semantic recall
- Uses `RecordingLLMClient` to log every LLM call
- Generates full reports in `reports/context-baseline-v1/`
- Requires `RUN_REAL_LLM_TESTS=1` and configured `DASHSCOPE_API_KEY`

### Synthetic Edge Replay (`scripts/run_context_edge_replay.py`)

- Zero API — constructs synthetic message history
- Covers edge cases not encountered in 30-turn baseline:
  - Multiple parallel tool calls
  - Tool error results
  - Tool success with empty results
  - Extra long tool results
  - Assistant content=None
  - Fact correction
  - Incomplete turn (no final answer)
- Verifies structural integrity after compression

## Semantic Probe Facts

| # | Question | Must contain | Must NOT contain |
|---|---|---|---|
| 1 | 项目代号 | 蓝色港湾 | — |
| 2 | 最终截止时间 | 周六, 十点, 10 | 周五, 九点半, 9:30 |
| 3 | 禁止框架 | LangGraph | — |
| 4 | 回答偏好 | 先给结论, 再解释 | — |
| 5 | 学习目标 | Agent Runtime, Context Management | — |
| 6 | 完成顺序 | README, 录屏, AI 开发记录 | — |
| 7 | 测试短语 | 青铜罗盘31415 | — |
| 8 | 缺少什么 | 代码链接 | — |
| 9 | Todo 状态 | README (完成), 录制 (未完成) | — |
| 10 | Hive 文档 | HiveServer2, 端口, 10000 | — |

## Metrics Definition

### Compression Efficiency
```
compression_ratio = tokens_after / tokens_before
token_reduction_percent = (1 - compression_ratio) * 100
```

### Structural Correctness
```
orphan_tool_result_count = tool results with no matching call
missing_tool_result_count = tool calls with no result
```

### Semantic Recall
```
core_fact_recall_rate = correct_probes / total_probes
```

### Isolation
```
cross_session_leak_count = leaked keywords in same-user-different-session
cross_user_leak_count = leaked keywords in different-user-same-session
```

## Test Acceleration Threshold vs Production Default

| Parameter | Test (this round) | Production Default |
|---|---|---|
| `max_estimated_tokens` | 1800 | 6000 |
| `keep_recent_user_turns` | 4 | 4 |
| `max_summary_chars` | 3000 | 3000 |
| `max_item_chars` | 300 | 300 |

The lowered `max_estimated_tokens` (1800 vs 6000) ensures compression triggers within 30 turns. 
All reports explicitly mark this difference.

## How to Replay

```powershell
# Zero-API edge case replay
python scripts/run_context_edge_replay.py

# Dry run
python scripts/run_context_baseline.py --dry-run

# Full baseline (requires API key)
$env:RUN_REAL_LLM_TESTS="1"
python scripts/run_context_baseline.py `
  --scenario scenarios/context-baseline-v1.json `
  --max-estimated-tokens 1800 `
  --keep-recent-user-turns 4

# Check results
Get-ChildItem reports/context-baseline-v1/
```

## How This Serves as Baseline for Round 10B

The current deterministic compression baseline provides:

1. **Metrics** — compression events, token reduction, structural errors, semantic recall
2. **Reports** — full transcript, LLM call history, context snapshots, probe results
3. **Database** — the saved SQLite session can be re-loaded and analyzed
4. **Comparison point** — when hybrid semantic summarizer is added in the next round, 
   all metrics can be compared against these baseline numbers
