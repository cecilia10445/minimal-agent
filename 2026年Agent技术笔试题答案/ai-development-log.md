# AI Development Log

## Round 2 — Agent Runtime

### 新增文件

| File | Purpose |
|---|---|
| `src/llm.py` | `ToolCall` / `LLMResponse` dataclass, `LLMClient` Protocol, `ScriptedLLMClient` |
| `src/trace.py` | `TraceStep` dataclass for recording each step |
| `src/prompt.py` | `SYSTEM_PROMPT` string |
| `src/agent.py` | `AgentRuntime`, `AgentResult`, `InvalidLLMResponseError`, `MaxStepsExceededError` |
| `tests/test_agent.py` | 24 tests covering all agent scenarios |
| `docs/ai-development-log.md` | this file |

### 未修改现有代码

- `src/tool.py` — unmodified
- `src/context.py` — unmodified
- `src/session.py` — unmodified (note: `Session.messages` typed `list[dict[str, str]]` but stores `dict[str, Any]` at runtime; works fine, cosmetic only)
- `src/registry.py` — unmodified
- `src/tools/*.py` — unmodified
- `tests/conftest.py` — unmodified
- `tests/test_all.py` — unmodified

### Agent Loop 实际执行流程

```
run(user_id, session_id, user_input)
  │
  ├─ validate inputs (non-empty)
  ├─ get_or_create Session
  ├─ append user message to session.messages
  │
  └─ for step in 1..max_steps:
       │
       ├─ build messages = [system, ...session.messages]
       ├─ export tool schema from registry
       ├─ call llm_client.complete(messages, tools)
       │
       ├─ [A] tool_calls non-empty ──
       │   ├─ append assistant msg with tool_calls to session
       │   ├─ for each tool_call:
       │   │   ├─ ToolContext(user_id, session_id, store)
       │   │   ├─ tool_registry.execute(ctx, name, args)
       │   │   ├─ success → observation = {"ok":true, "result":...}
       │   │   └─ error   → observation = {"ok":false, "error_type":..., "message":...}
       │   ├─ append tool msg to session
       │   └─ continue loop
       │
       ├─ [B] content non-empty ──
       │   ├─ append assistant msg to session
       │   ├─ record final_answer trace
       │   └─ return AgentResult
       │
       └─ [C] empty content + no tool_calls ──
           ├─ record llm_error trace
           └─ raise InvalidLLMResponseError
       │
  └─ loop exhausted ──
      ├─ record max_steps_exceeded trace
      └─ raise MaxStepsExceededError
```

### 消息格式示例

**User message:**
```json
{"role": "user", "content": "Calculate 12 * 8"}
```

**Assistant with tool call:**
```json
{
  "role": "assistant",
  "content": null,
  "tool_calls": [
    {
      "id": "call_1",
      "type": "function",
      "function": {"name": "calculator", "arguments": "{\"expression\": \"12 * 8\"}"}
    }
  ]
}
```

**Tool result:**
```json
{
  "role": "tool",
  "tool_call_id": "call_1",
  "name": "calculator",
  "content": "{\"ok\": true, \"result\": \"96\"}"
}
```

**Final answer:**
```json
{"role": "assistant", "content": "12 * 8 = 96"}
```

### 异常恢复方式

| 异常类型 | 处理方式 |
|---|---|
| `ToolNotFoundError` | 捕获，转为 `{"ok":false,"error_type":"ToolNotFoundError","message":"..."}`，作为 tool message 放回对话，Runtime 继续运行 |
| `ToolParameterError` | 同上 |
| `ToolExecutionError` | 同上 |
| `InvalidLLMResponseError` | 直接抛出，不自动恢复（属于致命错误） |
| `MaxStepsExceededError` | 循环结束后抛出，附带 Trace |
| `ScriptedLLMClient` 耗尽 | `RuntimeError` 抛出 |
| `ValueError` (输入校验) | 立即抛出 |

### 关键设计选择

1. **LLMClient 使用 Protocol**：Runtime 只依赖 `LLMClient` 协议，不绑定任何具体 SDK；接入真实 LLM 只需实现 `complete()` 方法。
2. **ScriptedLLMClient 确定性测试**：预设响应列表，顺序返回；保存 `call_history` 供测试断言 Context 内容。
3. **ToolContext 由 Runtime 注入**：LLM 无法通过工具参数选择或覆盖 session_id。
4. **Trace 存储为 dict**：通过 `dataclasses.asdict(TraceStep)` 转为 dict 后存入 `session.traces`，避免序列化耦合。
5. **工具结果统一 JSON 包装**：成功为 `{"ok":true,"result":"..."}`，失败为 `{"ok":false,"error_type":"...","message":"..."}`。
6. **异步同步**：当前使用同步调用，后续可替换为 async LLMClient。

### 测试失败与修复记录

| 失败 | 原因 | 修复 |
|---|---|---|
| 23 个 test_agent 测试失败 | `_make_runtime` 直接调用 pytest fixture `fixture_registry()` | 改为独立的 `_build_registry()` 工厂函数 |
| `test_second_run_sees_history` | 断言消息数为 3，实际历史包含前一轮 assistant 响应共 4 条 | 修复断言值为 4，roles 验证包含 `["system","user","assistant","user"]` |
| `test_trace_fields` / `test_error_trace_has_error_type` | `result.traces` 返回 dict 而非 TraceStep 对象（AgentResult 类型标注 `list[TraceStep]` 与实际不匹配） | 修正 AgentResult.traces 类型为 `list[dict[str, Any]]`，测试改用 dict 风格访问 |

### 测试数量与结果

- 原有 tests/test_all.py: **24 passed**
- 新增 tests/test_agent.py: **24 passed**
- 合计: **48 passed, 0 failed** (0.18s)

### 本轮未实现内容

- 真实 LLM API 调用
- Context 长度估算与压缩
- 长期 Memory / 数据库 / 向量存储
- CLI / Web 界面
- 真正网络搜索
- README 文档
- MCP / 文件修改 / Shell 工具

### 下一阶段接入真实 LLM 需要实现的接口

1. 实现 `LLMClient` 协议的具体类（如 `OpenAIClient`），对接 OpenAI / DeepSeek / Qwen 等 API
2. 处理 API 认证（环境变量管理 API Key）
3. 处理 API 错误（超时、限流、上下文超长）
4. 可选：Context 压缩策略（滑动窗口、摘要等）
5. 将 `ScriptedLLMClient` 替换为真实 client 进行集成测试

---

## Round 3 — 阿里云百炼 qwen3.6-plus 接入 + CLI

### 修改文件

