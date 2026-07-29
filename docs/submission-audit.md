# 提交审计

对照原始项目需求逐任务验证。

| # | Requirement | Implementation | Source | Tests | Demo | Status |
|---|---|---|---|---|---|---|
| 1 | 自研 Agent Runtime | `AgentRuntime` class in `src/agent.py` — implements `run()` with LLM call loop, tool execution, step counting | `src/agent.py:42-58` | `test_agent.py` (24 tests), `test_all.py` | Verified via CLI and real Qwen | PASS |
| 2 | 接收输入 | `run(user_id, session_id, user_input)` — validates non-empty inputs | `src/agent.py:64-74` | `test_agent.py::TestInputValidation` | `python -m src.cli --user-id u --session-id s --input "hello"` | PASS |
| 3 | 直接回答或调用工具决策 | LLM can respond directly (content) or call tools (tool_calls); loop continues until final answer or max steps | `src/agent.py:89-163` | `test_agent.py::TestToolCall`, `test_all.py` | CLI demo: "What is 2+2?" → direct answer; "Add todo: buy milk" → tool call | PASS |
| 4 | 工具执行 | `_handle_tool_calls()` executes each tool via `ToolRegistry.execute()`, catches ToolNotFoundError/ToolParameterError/ToolExecutionError | `src/agent.py:171-247` | `test_agent.py::TestToolExecution`, `test_all.py` | CLI: "Calculate 5*7" → calculator tool | PASS |
| 5 | 根据工具结果继续循环或结束 | After tool results appended, LLM called again; if no tool_calls and content present → final answer returned | `src/agent.py:89-163` | `test_all.py::TestMultiToolSequence` | CLI: multi-tool chain search → read | PASS |
| 6 | Tool Registry | `ToolRegistry` class in `src/registry.py` — register, execute, export_openai_schema | `src/registry.py` | `test_all.py::TestToolRegistration` | N/A | PASS |
| 7 | 工具 name/description/JSON Schema | Each tool extends `BaseTool` with `name`, `description`, `input_schema` (JSON Schema dict) | `src/tools/*.py` (8 tools) | `test_all.py::TestToolSchemas` | N/A | PASS |
| 8 | LLM 自主选择工具 | `tool_choice="auto"` in `OpenAICompatibleLLMClient.complete()` | `src/qwen_client.py:109-119` | `test_qwen_client.py` | Real Qwen picks calculator/search/todo as needed | PASS |
| 9 | LLM 输出解析 | `_parse_message()` extracts content, tool_calls, arguments; validates JSON arguments | `src/qwen_client.py:47-83` | `test_qwen_client.py::TestMessageParsing` | N/A | PASS |
| 10 | 至少三个工具 | 8 tools: Calculator, Search, ListDocs, SearchDocs, ReadDocs, TodoAdd, TodoList, TodoComplete | `src/bootstrap.py:10-20` | `test_all.py::TestToolRegistry` | `python -m src.cli --list-tools` | PASS |
| 11 | 最大步骤限制 | `max_steps` (default 10) → `MaxStepsExceededError` after N steps | `src/agent.py:48-49, 149-163` | `test_agent.py::TestMaxSteps` | N/A | PASS |
| 12 | 多用户 Session 隔离 | Sessions keyed by (user_id, session_id); cross-session/cross-user leak tests = 0 leaks | `src/session.py:22-29` | `test_round10a.py::TestDatabaseIsolation` | Real LLM isolation checks passed | PASS |
| 13 | 跨进程恢复 | `SQLiteSessionStore` persists/loads sessions from SQLite DB file | `src/sqlite_session.py` | `test_sqlite_session.py` (23 tests) | CLI: close and reopen with same session_id → todos restored | PASS |
| 14 | 纯对话追问 | Session history preserved; LLM sees full context in `build_messages()` | `src/context_manager.py:132-153` | `test_context_manager.py::TestBuildMessages` | CLI: "My name is X" ... "What is my name?" | PASS |
| 15 | 带工具追问 | Tool results stored alongside messages; LLM can reference previous tool output | `src/agent.py:239-246` | `test_all.py::TestMultiToolSequence` | CLI: "Add todo: milk" ... "List todos" | PASS |
| 16 | Context 内容选择 | `build_messages()` = system prompt + session summary + recent messages; summary injected as 2nd system message | `src/context_manager.py:132-153` | `test_context_manager.py::TestBuildMessages` | N/A | PASS |
| 17 | 基础压缩 | `_find_compress_boundary` → `_summarize_messages` → `_merge_summary` → trim messages; tool calls never split from results | `src/context_manager.py:83-130` | `test_context_manager.py` (39 tests), `test_round10b.py` | `scripts/run_context_edge_replay.py` (zero API) | PASS |
| 18 | Hybrid 语义摘要 + 回退 | `summary_mode="hybrid"` → `QwenSemanticSummarizer` → deterministic fallback on failure; `last_compression_event` tracks metadata | `src/context_summarizer.py`, `src/context_manager.py:110-178` | `test_round10b.py` (29 tests), `scripts/demo_hybrid_context.py` | Hybrid real run: semantic calls attempted, fallback works | PASS |
| 19 | 异常处理 | `LLMAuthenticationError`, `LLMRateLimitError`, `LLMTimeoutError`, `LLMServiceError`, `LLMResponseParseError`, `InvalidLLMResponseError`, `MaxStepsExceededError`, tool errors | `src/qwen_client.py:13-31`, `src/agent.py:22-31` | `test_agent.py::TestErrorHandling`, `test_qwen_client.py` | N/A | PASS |
| 20 | Trace | `TraceStep` dataclass records step_number, event_type, tool_call_id, decision_summary, observation, success, error_type, duration_ms | `src/trace.py` | `test_agent.py::TestTracing` | `python -m src.cli /trace` | PASS |
| 21 | 自动测试 | 270 tests across 11 test modules, plus 2 skipped (real API tests) | `tests/*.py` | N/A | `pytest` → 270 passed | PASS |
| 22 | 真实 LLM API | `OpenAICompatibleLLMClient` connects to qwen3.6-plus via DashScope OpenAI-compatible endpoint | `src/qwen_client.py:86-144` | `test_real_qwen.py` (skipped without key) | Real runs completed (quota exhausted at time of final audit) | PASS |
| 23 | README | `README.md` at project root — architecture, features, quick start, CLI, tests, boundaries | `README.md` | N/A | Renders on GitHub | PASS |
| 24 | 录屏脚本 | `scenarios/recording-demo.txt` + `docs/recording-script.md` with step-by-step instructions | `scenarios/recording-demo.txt`, `docs/recording-script.md` | N/A | Follow `recording-script.md` for 5-8 min demo | PASS |
| 25 | AI Prompt 与问题解决记录 | `docs/ai-development-log.md` — all rounds, prompts, issues, fixes, fake vs real distinction | `docs/ai-development-log.md` | N/A | Contains Round 1-11 entries | PASS |

## 备注

- **真实 LLM 配额**：DashScope 免费配额在最终验证时已耗尽。代码已通过早期运行（第 8 轮验证、之前的上下文基线）使用真实的 qwen3.6-plus 验证。所有自动化测试无需 API 依赖即可通过。
- **上下文基线指标**：早期运行的有缺陷的报告数据原样保留在 `reports/context-deterministic/` 和 `reports/context-hybrid/` 中。指标计算代码已修复，但因配额耗尽无法生成新报告。
- **探针评分器**：探针 2（截止时间）评分器已修复 —— 移除了导致假阴性的冗余 `"10"` 关键词。探针 9（待办）评分器已修复 —— 将 `"READ ME"` 修正为 `"README"` 关键词。两项修复均针对评分器假阴性，而非模型正确性。
