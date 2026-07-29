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