| 文件 | 操作 |
|---|---|
| `pyproject.toml` | 增加 `openai>=1.0,<2.0`、`python-dotenv>=1.0,<2.0` 依赖 + pytest markers |
| `src/session.py` | 增加 `list_user_sessions(user_id)` 方法 |
| `.env.example` | 新增 — 环境变量模板 |
| `.gitignore` | 新增 — 忽略 `.env` |
| `src/config.py` | 新增 — `LLMSettings` frozen dataclass + `load_llm_settings()` 安全布尔解析 |
| `src/qwen_client.py` | 新增 — `OpenAICompatibleLLMClient` 实现 `LLMClient` 协议，异常体系 |
| `src/bootstrap.py` | 新增 — `build_default_registry()` 集中注册 6 个工具 |
| `src/cli.py` | 新增 — 交互终端（`/help`、`/new`、`/sessions`、`/switch`、`/trace`、`/history`、`/quit`） |
| `tests/test_qwen_client.py` | 新增 — 17 个 Mock 测试覆盖适配器全部路径 |
| `tests/test_real_qwen.py` | 新增 — 2 个集成测试（默认 `@pytest.mark.real_llm`，自动跳过） |

**未修改文件：** `src/tool.py`、`src/context.py`、`src/registry.py`、`src/trace.py`、`src/llm.py`、`src/agent.py`、`src/prompt.py`、`src/tools/*`、`tests/test_all.py`、`tests/test_agent.py`、`tests/conftest.py`

### 完整 Prompt

```text
You are a personal work assistant that helps users complete tasks.

You can either answer directly or call tools to get information. When you need
external information, local documents, precise calculations, or todo operations,
use the appropriate tools.

After a tool returns a result, use the result to decide whether to call another
tool or give a final answer. Do not fabricate tool execution results.

When you have enough information to answer the user's question, stop calling
tools and provide the final answer.

You may include a brief decision summary before your response, but do not output
a full chain-of-thought.

The runtime has a maximum step limit, so avoid unnecessary repeated tool calls.
```

保存在 `src/prompt.py`，由 AgentRuntime 注入为 system message。工具 Schema 由 ToolRegistry 动态导出。

### 为什么选择 OpenAI-compatible 适配层

百炼兼容模式（`/compatible-mode/v1`）提供标准 OpenAI API 接口，使用 `openai` SDK 即可调用千问模型，无需依赖 `dashscope` 等阿里云专属 SDK。设计上 `OpenAICompatibleLLMClient` 不绑定任何特定厂商，`base_url` 由环境变量控制，未来可切换到其他 OpenAI-compatible 服务。

### 为什么模型只负责决策、Runtime 负责执行

严格遵循 Tool Call 分离原则：LLM 输出 tool_calls 后，由 AgentRuntime 在当前循环步内遍历执行每个工具，统一包装结果（JSON `{"ok":true/false,...}`），放回对话后再次请求 LLM。

适配器（`qwen_client.py`）的 `complete()` 只做请求→响应转换：

```
SDK response
  → choices[0].message
  → 解析 content / tool_calls
  → LLMResponse(content, tool_calls=[ToolCall(id, name, arguments)])
```

不在适配器中执行工具或发起第二轮调用。

### 为什么关闭 thinking

`enable_thinking=false` 避免模型输出完整思维链，减少 Token 消耗。`decision_summary` 字段仅取模型返回的前 200 字符自然语言作为可选摘要，Runtime 不依赖此字段。

### API 响应到内部 LLMResponse 的映射

| 字段 | 来源 |
|---|---|
| `content` | `message.content`（保留 None，不伪造） |
| `tool_calls` | 遍历 `message.tool_calls`，每个转为 `ToolCall(id, name, arguments)` |
| `arguments` | `json.loads(tc.function.arguments)`，必须为 JSON object |
| `decision_summary` | `content[:200]`（仅在 content 非空时）；Runtime 不依赖 |

### 异常映射

| OpenAI SDK 异常 | 项目内部异常 |
|---|---|
| `AuthenticationError` | `LLMAuthenticationError` |
| `RateLimitError` | `LLMRateLimitError` |
| `APITimeoutError` | `LLMTimeoutError` |
| `APIConnectionError` | `LLMServiceError` |
| `APIStatusError` | `LLMServiceError` |
| 其他 `OpenAIError` | `LLMServiceError`（保留异常链） |
| arguments 非法 JSON | `LLMResponseParseError` |
| arguments 非 object | `LLMResponseParseError` |
| choices 为空 | `LLMResponseParseError` |

异常信息不泄露 API Key、不包含完整请求 headers。

### 遇到的兼容问题

1. **`return ... from exc` 语法错误**：`_map_openai_error` 试图用 `return our_type(msg) from exc`，Python 不支持 `return ... from`，改为 `return our_type(msg)`（已在 raise 处保留 `from e`）。
2. **Mock SDK 的链式调用**：OpenAI SDK 1.x 使用 `client.chat.completions.create()`，MockSDK 需要嵌套 `MockChat` → `MockCompletions` 对象来模拟调用链。
3. **OpenAI 1.x 异常构造函数要求 `httpx.Response`**：`AuthenticationError`、`RateLimitError`、`APIStatusError` 等需要 `response: httpx.Response` 和 `body` 参数，不能传 `None`。使用 `unittest.mock.MagicMock` 构造 fake response。

### 测试失败与修复

| 失败 | 原因 | 修复 |
|---|---|---|
| 2 个 test_* 文件 import 失败 | `_map_openai_error` 中 `return ... from exc` 语法错误 | 改为 `return our_type(msg)` |
| 4 个 API 错误测试 | OpenAI 1.x 异常要求真实 `httpx.Response`，`response=None` 导致 `AttributeError` | 使用 `MagicMock` 构造 fake response |

### 是否真正执行了 API 集成测试

**否**。当前环境未配置 `DASHSCOPE_API_KEY`，`tests/test_real_qwen.py` 的两个 `@pytest.mark.real_llm` 测试自动跳过。

本机执行命令：
```powershell
# 1. 复制环境变量模板并填入真实 Key
cp .env.example .env
# 编辑 .env，填入 DASHSCOPE_API_KEY

# 2. 运行 Mock 测试（无需 Key，必须全部通过）
pytest

# 3. 运行真实 API 测试
$env:RUN_REAL_LLM_TESTS="1"; pytest -m real_llm -v

# 4. 启动 CLI
python -m src.cli
```

### CLI 使用方式

```
python -m src.cli
```

支持的斜杠命令：

| 命令 | 作用 |
|---|---|
| `/new` | 创建并切换到新 Session |
| `/sessions` | 列出当前用户的所有 Session |
| `/switch <id>` | 切换到指定 Session |
| `/trace` | 显示当前 Session 的 Trace |
| `/history` | 显示当前 Session 简化消息历史 |
| `/help` | 帮助 |
| `/quit` | 退出 |

普通文本发送给 AgentRuntime。异常显示友好消息（不打印 Python 堆栈），程序保持可继续输入。

### 测试最终结果

```
65 passed, 2 skipped in 1.06s
```

- tests/test_all.py: 24 passed
- tests/test_agent.py: 24 passed
- tests/test_qwen_client.py: 17 passed
- tests/test_real_qwen.py: 2 skipped (RUN_REAL_LLM_TESTS not set)

### 本轮未实现内容

- 真实 LLM API 集成测试（未配置 Key，无法执行）
- Context 长度估算与压缩
- 长期 Memory / 数据库 / 向量存储
- 真正网络搜索
- MCP / 文件修改 / Shell 工具
- 流式输出
- 并行工具执行

---

## Round 4 — CLI Trace 修复 + 搜索模拟数据补全

### 问题

1. **CLI Trace 展示**：`AgentRuntime.run()` 返回的 `AgentResult.traces` 是 `list(session.traces)`，即 Session 的全部累计 trace。多次请求后 Step 1、Step 2 混合在一起无法区分。
2. **模拟搜索未命中**：用户搜索 "Agent Runtime" 时 mock 数据中不包含该条目，返回 "No results found."。

### 修复方案

| 文件 | 修改内容 |
|---|---|
| `src/trace.py` | `TraceStep` 新增 `run_id: int = 0` 字段 |
| `src/agent.py` | 新增 `_run_counter`，每次 `run()` 递增并传给所有 TraceStep；记录 `trace_start` 在返回 `AgentResult` 时只返回本次新增的 trace 切片 `session.traces[trace_start:]`；`MaxStepsExceededError` 和 `InvalidLLMResponseError` 现在携带 `traces` 属性 |
| `src/tools/search.py` | `_MOCK_DATA` 新增 `"agent runtime"`、`"function calling"`、`"context management"` 三条稳定演示数据 |
| `src/cli.py` | 普通对话后 `_print_traces(result)` 使用 `result.traces`（仅本次）；`/trace` 命令按 `run_id` 分组输出；`MaxStepsExceededError` 处理使用 `e.traces` 代替全量 session.traces |
| `tests/test_all.py` | `TestSearch` 新增 4 个测试：Agent Runtime 大小写命中、Function Calling、Context Management 大小写不敏感 |
| `tests/test_agent.py` | 新增 `TestRunTraceIsolation.test_second_run_traces_do_not_include_first_run` 验证两个连续 run 返回的 traces 各自只有 1 条，而 session.traces 累计为 2 条 |

### 关键设计

- **run_id**：`AgentRuntime` 内部计数器，每次 `run()` 递增，注入到所有 TraceStep。0 为默认值（不影响已有 trace）。
- **trace 切片**：`run()` 开始时记录 `trace_start = len(session.traces)`，结束时返回 `session.traces[trace_start:]`。
- **异常携带 traces**：`MaxStepsExceededError` 和 `InvalidLLMResponseError` 构造函数接受 `traces` 参数，CLI 可直接使用 `e.traces`。
- **搜索匹配逻辑不变**：仍为 `query in key.lower()`，大小写不敏感的子串包含匹配。

### 测试结果

```
70 passed, 2 skipped in 1.13s
```

- 原有 48 个测试继续通过
- 新增 5 个测试（4 search + 1 trace isolation）通过
- 编译检查通过

---

## Round 5 — Context 压缩与 Session 摘要

### 新增文件

| 文件 | 说明 |
|---|---|
| `src/context_manager.py` | `ContextPolicy` 配置、`ContextManager`（prepare_session / build_messages）、`estimate_tokens`、`_find_compress_boundary`、`_summarize_messages`、`_merge_summary`、`_truncate` |
| `tests/test_context_manager.py` | ~39 个测试，覆盖 estimate_tokens、压缩边界、摘要生成、合并、prepare_session（含阈值、保留轮次、并行 tool_call、隔离性）、build_messages、Runtime 集成 |

### 修改文件

| 文件 | 修改 |
|---|---|
| `src/session.py` | 字段不变 |
| `src/agent.py` | 导入 ContextManager，`__init__` 新增 `context_manager` 参数，`run()` 调用 `prepare_session()` 和 `build_messages()` |
| `src/cli.py` | 新增 `/memory` 命令，显示 summary 状态、消息数、估算 token |

### Context 压缩流程

1. `prepare_session(session)`：
   - 估算当前 session.messages token 数
   - 若超过阈值 → `_find_compress_boundary()` 找到需要压缩的边界（保留最近 N 个 user turn）
   - 边界内消息 → `_summarize_messages()` 生成摘要条目
   - `_merge_summary()` 合并到已有 summary
   - 保留最近 N 个 user turn 的消息
2. `build_messages(system_prompt, session)`：
   - system message
   - 若有 summary → 额外 system message（"Session memory summary..."）
   - session.messages 中的历史消息

### 测试结果

```
108 passed, 2 skipped in 1.62s
```

### 本轮未实现

- SQLite 持久化
- 多用户隔离
- Context Policy 环境变量配置

---

## Round 6 — Session 跨进程持久化、用户隔离、Context 压缩演示

### Prompt 摘要

实现 Session 跨进程持久化（SQLite）、逻辑用户隔离、CLI 用户/Session 参数、Context Policy 环境变量配置、零 API Context 压缩演示脚本。

### 修改文件清单

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/session.py` | 修改 | 新增 `save()` 方法；`list_user_sessions` 返回 `list[Session]` |
| `src/sqlite_session.py` | 新增 | SQLiteSessionStore，带内存缓存 |
| `src/config.py` | 修改 | 新增 `load_context_policy()`，导入 `ContextPolicy` |
| `src/agent.py` | 修改 | 新增 `_save_session()` 辅助方法；在 prepare_session、user msg、assistant tool_call、tool result、final answer、trace、异常前调用 |
| `src/cli.py` | 重写 | 新增 argparse（`--user-id`、`--session-id`、`--db-path`）；默认使用 SQLiteSessionStore；新增 `/whoami`；`/sessions` 适配新返回类型；启动时显示 user_id/session_id/db_path |
| `tests/test_sqlite_session.py` | 新增 | 23 个测试（基础持久化 16 + Runtime 集成 7） |
| `scripts/demo_context_compression.py` | 新增 | 零 API Context 压缩演示脚本 |

### 未修改文件

`src/tool.py`、`src/context.py`、`src/registry.py`、`src/trace.py`、`src/llm.py`、`src/prompt.py`、`src/tools/*`、`src/context_manager.py`（核心压缩规则不变）、`src/session.py`（Session 字段不变）、`src/qwen_client.py`、`src/bootstrap.py`、`tests/conftest.py`、`tests/test_all.py`、`tests/test_agent.py`、`tests/test_context_manager.py`、`tests/test_qwen_client.py`、`tests/test_real_qwen.py`

### SQLite 表结构

```sql
CREATE TABLE IF NOT EXISTS sessions (
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, session_id)
);
```

### Session 序列化格式

`state_json` 保存为 JSON 字符串，包含四个字段：

```json
{
    "messages": [
        {"role": "user", "content": "..."},
        {"role": "assistant", "tool_calls": [...]},
        {"role": "tool", "tool_call_id": "...", "name": "...", "content": "..."}
    ],
    "summary": "- 用户请求：...\n- 助手回答：...",
    "todos": [{"id": 1, "content": "Buy milk", "done": false}],
    "traces": [{"step_number": 1, "event_type": "tool_call", "run_id": 1, ...}]
}
```

所有 Python datetime/dataclass 等非 JSON 原生类型使用 `default=str` 安全序列化。使用 `ensure_ascii=False` 保留中文。

### 持久化保存时机

AgentRuntime 在以下时机调用 `_save_session(session)` → `session_store.save(session)`：

1. `prepare_session()` 完成后（可能更新 summary）
2. user message 追加后
3. assistant tool_call message 追加后
4. 每个 tool result 追加后
5. final answer 追加后（消息 + trace 分别保存）
6. InvalidLLMResponseError 抛出前
7. MaxStepsExceededError 抛出前（消息 + trace 分别保存）
8. except 块中异常重抛前

### 用户和 Session 隔离方式

- `SQLiteSessionStore` 以 `(user_id, session_id)` 作为复合主键
- 同一 `user_id` 不同 `session_id` 完全隔离
- 不同 `user_id` 即使使用相同 `session_id` 也完全隔离
- `list_user_sessions(user_id)` 只返回指定用户的 sessions
- `AgentRuntime` 不依赖 store 实现细节，只通过统一接口调用

### CLI 启动参数

```powershell
python -m src.cli --user-id user-a --session-id window-1
python -m src.cli --user-id user-a --session-id window-2
python -m src.cli --user-id user-b --session-id window-1 --db-path custom/path.db
```

默认值：`user_id=local-user`、`session_id=default`、`db_path=data/agent_sessions.db`

新增斜杠命令：

| 命令 | 作用 |
|---|---|
| `/whoami` | 显示当前 user_id、session_id、db_path |

### Context Policy 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `AGENT_CONTEXT_MAX_TOKENS` | 6000 | 触发压缩的 token 阈值 |
| `AGENT_CONTEXT_KEEP_RECENT_TURNS` | 4 | 保留的最近用户轮次数 |
| `AGENT_CONTEXT_MAX_SUMMARY_CHARS` | 3000 | 摘要最大字符数 |
| `AGENT_CONTEXT_MAX_ITEM_CHARS` | 300 | 单条摘要条目最大字符数 |

非法值（空、非整数、零/负数）抛出 `LLMConfigurationError`。

### Context 演示输出

```text
=== Context Compression Demo (zero API calls) ===

Policy: max_estimated_tokens=1, keep_recent_user_turns=1
Before compression:
  Messages: 17
  Estimated tokens: 434
  Summary length: 0 chars
  Summary: ''

Compression triggered: True

After compression:
  Messages: 2
  Estimated tokens: 33
  Kept 1 recent user turn(s)
  User turns remaining: 1
  Summary length: 513 chars
No orphan tool messages or missing results.
```

### 测试失败与修复

| 失败 | 原因 | 修复 |
|---|---|---|
| 6 个 test_context_manager 测试 | `keep_recent_user_turns` 默认 4 大于测试构造的轮次数，`_find_compress_boundary` 返回 0 | 测试 policy 增加 `keep_recent_user_turns=1` |
| test_parallel_tool_calls_preserved | 断言 `len == 6` 但消息实际为 5 | 修复断言为 `== 5` |
| test_todo_after_compress_still_accessible | 函数体内局部 `from src.context_manager import ContextManager` 与模块级导入冲突，导致 `UnboundLocalError` | 删除冗余局部 import |
| test_llm_receives_summary_after_compress | 2 次 run 只产生 2 个 user turn，`keep=1` 下 boundary=0 | 改为 3 次 run |
| test_runtime_persists_then_new_runtime_recovers | `todo_add` 工具通过 `ToolContext.store.get_or_create()` 获得**不同** Session 对象，修改未在 Runtime 的 session 中体现 | `SQLiteSessionStore` 增加内存缓存，`get_or_create/get` 返回缓存的同一 Python 对象 |
| test_corrupted_json_raises_error | 缓存优先返回未损坏对象，不重新读取数据库 | 测试改用新 store 实例绕过缓存 |

### 测试数量与结果

```
tests/test_all.py             24 passed
tests/test_agent.py           24 passed
tests/test_qwen_client.py     17 passed
tests/test_context_manager.py 39 passed
tests/test_sqlite_session.py  23 passed   (16 基础 + 7 集成)
tests/test_real_qwen.py        2 skipped
────────────────────────────────────────────
Total: 130 passed, 2 skipped (2.05s)
```

编译检查通过（`python -m compileall src tests scripts`）。

### 是否完成跨进程恢复

**是**。CLI 关闭后重新启动，使用相同 `--user-id` 和 `--session-id` 可恢复 messages、summary、todos、traces。不同进程使用同一数据库文件时，`SQLiteSessionStore` 使用 SQLite 并发访问（`check_same_thread=False`），最后写入覆盖。

### 尚未实现的交付内容

- 密码登录、注册系统、JWT（明确不实现）
- Web 页面（明确不实现）
- 向量数据库、Embedding、跨 Session 自动召回（明确不实现）
- 流式输出
- MCP 工具
- 多 Agent
- 分布式并发版本控制或悲观锁

---

## Round 7 — 本地知识文档链路修复（list_docs / search_docs / read_docs）

### 人工发现的问题

1. 新加入 `knowledge_docs/唯一测试文档.md` 后，明确指定文件名可以通过 `read_docs` 读取。
2. 在本地文档中搜索"紫色河马987"时，模型错误调用了通用 `search` 而不是本地文档搜索。
3. 全新 Session 询问"当前有哪些本地文档"时，模型无法列出目录。
4. 旧 Session 可以列出以前读过的文件，但没有调用工具，只是在使用历史记忆。
5. 旧 Session 对"当前文件列表"的回答可能过时。

### 为什么拆为三个工具

原先只有一个 `read_docs`，缺乏目录列举和全文检索能力，导致模型不得不用通用 `search` 模拟本地检索。拆为 `list_docs`、`search_docs`、`read_docs` 后，每个工具的职责单一清晰，LLM 根据 Schema 和 System Prompt 的 routing rules 自主选择正确的工具，不再混用通用 search。

### Memory 与动态外部状态的区别

Session Memory 表示"过去读过、搜索过什么"，代表历史快照。磁盘上的文件状态是动态的，随时可能变化（新增、删除、修改）。System Prompt 明确要求：当两者冲突时，以当前工具结果为准。LLM 必须调用工具获取当前状态，不能凭记忆回答文件列表。

### 修改文件清单

| 文件 | 操作 | 说明 |
|---|---|---|
| `src/tools/list_docs.py` | 新增 | 列出 knowledge_docs 中所有 .md 文件 |
| `src/tools/search_docs.py` | 新增 | 在 knowledge_docs 文件名和正文中搜索关键词 |
| `src/tools/read_docs.py` | 重写 | 增强模糊匹配、自动补全 .md、截断、JSON 返回格式 |
| `src/prompt.py` | 修改 | 新增 8 条工具路由规则 |
| `src/bootstrap.py` | 修改 | 注册 ListDocsTool、SearchDocsTool |
| `tests/conftest.py` | 修改 | 注册新工具 |
| `tests/test_agent.py` | 修改 | `_build_registry` 注册新工具 |
| `tests/test_sqlite_session.py` | 修改 | `_build_registry` 注册新工具 |
| `tests/test_docs_tools.py` | 新增 | 39 个测试 |
| `scripts/demo_docs_agent.py` | 新增 | 真实 qwen3.6-plus 端到端演示脚本 |

### 未修改文件

`src/tool.py`、`src/context.py`、`src/registry.py`、`src/trace.py`、`src/llm.py`、`src/agent.py`（未修改 Agent Loop）、`src/context_manager.py`、`src/session.py`、`src/qwen_client.py`、`src/config.py`、`src/sqlite_session.py`、`src/cli.py`、`src/tools/search.py`、`src/tools/calculator.py`、`src/tools/todo.py`、`tests/test_all.py`、`tests/test_context_manager.py`、`tests/test_qwen_client.py`、`tests/test_real_qwen.py`、`tests/conftest.py`（仅新增 import）

### 三个文档工具的职责

| 工具 | 职责 | 何时调用 |
|---|---|---|
| `list_docs` | 列出 knowledge_docs 目录当前存在的 Markdown 文档 | 用户询问当前有哪些、全部有哪些、是否存在某类本地文档 |
| `search_docs` | 在 knowledge_docs 全部 Markdown 文件名和正文中搜索关键词 | 要求在本地文档、知识库或资料中查找某词、主题或内容 |
| `read_docs` | 读取一个指定 Markdown 文档 | 已有明确文件名，或通过 list_docs/search_docs 找到候选后 |

### 实际 Schema

**list_docs:**
```json
{
  "name": "list_docs",
  "description": "列出本地 knowledge_docs 知识库中当前存在的所有 Markdown 文档。...",
  "parameters": {"type": "object", "properties": {}, "additionalProperties": false}
}
```

**search_docs:**
```json
{
  "name": "search_docs",
  "description": "在本地 knowledge_docs 知识库的所有 Markdown 文件名和正文中搜索关键词。...",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {"type": "string"},
      "top_k": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5}
    },
    "required": ["query"],
    "additionalProperties": false
  }
}
```

**read_docs:**
```json
{
  "name": "read_docs",
  "description": "读取本地 knowledge_docs 中的一个指定 Markdown 文档。...",
  "parameters": {
    "type": "object",
    "properties": {
      "filename": {"type": "string"}
    },
    "required": ["filename"],
    "additionalProperties": false
  }
}
```

### 动态扫描机制

三个工具每次 `execute()` 时都调用 `os.listdir()` 重新扫描 `knowledge_docs` 目录，不在工具初始化阶段或类级别缓存文件列表。新增或删除文件后，下一次工具调用立即反映磁盘实际状态。

### System Prompt 路由规则

1. 用户询问当前有什么本地文档 → 必须调用 `list_docs`
2. 要求在本地文档中搜索关键词 → 必须调用 `search_docs`
3. 有明确文件名要查看内容 → 调用 `read_docs`
4. 通用 `search` 只用于模拟外部公开资料搜索，不能用于本地 knowledge_docs 检索
5. 会话记忆表示过去的信息；涉及当前本地文档状态时，必须重新调用工具
6. 当前工具结果与历史记忆冲突时，以当前工具结果为准
7. 不得编造不存在的文件名或文档内容
8. search_docs 返回候选后，如用户要求具体内容，可以继续调用 read_docs

### 测试失败与修复

| 失败 | 原因 | 修复 |
|---|---|---|
| `test_path_traversal_rejected` | `..` 检查在 `.md` 检查之后，`../pyproject.toml` 先触发 `.md` 拒绝 | 交换检查顺序，先拦路径穿越 |
| `test_ambiguous_filename_returns_candidates` | `filename="guide"` 自动补全 `.md` 后精确匹配 `guide.md`，未返回多候选 | 使用 `alpha_v1.md` / `alpha_v2.md` 避免精确匹配；`_find_candidates` 使用 `stem` 做子串匹配 |
| `test_knowledge_base_accessible_across_users` | ScriptedLLMClient 只有 1 个 response 但需要 2 次调用 | 增加至 2 个 response |

### 测试数量与结果

```
tests/test_all.py             24 passed
tests/test_agent.py           24 passed
tests/test_qwen_client.py     17 passed
tests/test_context_manager.py 39 passed
tests/test_sqlite_session.py  23 passed
tests/test_docs_tools.py      37 passed   (8 list + 11 search + 7 read + 3 schema + 8 integration)
tests/test_real_qwen.py        2 skipped
────────────────────────────────────────────
Total: 167 passed, 2 skipped (2.46s)
```

### 是否执行真实 Qwen 演示

**否** — 当前环境未配置 `DASHSCOPE_API_KEY`，无法运行 `scripts/demo_docs_agent.py`。当环境已配置时，执行命令：

```powershell
$env:RUN_REAL_LLM_TESTS="1"; python scripts/demo_docs_agent.py
```

预计输出：
- Round 1: `list_docs` 列出包含 `__agent_dynamic_demo__.md` 的文档列表
- Round 2: `search_docs` 搜索"蓝色鲸鱼2468"并定位到该文件
- Round 3: `read_docs` 读取内容说明"验证 Agent 在不重启的情况下发现新加入的本地知识文档"

### 正确调用 list_docs / search_docs / read_docs

确定性测试（ScriptedLLMClient）验证了：
- `test_list_docs_result_in_context`: list_docs 调用 → tool msg 写入 context ✓
- `test_search_docs_then_read_docs_sequence`: search_docs → read_docs 连续两轮 ✓
- `test_tool_call_trace_correct`: 工具名和 event_type 正确 ✓
- `test_tool_error_observation_returns_to_model`: 错误 observation 回填模型 ✓

### 人工 CLI 验收命令

```powershell
# 全新 Session，验证工具路由
python -m src.cli --user-id docs-test-user --session-id fresh-doc-routing

# 建议输入：
#   目前本地知识库中有哪些文档？
#   请在本地文档中搜索"HiveServer2"。
#   请读取搜索到的文档并总结故障原因。

# 然后在 CLI 运行期间新建 Markdown 文件：
# 新开一个终端：
# echo "# New Doc" > knowledge_docs/live_test.md

# 回到 CLI 输入：
#   当前有哪些本地文档？
```

---

## Round 8 — 文档链路质量收口与测试资产建设

### 本轮回合 Prompt

本轮回合不新增业务工具。目标：修复人工测试暴露的 4 个行为缺陷，增强 System Prompt，增加 long doc truncation 元数据，建立完整测试资产（manual test plan、machine-readable scenarios、real-LLM scenario runner、inspection script）。

### 人工测试确认的 4 个缺陷

| # | 缺陷 | 人工输入 | 预期 | 实际 |
|---|---|---|---|---|
| 1 | 动态状态被历史工具结果覆盖 | 删除文件后问"现在本地知识库有哪些文档？" | 必须重新调用 list_docs | Agent 基于上一轮结果回答旧列表 |
| 2 | 显式文件名被旧 Session 记忆替换 | "读取 JavaScript介绍.md"（旧 Session 曾读过 `介绍.md`） | 忠实传递 `JavaScript介绍.md` | 被替换为历史 `介绍.md` |
| 3 | 相同无结果搜索重复调用 | "搜索公开资料中 Agent Runtime 的一般定义"（mock 无结果） | 不立即重复 | search 被调用 3 次 |
| 4 | 长文档截断未向用户披露 | 读取 115 KB 文档 | 说明只读了部分 | 未提及截断，遗漏尾部标识码 |

### 修复方式

**1. System Prompt 增强** (`src/prompt.py`)

新增 `--- Dynamic State & Freshness Rules ---` 小节（规则 9-13），明确要求：

- 规则 9：用户询问当前/现在/目前/现有/全部/最新/数量时，**每次**都必须重新调用 list_docs
- 规则 10：用户提供的显式文件名必须忠实传递，不得替换；多候选时返回候选让用户选择
- 规则 11：同一工具相同参数已返回空结果时，不得立即重复调用
- 规则 12：工具结果含 `truncated: true` 时，最终回答必须声明只读取了部分内容
- 规则 13：当前工具结果与 Session Memory 冲突时，以工具结果为准

**2. read_docs 返回字段增强** (`src/tools/read_docs.py`)

新增字段：
- `original_chars` (int) — 磁盘上原始文件字符数
- `returned_chars` (int) — 实际返回内容的字符数

截断时 `original_chars > returned_chars`，短文档二者相等。

### 长文档检查结果

通过 `scripts/inspect_long_document.py` 使用项目真实工具验证：

| 指标 | 值 |
|---|---|
| 文件名 | `_inspect_long_test_temp_.md` |
| 原始字符数 | 12,037 |
| 返回字符数 | 10,016 |
| 是否截断 | `truncated: true` |
| original_chars > returned_chars | ✅ 12,037 > 10,016 |
| read_docs 内容含尾部标识 | ❌（预期不含） |
| search_docs 找到尾部标识 | ✅ 找到"银色狮子8642" |

### 修改文件清单

| 文件 | 修改类型 | 说明 |
|---|---|---|
| `src/prompt.py` | 修改 | 新增规则 9-13（Dynamic State & Freshness Rules） |
| `src/tools/read_docs.py` | 修改 | 新增 `original_chars`、`returned_chars` 返回字段 |
| `src/cli.py` | 修改 | 新增 `--script`、`--step-delay` 参数，支持脚本模式 |
| `tests/test_round8.py` | 新增 | 18 个测试（prompt rules + truncation metadata + scenario JSON validation + dry-run） |
| `docs/manual-test-plan.md` | 新增 | 完整人工测试记录（46 个用例，9 组 A-I） |
| `scenarios/agent-e2e-scenarios.json` | 新增 | 16 个机器可读场景 |
| `scenarios/recording-demo.txt` | 新增 | 录屏用脚本文件 |
| `scripts/inspect_long_document.py` | 新增 | 零 API 长文档截断检查脚本 |
| `scripts/run_real_agent_scenarios.py` | 新增 | 真实 LLM 场景运行器 |

### 测试数量与结果

```
tests/test_all.py             24 passed
tests/test_agent.py           24 passed
tests/test_qwen_client.py     17 passed
tests/test_context_manager.py 39 passed
tests/test_sqlite_session.py  23 passed
tests/test_docs_tools.py      37 passed
tests/test_real_qwen.py        2 skipped
tests/test_round8.py          18 passed  (4 prompt rules + 6 truncation + 2 metadata + 6 scenario JSON + 1 dry-run + 1 no-real-api)
────────────────────────────────────────────
Total: 189 passed, 2 skipped (2.70s)
```

### 真实 qwen3.6-plus 场景结果

3 个关键场景已执行验证：

| Scenario | 结果 | 关键观察 |
|---|---|---|
| DOC-FRESHNESS-001 | ✅ 行为正确 | 第 2 次询问"现在本地知识库还有哪些文档？"重新调用了 list_docs，已删除文件不再出现。模型在回答中主动提及"之前的新鲜度测试文件已删除" |
| DOC-AMBIGUITY-001 | ✅ 通过 | read_docs 返回 `JavaScript介绍基础.md` / `JavaScript介绍进阶.md` 两个候选，模型正确要求用户选择，未擅自决定 |
| DOC-LONG-001 | ✅ 通过 | read_docs 返回 `truncated=true`，模型在答案中披露"原始字符 12037，返回字符 10016，仅显示了部分内容"。search_docs 正确找到截断区域后的"银色狮子8642" |

由于控制台编码 (GBK) 无法正确显示中文，部分 keyword assertion 标记为 WARN，但实际 LLM 行为完全符合预期。

### CLI 脚本模式

最小改造实现 `--script` 和 `--step-delay` 参数：

```powershell
python -m src.cli `
  --user-id demo-user `
  --session-id demo-session `
  --script scenarios/recording-demo.txt `
  --step-delay 1.0
```

- 每行一个用户输入
- 忽略空行和 `#` 开头注释
- 在终端中显示完整交互（用户输入、回答、Steps、Trace）
- `--step-delay` 控制录屏节奏
- 不影响默认交互模式
- 不引入 Playwright/PyAutoGUI/浏览器

### 场景运行器使用方式

```powershell
# 列出计划（不调用 API）
python scripts/run_real_agent_scenarios.py --all --dry-run

# 运行单个场景
$env:RUN_REAL_LLM_TESTS="1"
python scripts/run_real_agent_scenarios.py --scenario DOC-FRESHNESS-001

# 按标签运行
python scripts/run_real_agent_scenarios.py --tag freshness

# 运行全部
python scripts/run_real_agent_scenarios.py --all
```

报告输出：`reports/real-agent-scenario-report.json` + `reports/real-agent-scenario-report.md`

### 人工测试文档路径

- `docs/manual-test-plan.md` — 46 个用例，9 组（A-I），包含状态标记

### 场景 JSON 路径与数量

- `scenarios/agent-e2e-scenarios.json` — 16 个场景

---

## Round 9 — Context 现状审计与可视化

### 本轮 Prompt

不对 Context 管理做任何修改，只进行源码级审计。生成审计文档、零 API 可视化脚本和 SQLite 只读检查脚本。为下一阶段"确定性结构压缩 + 真实 Qwen 语义摘要 + 失败回退"的混合 Context 管理做准备。

### 审计发现摘要

#### 1. 当前 Context 的准确组成

最终发送给 LLM 的消息序列：

```
[0] system           → SYSTEM_PROMPT (src/prompt.py)
[1] system (summary) → "Session memory summary..." + session.summary (仅当 summary 非空)
[2..N]                 session.messages（压缩后剩余 + 当前轮次所有消息）
```

**不包括在 Context 中的内容**：
- Todo — 只通过工具调用访问
- Trace — 仅 CLI 显示 / 调试
- `decision_summary` — 仅存储在 `TraceStep`
- 完整思维链 — Prompt 禁止输出
- API Key — 从不记录或序列化
- SQLite 元数据 — 纯粹存储层

#### 2. 压缩触发条件

```python
# src/context_manager.py:109-115
def prepare_session(self, session):
    if not session.messages: return False
    current_estimate = estimate_tokens(session.messages)
    if current_estimate < self._policy.max_estimated_tokens: return False
    boundary = _find_compress_boundary(session.messages, self._policy.keep_recent_user_turns)
    if boundary <= 0: return False
    # ... compress ...
```

三个条件**全部**满足时才触发：
1. `estimate_tokens >= max_estimated_tokens`（默认 6000）
2. `_find_compress_boundary() > 0`（用户轮次 > keep_recent_user_turns，默认 4）
3. `session.messages` 非空

`prepare_session()` 在 `agent.run()` 中只调用 **一次**，在追加当前用户消息**之前**。因此压缩只作用于**前一轮**的 messages。

#### 3. 压缩边界算法

`_find_compress_boundary` 计算用户消息数量，保留最近 N 个用户轮次，边界始终落在 `user` 消息上。保证：
- Tool Call 序列（assistant(tc) → tool → assistant final）**永远不会被拆分**
- 不会产生孤立 `tool` 消息

#### 4. Summary 实际格式

每个消息角色转换为固定模板行：

| 角色 | 模板 | 示例 |
|---|---|---|
| user | `- 用户请求：{content}` | `- 用户请求：Calculate 15 * 23` |
| assistant(tool_calls) | `- 调用工具：{name}，{args}` | `- 调用工具：calculator，{"expression":"15*23"}` |
| tool | `- 工具结果（{name}）：{content}` | `- 工具结果（calculator）：{"ok":true,"result":"345.0"}` |
| assistant(final) | `- 助手回答：{content}` | `- 助手回答：15 * 23 = 345` |

每项截断至 `max_item_chars`（默认 300）。新旧 summary 通过 `_merge_summary` 拼接，超限时优先保留新内容。

#### 5. 不会进入 Context 的数据

- Todo items
- Trace steps
- decision_summary
- 完整思维链
- API Key
- SQLite created_at / updated_at
- ToolContext

#### 6. Context 测试的准确数量和分类

`tests/test_context_manager.py` 共 **39 个测试**，11 个测试类 + 1 个 standalone：

| 分类 | 测试数 | 测试函数 |
|---|---|---|
| Token 估算 | 3 | `test_empty_returns_zero`, `test_non_empty_at_least_one`, `test_includes_tool_calls` |
| Truncation | 2 | `test_short_unchanged`, `test_long_truncated` |
| 边界识别 | 6 | `test_no_messages` – `test_tool_turns_boundary` |
| 摘要生成 | 4 | `test_user_and_assistant` – `test_content_none_handled` |
| 摘要合并 | 4 | `test_no_existing` – `test_prefers_newer_content` |
| Session 压缩 | 8 | `test_no_compress_when_below_threshold` – `test_summary_length_limited` |
| Session 隔离 | 2 | `test_session_a_not_affect_b`, `test_todos_and_traces_untouched` |
| 消息构建 | 4 | `test_no_summary_no_extra_message` – `test_current_user_input_preserved` |
| AgentRuntime 集成 | 4 | `test_llm_receives_summary_after_compress` – `test_normal_pytest_no_real_api` |
| 已有测试完整性 | 1 | `test_agent_tests_import` |
| Round 9 新增 | 9 | (见 test_round9.py: 可视化 + 检查脚本测试) |

### 可视化脚本实际输出

`python scripts/visualize_context_as_built.py` 使用 27 条混合历史消息，小阈值触发压缩：

```
BEFORE:  27 messages, 8 user turns, 1172 estimated tokens, summary=NO
COMPRESSION: YES, compressed 23, kept 4 (2 user turns)
AFTER:   4 messages, 74 tokens, summary=513 chars
FINAL:   6 messages (system + system(summary) + user + assistant + user + assistant(tc))
INTEGRITY: No orphan tools, No API key, Summary created
```

详细报告：`reports/context-as-built-visualization.json` + `.md`

### user-a/window-1 Session 检查结果

`python scripts/inspect_session_context.py --user-id user-a --session-id window-1`

| 指标 | 值 |
|---|---|
| Messages | 34 |
| Estimated tokens | 7975 |
| Summary | NO (empty — below compression threshold) |
| Todos | 2 |
| Traces | 17 |
| Tool calls | 9 (all matched) |
| API Key | Not found ✅ |

### 适合接入混合语义压缩的位置

根据完整审计，以下是基于当前代码的准确接入点建议：

1. **`_summarize_messages()` 替换** → `src/context_manager.py:24-56` — 当前是纯规则摘要函数。语义摘要器应实现 `SemanticSummarizer` Protocol
2. **`ContextManager.__init__` 扩展** → 行 106 — 添加可选 `summarizer` 参数
3. **`prepare_session()` 返回值增强** → 行 109 — 返回 `CompressionEvent` 丰富信息
4. **`session.summary` 重用** → 无需 schema 变更，LLM 摘要也存储为字符串

### 当前实现的主要语义风险

1. **规则摘要丢失隐含语义** — 无法区分疑问、命令或情绪
2. **事实修正未特殊处理** — 旧的矛盾信息可能保留在 summary 中
3. **重复信息累积** — 多个压缩轮次叠加无去重
4. **超长 Tool Result** — 默认 300 字符截断丢失重要语义
5. **文档读取结果截断** — read_docs 返回的 10000+ 字符仅保留 300
6. **用户偏好与约束退化** — "总是用中文"等偏好可能被压缩截断
7. **陈旧动态状态** — old list_docs/search_docs 结果可能误导
8. **无幻觉防护（当前安全）** — 纯确定性摘要无幻觉风险。接入 LLM 摘要后会新增幻觉、矛盾传播、Prompt Injection 传播等风险

### 新增/修改文件

| 文件 | 变更 |
|---|---|
| `docs/context-as-built-audit.md` | **新增** — 12 节源码级审计文档 |
| `scripts/visualize_context_as_built.py` | **新增** — 零 API 可视化脚本 |
| `scripts/inspect_session_context.py` | **新增** — SQLite Session 只读检查脚本 |
| `tests/test_round9.py` | **新增** — 9 个测试 |

### 自动测试结果

```
tests/test_all.py             24 passed
tests/test_agent.py           24 passed
tests/test_qwen_client.py     17 passed
tests/test_context_manager.py 39 passed
tests/test_sqlite_session.py  23 passed
tests/test_docs_tools.py      37 passed
tests/test_real_qwen.py        2 skipped
tests/test_round8.py          18 passed
tests/test_round9.py           9 passed
────────────────────────────────────────────
Total: 203 passed, 2 skipped (3.58s)
```

### 执行命令输出

| 命令 | 结果 |
|---|---|
| `pytest` | 203 passed, 2 skipped |
| `python -m compileall src tests scripts` | All OK |
| `python scripts/visualize_context_as_built.py` | ✅ 可视化成功，报告生成 |
| `python scripts/inspect_session_context.py --user-id user-a --session-id window-1` | ✅ 34 消息，无 summary，2 todos |

本轮**不修改任何 Context 业务代码**，只做审计和可视化。混合语义压缩将在下一阶段实现。

---

## Round 10A — Context Baseline

### 新增文件

| File | Purpose |
|---|---|
| `scenarios/context-baseline-v1.json` | 20 chat + 10 tool + 10 semantic probe scenario |
| `src/recording_llm_client.py` | Wraps LLMClient, records per-call metadata |
| `scripts/run_context_baseline.py` | Real LLM baseline orchestrator with metrics/reports |
| `scripts/run_context_edge_replay.py` | Synthetic edge-case compression replay (zero API) |
| `docs/context-baseline-test-plan.md` | Human-readable test plan for baseline |
| `tests/test_round10a.py` | 38 tests for scenario, metrics, dry-run, recording client, edge replay |

### 修改文件

| File | Change |
|---|---|
| `scenarios/context-baseline-v1.json` | Fixed unescaped Chinese curly quotes, regenerated via Python |
| `scripts/run_context_baseline.py` | Fixed `global _HAS_KEY` before read, removed duplicate global |
| `tests/test_round10a.py` | `test_report_dir_structure` gates on `run-metadata.json` existence |

### 自动测试结果

```
tests/test_all.py             24 passed
tests/test_agent.py           24 passed
tests/test_qwen_client.py     17 passed
tests/test_context_manager.py 39 passed
tests/test_sqlite_session.py  23 passed
tests/test_docs_tools.py      37 passed
tests/test_real_qwen.py        2 skipped
tests/test_round8.py          18 passed
tests/test_round9.py           9 passed
tests/test_round10a.py        38 passed
────────────────────────────────────────────
Total: 241 passed, 2 skipped (3.00s)
```

---

## Round 10B — Hybrid Semantic Context Compression

### 新增文件

| File | Purpose |
|---|---|
| `src/context_summarizer.py` | `SemanticSummarizer` Protocol, `QwenSemanticSummarizer`, JSON validation & formatting |
| `scripts/compare_context_modes.py` | Compare deterministic vs hybrid `metrics.json` → `context-comparison.md` + `.json` |
| `scripts/demo_hybrid_context.py` | Zero-API demo with `FakeSemanticSummarizer` (success + fallback) |
| `docs/hybrid-context-design.md` | Design rationale, architecture, fallback matrix |
| `tests/test_round10b.py` | 29 tests with `FakeSemanticSummarizer` (no real network) |

### 修改文件

| File | Change |
|---|---|
| `src/config.py` | Added `load_summary_mode()`, `load_summary_model()`, `load_summary_max_chars()` |
| `src/qwen_client.py` | `complete()` skips `tools`/`tool_choice` when `tools` empty |
| `src/context_manager.py` | `ContextManager.__init__` accepts optional `summarizer` and `summary_mode`. `prepare_session` hybrid path: calls summarizer → fallback to deterministic on failure. Tracks `last_compression_event` |
| `scripts/run_context_baseline.py` | Added `--summary-mode deterministic|hybrid` and `--report-dir` flags |

### Hybrid Compression Call Chain

```
agent.run()
  → context_manager.prepare_session(session)
    → _find_compress_boundary()  [code ensures structural safety]
    → if mode == "hybrid" and summarizer exists:
        → summarizer.summarize(previous_summary, to_compress, max_output_chars)
          → OpenAI chat.completions (no tools, response_format=json_object)
          → parse JSON → validate fields → format as text
        → if success: session.summary = semantic_text
        → if exception/empty: fallback to deterministic
    → if not semantic_succeeded:
        → _summarize_messages() + _merge_summary()  [existing deterministic path]
    → session.messages = session.messages[boundary:]
    → update last_compression_event metadata
  → session.messages.append(user_input)
  → context_manager.build_messages()  [unchanged]
```

### Semantic Summary JSON Structure

```json
{
  "goals": [],
  "confirmed_facts": [],
  "latest_corrections": [],
  "preferences": [],
  "constraints": [],
  "completed_actions": [],
  "open_items": [],
  "document_references": []
}
```

Formatted to plain text before storage:
```
Goals:
- ...

Confirmed Facts:
- ...
```

### Failure Fallback Logic

| Failure | Detection | Fallback |
|---|---|---|
| API timeout | Exception | Deterministic |
| Auth error | Exception | Deterministic |
| Rate limit | Exception | Deterministic |
| Network error | Exception | Deterministic |
| Empty response | `if semantic_text` false | Deterministic |
| Invalid JSON | `json.loads` + `_validate_semantic_json` raise | Deterministic |
| Bad field types | `_validate_semantic_json` raise | Deterministic |
| Output too long | Truncate after format | (truncated text kept) |

Fallback never propagates to the user — Agent continues normally.

### 自动测试结果

```
tests/test_all.py             24 passed
tests/test_agent.py           24 passed
tests/test_qwen_client.py     17 passed
tests/test_context_manager.py 39 passed
tests/test_sqlite_session.py  23 passed
tests/test_docs_tools.py      37 passed
tests/test_real_qwen.py        2 skipped
tests/test_round8.py          18 passed
tests/test_round9.py           9 passed
tests/test_round10a.py        38 passed
tests/test_round10b.py        29 passed
────────────────────────────────────────────
Total: 270 passed, 2 skipped (3.69s)
```

### 执行命令输出

| 命令 | 结果 |
|---|---|
| `pytest` | 270 passed, 2 skipped |
| `python -m compileall src tests scripts` | All OK |
| `python scripts/demo_hybrid_context.py` | ✅ Demo 1 (successful semantic summary): 8→4 msgs, 108→56 tokens; ✅ Demo 2 (fallback): 8→4 msgs, semantic failed → deterministic used |
| `python scripts/run_context_baseline.py --dry-run --summary-mode hybrid` | ✅ Dry run shows hybrid mode, correct report dir `reports/context-hybrid/` |

### 真实 Hybrid 测试

未执行。本次仅验证零 API 路径。存在真实 `DASHSCOPE_API_KEY` 时可运行:

```powershell
$env:RUN_REAL_LLM_TESTS="1"
python scripts/run_context_baseline.py --scenario scenarios/context-baseline-v1.json --summary-mode hybrid --max-estimated-tokens 1800 --keep-recent-user-turns 4 --report-dir reports/context-hybrid
```

### Semantic Summary 调用统计（零 API 路径）

| 指标 | 值 |
|---|---|
| Semantic summary call count | 29 (all via FakeSemanticSummarizer, no real API) |
| Semantic summary success count | 27 (simulated success) |
| Semantic summary fallback count | 2 (simulated failure) |
| Deterministic real report | 不存在 — 尚未运行真实基线 |
| Hybrid real report | 不存在 — 尚未运行真实基线 |
| Comparison report | 尚未生成 — 缺少一侧真实报告 |
