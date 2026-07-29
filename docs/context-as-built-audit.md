# 上下文实际构建审计

基于当前源代码（第 8 轮，189 个测试通过）对 `minimal_agent` 上下文管理的源码级审计。

---

## 1. 类与职责

### `Session`（src/session.py:8-15）

```python
@dataclass
class Session:
    user_id: str
    session_id: str
    messages: list[dict[str, str]]
    summary: str
    todos: list[dict[str, Any]]
    traces: list[dict[str, Any]]
```

| 字段 | 类型 | 用途 |
|---|---|---|
| `user_id` | `str` | 逻辑用户标识 |
| `session_id` | `str` | 用户内的会话标识 |
| `messages` | `list[dict[str, str]]` | 有序对话历史（role, content, tool_calls 等） |
| `summary` | `str` | 已压缩消息的确定性文本摘要 |
| `todos` | `list[dict[str, Any]]` | 待办事项（不发送给 LLM 上下文） |
| `traces` | `list[dict[str, Any]]` | 逐步执行追踪（不发送给 LLM 上下文） |

注意：`messages` 上的 `list[dict[str, str]]` 类型标注过于严格——运行时它包含 `dict[str, Any]`，包括 `tool_calls`（list）、`tool_call_id`（str）、`name`（str）等。

### `SessionStore`（src/session.py:18-38）

基于内存字典的存储。键为 `(user_id, session_id)` 元组。

| 方法 | 行为 |
|---|---|
| `get_or_create(key)` | 返回已有或创建新的 `Session` |
| `get(key)` | 返回 `Session` 或 `None` |
| `list_user_sessions(uid)` | 列出用户的所有会话 |
| `save(session)` | 插入或更新字典 |
| `clear()` | 清空所有会话 |

### `SQLiteSessionStore`（src/sqlite_session.py:88-190）

基于 SQLite 的存储，带内存缓存以实现对象标识一致性。

| 方面 | 详情 |
|---|---|
| 表 | `sessions(user_id TEXT, session_id TEXT, state_json TEXT, created_at TEXT, updated_at TEXT)` |
| 主键 | `(user_id, session_id)` 联合主键 |
| 序列化 | `_serialize()` 将 `messages`、`summary`、`todos`、`traces` 写为 JSON |
| 反序列化 | `_deserialize()` 验证全部 4 个键存在 |
| 缓存 | `_cache: dict[tuple[str, str], Session]` —— 每进程返回相同的 Python 对象 |
| Upsert | `INSERT ... ON CONFLICT DO UPDATE SET state_json, updated_at` |

`save()` 在 `agent.py` 的 8 个位置被调用（每次修改 session.messages、session.traces 前后）。

### `ContextPolicy`（src/context_manager.py:10-15）

```python
@dataclass(frozen=True)
class ContextPolicy:
    max_estimated_tokens: int = 6000
    keep_recent_user_turns: int = 4
    max_summary_chars: int = 3000
    max_item_chars: int = 300
```

可通过 `src/config.py:load_context_policy()` 从环境变量配置：
- `AGENT_CONTEXT_MAX_TOKENS` → `max_estimated_tokens`
- `AGENT_CONTEXT_KEEP_RECENT_TURNS` → `keep_recent_user_turns`
- `AGENT_CONTEXT_MAX_SUMMARY_CHARS` → `max_summary_chars`
- `AGENT_CONTEXT_MAX_ITEM_CHARS` → `max_item_chars`

### `ContextManager`（src/context_manager.py:105-153）

两个公开方法：

| 方法 | 位置 | 用途 |
|---|---|---|
| `prepare_session(session)` | 第 109-130 行 | 条件压缩：将旧消息截断为摘要 |
| `build_messages(system_prompt, session)` | 第 132-153 行 | 组装发送给 LLM 的最终消息列表 |

### `AgentRuntime`（src/agent.py:42-247）

主要编排器。关键上下文相关操作：

| 操作 | 位置 | 详情 |
|---|---|---|
| `prepare_session()` 调用 | 第 84 行 | 在追加用户消息之前 |
| 用户消息追加 | 第 86 行 | 压缩之后 |
| `build_messages()` 调用 | 第 91 行 | 步骤循环内，每次 LLM 调用之前 |
| 工具调用追加 | 第 194 行 | 带 tool_calls 的 assistant 消息 |
| 工具结果追加 | 第 239-246 行 | 每个工具调用一条 tool 消息 |
| 助手回答追加 | 第 110-112 行 | 最终 assistant 内容消息 |
| `_save_session()` 调用 | 第 85, 87, 113, 123, 132, 143, 149, 159, 165, 168, 195, 247 行 | 每次修改后 |

### `LLMClient` 协议（src/llm.py:21-29）

```python
class LLMClient(Protocol):
    def complete(self, *, messages: list[dict], tools: list[dict]) -> LLMResponse: ...
```

实现：`ScriptedLLMClient`（测试替身，`src/llm.py:32-58`）、`OpenAICompatibleLLMClient`（真实，`src/qwen_client.py`）。

### `TraceStep`（src/trace.py:7-19）

```python
@dataclass
class TraceStep:
    step_number: int
    event_type: str          # "tool_call" | "final_answer" | "llm_error" | "max_steps_exceeded"
    run_id: int = 0
    decision_summary: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    arguments: dict | None = None
    observation: str | None = None
    success: bool | None = None
    error_type: str | None = None
    duration_ms: float | None = None
```

---

## 2. 完整数据流

### 带源码位置的流程图

```
用户输入
    │
    ▼
1. session = store.get_or_create(user_id, session_id)
   └─ src/agent.py:79
   └─ src/sqlite_session.py:112（或 src/session.py:22）
    │
    ▼
2. context_manager.prepare_session(session)
   └─ src/agent.py:84
   └─ src/context_manager.py:109
   │  ├─ estimate_tokens(session.messages) → 低于阈值则 False
   │  ├─ find_compress_boundary() → 轮次不足则 0
   │  ├─ slice messages[:boundary] → to_compress
   │  ├─ summarize_messages(to_compress) → entries 列表
   │  ├─ merge_summary(existing, entries) → 新摘要字符串
   │  ├─ session.summary = new_summary
   │  └─ session.messages = messages[boundary:]
   │
   ├─ store.save(session)  [agent.py:85]
    │
    ▼
3. session.messages.append({"role": "user", "content": user_input})
   └─ src/agent.py:86
    │
   ├─ store.save(session)  [agent.py:87]
    │
    ▼
4. FOR 每一步（1 到 max_steps）：
    │
   ├─ msgs = build_messages(system_prompt, session)
   │  └─ src/agent.py:91
   │  └─ src/context_manager.py:132
   │     ├─ [{"role": "system", "content": system_prompt}]
   │     ├─ IF 有摘要：[{"role": "system", "content": "Session memory..." + summary}]
   │     └─ + session.messages（包括当前用户消息及之前的工具结果）
   │
   ├─ response = llm_client.complete(messages=msgs, tools=tools_schema)
   │  └─ src/agent.py:96-98
   │
   ├─ IF 有 tool_calls：
   │  ├─ 追加 assistant 消息（带 tool_calls）→ session.messages [agent.py:194]
   │  ├─ store.save(session) [agent.py:195]
   │  ├─ FOR 每个工具调用：
   │  │  ├─ 执行工具 [agent.py:201]
   │  │  ├─ 追加追踪 [agent.py:237]
   │  │  ├─ 追加工具消息 → session.messages [agent.py:239-246]
   │  │  └─ store.save(session) [agent.py:247]
   │  └─ 返回步骤 4（下一轮迭代）
   │
   ├─ ELIF 有内容：
   │  ├─ 追加 assistant 消息 → session.messages [agent.py:110-112]
   │  ├─ store.save(session) [agent.py:113]
   │  ├─ 追加追踪 [agent.py:122]
   │  ├─ store.save(session) [agent.py:123]
   │  └─ 返回 AgentResult [agent.py:124-129]
   │
   └─ ELSE（空）：
      ├─ store.save(session) [agent.py:132]
      ├─ 追加错误追踪 [agent.py:142]
      ├─ store.save(session) [agent.py:143]
      └─ 抛出 InvalidLLMResponseError [agent.py:144-147]
```

关键观察：`prepare_session` 在**每次运行**时**仅调用一次**，在**当前用户消息追加之前**。它只压缩**之前运行**的消息，从不压缩当前轮次。

---

## 3. 当前上下文组成

### 发送给 LLM 的最终消息列表

```
索引  Role       内容
────── ────────── ──────────────────────────────────────────────
0      system     SYSTEM_PROMPT（来自 src/prompt.py）
1*     system     "Session memory summary. Treat this as previous
                  conversation context, but prefer current tool
                  results when conflicts exist:\n" + session.summary
2..N   user/      session.messages（压缩后剩余的消息
       assistant  + 当前轮次的用户消息
       /tool      + tool_call 消息 + tool result 消息）
```

`*` —— 仅在 `session.summary` 非空时存在。

### 上下文**包含**的内容

| 数据 | 包含 | 来源 |
|---|---|---|
| 系统提示 | ✅ 始终 | `src/prompt.py` |
| 摘要（确定性） | ✅ 当 `session.summary != ""` 时 | `build_messages()` 第 141 行 |
| 当前用户输入 | ✅ 在 agent.py:86 追加 | `session.messages` |
| 之前的用户输入 | ✅ 压缩后剩余 | `session.messages` |
| Assistant tool_call 消息 | ✅ 在 agent.py:194 追加 | `session.messages` |
| 工具结果消息 | ✅ 在 agent.py:239-246 追加 | `session.messages` |
| Assistant 最终回答 | ✅ 在 agent.py:110 追加 | `session.messages` |
| 工具模式 | ✅ 作为 `tools` 参数传递 | `export_openai_schema()` |

### 上下文**不包含**的内容

| 数据 | 排除？ | 存储位置 | 原因 |
|---|---|---|---|
| 待办事项 | ❌ 不在上下文中 | `session.todos` | 仅通过工具调用访问 |
| 追踪步骤 | ❌ 不在上下文中 | `session.traces` | 仅用于 CLI 显示/调试 |
| `decision_summary` | ❌ 不在上下文中 | `TraceStep.decision_summary` | 用于追踪/调试，非模型输入 |
| 完整思维链 | ❌ 不在上下文中 | 未存储 | 提示要求"不要输出" |
| API 密钥 | ❌ 不在上下文中 | `os.environ` / `LLMSettings` | 从不记录或序列化 |
| SQLite 元数据 | ❌ 不在上下文中 | SQLite `created_at`/`updated_at` | 仅存储使用 |
| `ToolContext` | ❌ 不在上下文中 | 每次运行创建 | 仅运行时，不序列化 |

---

## 4. 压缩触发条件

### 默认阈值

```python
ContextPolicy(max_estimated_tokens=6000)  # src/context_manager.py:12
```

可通过 `AGENT_CONTEXT_MAX_TOKENS` 环境变量覆盖。

### Token 估算方法

```python
def estimate_tokens(messages: list[dict]) -> int:
    # src/context_manager.py:98-102
    text = json.dumps(messages, ensure_ascii=False, default=str)
    return max(1, len(text) // 4)
```

这是一个**字节长度代理**——将所有消息序列化为 JSON，字符数除以 4。这是粗略估计，并非真正的分词器。它计算所有键、tool_calls 结构等。

### 判断表达式（实际代码）

```python
# src/context_manager.py:109-115
def prepare_session(self, session: Session) -> bool:
    if not session.messages:
        return False
    current_estimate = estimate_tokens(session.messages)
    if current_estimate < self._policy.max_estimated_tokens:
        return False
    boundary = _find_compress_boundary(session.messages, self._policy.keep_recent_user_turns)
    if boundary <= 0:
        return False
    # ... 压缩 ...
    return True
```

三个条件**必须全部**满足：
1. `estimate_tokens >= max_estimated_tokens`
2. `_find_compress_boundary() > 0`（用户轮次超过保留数）
3. `session.messages` 非空

### `prepare_session` 调用时机

- 在 `src/agent.py:84` 调用 —— 每次 `agent.run()` 调用**一次**
- 在 `session.messages.append({"role": "user", "content": user_input})`（agent.py:86）**之前**调用
- 因此，压缩作用于**上次运行的消息**，从不作用于当前输入
- 在步骤循环中不会再次调用，即使多次工具调用添加了大量消息

### 压缩是否能在一次 `run()` 中多次触发

**不能。** `prepare_session()` 在第 84 行被调用一次，在步骤循环之前。步骤循环（第 90-163 行）追加 tool_calls 和工具结果，但不会再调用 `prepare_session()`。单次 `run()` 最多可以添加 `max_steps` 轮工具调用而不重新评估是否需要压缩。

---

## 5. 压缩边界算法

### 核心算法（`_find_compress_boundary`，src/context_manager.py:83-95）

```python
def _find_compress_boundary(messages: list[dict], keep_turns: int) -> int:
    user_count = sum(1 for m in messages if m.get("role") == "user")
    if user_count <= keep_turns:
        return 0
    turns_to_skip = user_count - keep_turns
    seen = 0
    for i, msg in enumerate(messages):
        if msg.get("role") == "user":
            seen += 1
            if seen > turns_to_skip:
                return i
    return len(messages)
```

**策略：** 统计用户消息数，确定"超出"最后 `keep_turns` 轮之前有多少轮。向前遍历，返回第一个要保留轮次的索引。

### 示例

#### 示例 1：纯对话（2 轮，keep=4）

```
Messages: [user:q1, asst:a1, user:q2, asst:a2]
user_count = 2 ≤ 4  →  return 0（不压缩）
```

#### 示例 2：纯对话（3 轮，keep=2）

```
Messages: [user:q1, asst:a1, user:q2, asst:a2, user:q3, asst:a3]
user_count = 3 > 2
turns_to_skip = 1
遍历：
  i=0: user:q1 → seen=1, seen ≤ 1 → 继续
  i=1: asst:a1
  i=2: user:q2 → seen=2, seen > 1 → return 2
```
结果：压缩 [0, 1)（消息 0-1），保留 [2, 3, 4, 5]。

#### 示例 3：单工具调用轮次（3 轮，keep=2）

```
[user:q1, asst(tc), tool, asst:final, user:q2, asst:a2, user:q3, asst:a3]
user_count = 3 > 2
turns_to_skip = 1
遍历：
  i=0: user:q1 → seen=1, seen ≤ 1 → 继续
  i=1: asst(tc) → 不是 user
  i=2: tool → 不是 user
  i=3: asst:final → 不是 user
  i=4: user:q2 → seen=2, seen > 1 → return 4
```
结果：压缩 [0..3]（整个第一轮工具调用），保留 [4..7]。

#### 示例 4：并行工具调用（2 轮，keep=1）

```
[user:q1, asst:final:q1, user:q2, asst(tc1+tc2), tool:r1, tool:r2, asst:done]
user_count = 2 > 1
turns_to_skip = 1
遍历：
  i=0: user:q1 → seen=1, seen ≤ 1 → 继续
  i=1: asst:a1 → 不是 user
  i=2: user:q2 → seen=2, seen > 1 → return 2
```
结果：压缩 [0..1]，保留 [2..6]。

#### 示例 5：工具错误（assistant content=null，工具失败）

与示例 3 相同——算法只统计用户消息，因此错误消息被视为其轮次的一部分。

#### 示例 6：最后一轮无最终答案

如果最后一轮是 `[user, asst(tc), tool]` 而没有最终 assistant 消息，user_count 仍然将其计为一轮。边界将放在要保留的下一轮用户消息处。不完整的轮次将包含在保留消息中。

#### 示例 7：孤立的工具消息

如果工具结果没有前导的用户消息（正常操作中不太可能），算法仍会围绕用户边界进行分组。两个用户轮次之间的孤立工具消息将与第二轮一起保留。

### 关键属性：用户边界对齐

边界始终落在 `user` 消息上（或在最末尾）。这保证：
- 工具调用序列（带 tool_calls 的 assistant → 零或多个工具结果 → assistant 最终回答）**从不**跨压缩边界分割。
- 剩余消息中没有孤立的 `tool` 消息（所有工具结果属于完整保留的轮次）。
- to_compress 切片从索引 0 开始，始终是完整轮次的有序序列。

---

## 6. 当前摘要格式

### `_summarize_messages`（src/context_manager.py:24-56）

每个消息角色被转换为确定性文本行：

| 角色 | 模式 | 示例 |
|---|---|---|
| user | `- 用户请求：{content}` | `- 用户请求：Calculate 15 * 23` |
| assistant（带 tool_calls） | `- 调用工具：{name}，{args}` | `- 调用工具：calculator，{"expression":"15*23"}` |
| tool | `- 工具结果（{name}）：{content}` | `- 工具结果（calculator）：{"ok":true,"result":"345.0"}` |
| assistant（最终回答） | `- 助手回答：{content}` | `- 助手回答：15 * 23 = 345` |

### 每项字符截断

每个项目截断至 `max_item_chars`（默认 300）：
```python
def _truncate(text: str, max_chars: int) -> str:
    return text[:max_chars] + "..."
```

### 摘要合并（`_merge_summary`，src/context_manager.py:59-80）

```python
def _merge_summary(existing: str, new_entries: list[str], max_chars: int) -> str:
```

| 场景 | 行为 |
|---|---|
| 无现有摘要 | 使用新条目；超过 max_chars 则截断 |
| 合并后合适 | `existing + "\n" + new_text` |
| 合并后超出 | 为截断标记保留 50 字符；尽量保留全部 new_text |
| 新文本太长 | 将 new_text 截断至 `max_chars - 50` |
| 新文本合适但旧文本太长 | 保留旧文本的最后 `max_chars - len(new_text) - 1` 个字符 |
| 空间极有限 | 丢弃旧文本，返回 new_text + 截断标记 |

### 真实摘要示例

对于一个包含 2 个纯对话轮次和 1 个工具轮次的压缩会话：

```
- 用户请求：今天天气怎么样？
- 助手回答：晴天，25 度。
- 用户请求：计算 15 * 23
- 调用工具：calculator，{"expression":"15*23"}
- 工具结果（calculator）：{"ok":true,"result":"345.0"}
- 助手回答：15 * 23 = 345
```

### `None` 内容处理

```python
# 第 31-32 行
content = msg.get("content", "")
if content is None:
    content = ""
```

Assistant tool_call 消息通常有 `"content": null`，会被转为空字符串并在（不带 tool_calls 的 `assistant` 分支中）摘要为 `- 助手回答：`。但如果它有 `tool_calls` 键，会在第 35 行的较早分支中被捕获：
```python
elif msg.get("role") == "assistant" and "tool_calls" in msg:
```

因此 tool_call 消息永远不会进入"assistant"文本分支。

---

## 7. SQLite 持久化

### 序列化（`_serialize`，src/sqlite_session.py:38-48）

```python
def _serialize(session: Session) -> str:
    return json.dumps({
        "messages": session.messages,
        "summary": session.summary,
        "todos": session.todos,
        "traces": session.traces,
    }, ensure_ascii=False, default=str)
```

### 反序列化（`_deserialize`，src/sqlite_session.py:51-67）

验证：
- JSON 格式正确
- 根是一个字典
- 全部 4 个键存在

如果 JSON 损坏：抛出 `SessionPersistenceError`。

### 各字段处理

| 字段 | 存储为 | 恢复为 |
|---|---|---|
| `messages` | 完整 JSON 数组 | `Session.messages`（相同结构） |
| `summary` | 纯文本字符串 | `Session.summary` |
| `todos` | 完整 JSON 数组 | `Session.todos` |
| `traces` | 完整 JSON 数组 | `Session.traces` |

所有字段在 `save()` → 进程重启 → `get_or_create()` 过程中完整保留。

### `session.summary` 持久化

`summary` 是 dataclass 中的字符串字段，作为 JSON 字符串值序列化。它不是独立的 SQLite 列——它存在于 `state_json` 内部。其值在进程重启后保持不变。

---

## 8. 测试映射（`tests/test_context_manager.py`）

总计：**39 个测试函数**，分布在 11 个测试类 + 1 个独立测试。

### Token 估算（3 个测试）

| 测试 | 断言 |
|---|---|
| `test_empty_returns_zero` | `estimate_tokens([]) == 0` |
| `test_non_empty_at_least_one` | `estimate_tokens([{"role":"user","content":"hi"}]) >= 1` |
| `test_includes_tool_calls` | 估算包含 tool_call + tool_result 的计数 |

### 截断（2 个测试）

| 测试 | 断言 |
|---|---|
| `test_short_unchanged` | `_truncate("hello", 10)` 返回 `"hello"` |
| `test_long_truncated` | `_truncate("hello world", 5)` 返回 `"hello..."`（8 字符） |

### 边界识别（6 个测试）

| 测试 | 断言 |
|---|---|
| `test_no_messages` | `_find_compress_boundary([], 4) == 0` |
| `test_fewer_turns_than_keep` | 1 轮 keep=4 → 0 |
| `test_exact_turns_no_compress` | 2 轮 keep=2 → 0 |
| `test_more_turns_than_keep` | 3 轮 keep=2 → 边界在索引 2 |
| `test_more_turns_keeps_last_n` | 4 轮 keep=2 → 边界在索引 4 |
| `test_tool_turns_boundary` | 3 轮（1 个工具轮）keep=2 → 边界在索引 4 |

### 摘要生成（4 个测试）

| 测试 | 断言 |
|---|---|
| `test_user_and_assistant` | 条目包含"用户请求"和"助手回答" |
| `test_tool_calls_summarized` | 条目包含"调用工具"和"工具结果" |
| `test_long_content_truncated` | 长内容包含"..." |
| `test_content_none_handled` | `None` 内容被优雅处理 |

### 摘要合并（4 个测试）

| 测试 | 断言 |
|---|---|
| `test_no_existing` | 新条目成为摘要 |
| `test_combines_existing_and_new` | 新旧内容均出现 |
| `test_trims_when_exceeds_max` | 长度 ≤ max_chars + 松弛量 |
| `test_prefers_newer_content` | 新内容优先于旧内容保留 |

### 会话压缩（8 个测试）

| 测试 | 断言 |
|---|---|
| `test_no_compress_when_below_threshold` | 返回 False，消息不变 |
| `test_compress_when_above_threshold` | 返回 True，消息减少 |
| `test_keeps_recent_turns` | 保留最后 2 轮用户消息（4 条消息） |
| `test_no_compress_if_empty` | 空消息 → False |
| `test_summary_created_after_compress` | 摘要非空，包含已压缩内容 |
| `test_tool_call_not_split_from_result` | 工具轮的全部 4 条消息保留，`remaining[0]` 是"user" |
| `test_parallel_tool_calls_preserved` | 保留 5 条消息（user + 2 个并行 tool_calls + 2 个结果 + done） |
| `test_summary_length_limited` | 摘要长度 ≤ max_summary_chars + 松弛量 |

### 会话隔离（2 个测试）

| 测试 | 断言 |
|---|---|
| `test_session_a_not_affect_b` | 会话 A 压缩不影响会话 B |
| `test_todos_and_traces_untouched` | 压缩不修改 todos 或 traces |

### 消息构建（4 个测试）

| 测试 | 断言 |
|---|---|
| `test_no_summary_no_extra_message` | 3 条消息：system + user + assistant |
| `test_with_summary_injected` | 3 条消息：system + system(summary) + user |
| `test_summary_position_after_system` | 摘要是第 2 条消息（在系统提示之后，用户之前） |
| `test_current_user_input_preserved` | 当前用户输入出现在构建的消息中 |

### AgentRuntime 集成（4 个测试）

| 测试 | 断言 |
|---|---|
| `test_llm_receives_summary_after_compress` | 压缩后 call_history 中有摘要 |
| `test_plain_chat_after_compress_still_works` | 第二个回答正确返回 |
| `test_todo_after_compress_still_accessible` | 待办在压缩后仍然可用 |
| `test_normal_pytest_no_real_api` | 使用 ScriptedLLMClient（索引递增） |

### 已有测试未被破坏（1 个测试）

| 测试 | 断言 |
|---|---|
| `test_agent_tests_import` | 模块导入无错误 |

---

## 9. 当前限制与风险

### 9.1 基于规则的摘要丢失隐含语义

确定性 `_summarize_messages` 使用固定的中文模板（`- 用户请求：`）。它：
- **不推断**意图、情感或隐含约束
- **不区分**问题和命令
- 丢失原始对话的语义细节

示例："我觉得可能要下雨" vs "关上窗户" 都变成了 `- 用户请求：{原文}`。

### 9.2 事实修正未被特殊处理

如果用户在第 1 轮说"我叫小明"，在第 3 轮说"其实叫我小红"：
- 第 1 轮可能被压缩进摘要
- 摘要记录"用户请求：我叫小明"
- 没有机制识别这是已被覆盖的信息
- LLM 同时收到摘要（小明）和保留的轮次（小红）可能会混淆

### 9.3 重复信息累积

每个被压缩的轮次都会向摘要添加条目。经过多次会话，摘要不断增长并从底部（最早的内容）被截断。但跨轮次的重复信息（如 `- 工具结果（read_docs）：{截断的内容}`）在保留时没有去重。

### 9.4 超长工具结果

工具结果被序列化为包含完整结果字符串的 JSON：
```python
observation = json.dumps({"ok": True, "result": result}, ensure_ascii=False)
```

当这个被摘要时：
```python
content = msg.get("content", "")  # 完整的 JSON 字符串
entries.append(f"- 工具结果（{name}）：{_truncate(content, max_item_chars)}")
```

默认 `max_item_chars=300` 意味着长结果（read_docs 返回 10000 字符）会被截断为 300 字符 + "..."。超过 300 字符的重要语义内容在摘要中被静默丢失。

### 9.5 文档读取结果被严重截断

read_docs 结果可能包含 10000+ 字符。摘要后仅保留前 300 字符。摘要丢失：
- 读取了哪个文档
- 300 字符后的实际内容
- 结果是否被截断

### 9.6 用户偏好和约束退化

如果用户在第 2 轮说"请用中文回答"，此声明：
- 被压缩为 `- 用户请求：请用中文回答`
- 变成一条孤立的文本行，而非持久指令
- 多次压缩后，可能因空间不足而优先被新内容替换

### 9.7 旧摘要中的过时动态状态

像 `- 工具结果（list_docs）：{"ok": true, "result": "file1, file2"}` 的摘要条目代表过去的磁盘状态。如果摘要作为"当前上下文"注入，LLM 可能错误地将旧文件列表视为当前状态——尽管规则 13 说"优先使用当前工具结果"。必须依赖 LLM 来做出这种区分。

### 9.8 目前缺乏幻觉防护

当前摘要纯粹是确定性文本提取——没有 LLM 参与，因此没有幻觉风险。然而：
- `_truncate()` 函数追加 `"..."` 而没有结构标记
- 工具结果中被截断的 JSON 可能看起来不完整，但 LLM 仍可能尝试使用它
- 截断点落在任意字符边界上，而不是语义边界

### 9.9 LLM 摘要集成后的风险

引入 LLM 语义摘要后，新风险包括：
- **编造的摘要事实** —— LLM 可能"记住"从未发生过的事
- **摘要与最新消息之间的矛盾** —— LLM 必须解决冲突
- **关键细节丢失** —— LLM 可能认为用户认为重要的内容不重要
- **通过摘要进行提示注入** —— 如果被压缩的消息包含注入指令，LLM 驱动的摘要器可能传播这些指令
- **增加成本和延迟** —— 每次压缩触发额外的 LLM 调用

---

## 10. 混合压缩集成设计要点

基于当前代码，以下是适合引入语义摘要器组件的精确接口和位置。不提供实现代码。

### 10.1 SemanticSummarizer 协议 —— `_summarize_messages` 替换

**当前位置：** `src/context_manager.py:24-56`，函数 `_summarize_messages()`

**当前签名：**
```python
def _summarize_messages(messages: list[dict], max_item_chars: int) -> list[str]:
```

**设计接口：**
```python
class SemanticSummarizer(Protocol):
    def summarize(self, messages: list[dict], max_chars: int) -> str: ...
```

这是最自然的注入点。`prepare_session()` 第 124 行调用 `_summarize_messages(to_compress, ...)` 并接收一个 `list[str]`。`SemanticSummarizer` 将返回单个连贯的摘要字符串。

**选项：**
- `DeterministicSummarizer` —— 当前逻辑，作为回退
- `QwenSemanticSummarizer` —— 调用 LLM 生成自然语言摘要
- `FallbackSummarizer` —— 尝试 LLM，出错时回退到确定性方式

### 10.2 ContextManager 注入点 —— 构造函数参数

**当前：** `ContextManager.__init__` 第 106 行只接受 `ContextPolicy`

```python
class ContextManager:
    def __init__(self, policy: ContextPolicy | None = None) -> None:
```

**设计：** 添加可选参数 `summarizer: SemanticSummarizer | None = None`。如果提供了摘要器，在 `prepare_session()` 中使用它。否则回退到当前确定性逻辑。

### 10.3 压缩事件通知 —— `prepare_session` 返回值

**当前：** `prepare_session()` 返回 `bool`（是否发生了压缩）。

```python
def prepare_session(self, session: Session) -> bool:
```

**设计：** 可以返回一个 `CompressionEvent` 数据类，包含：
- `compressed: bool`
- `messages_before: int` / `messages_after: int`
- `summary_before_len: int` / `summary_after_len: int`
- `summarizer_used: str`（"deterministic" | "semantic"）
- `tokens_saved: int`

### 10.4 ContextMetrics 报告 —— `prepare_session` 前后

**当前：** `agent.py:84` 调用 `prepare_session()` 并忽略 bool 返回值。

**设计：** `ContextManager` 和 `AgentRuntime` 都可维护指标计数器：
- 压缩次数
- 压缩的 Token 总数
- 摘要器类型分布

### 10.5 摘要存储 —— `session.summary` 已存在

**当前：** `session.summary: str` 存储压缩后的文本。

**设计：** 不需要修改模式。LLM 生成的摘要也将作为纯字符串存储。未来增强可向 `Session` 添加 `summary_type: str`（"deterministic" | "semantic"）和 `summary_version: int` 字段。

### 10.6 用于摘要的 LLM 调用 —— 何时及如何

**设计考量：**

- `prepare_session()` 当前在 `agent.run()` 中同步调用。
- 基于 LLM 的摘要器会使第一个用户响应变慢。
- 选项：
  1. **在 prepare_session 中同步** —— 简单、可预测
  2. **异步/延迟** —— 摘要在当前响应返回后进行，但需要后台处理
  3. **按需** —— 仅在明确触发时摘要（如 Token 阈值）
- 应使用 `ScriptedLLMClient` 或专用的摘要 LLM 客户端，而不是直接使用 `qwen_client`。

### 10.7 回退策略 —— `_merge_summary` 兼容性

**当前：** `_merge_summary()` 将新条目追加到现有摘要。

**设计：** 使用 LLM 摘要后合并策略将根本改变。不再文本拼接：
- LLM 接收 `existing_summary + "\n" + new_messages_text` 并生成单个连贯的摘要
- 回退：如果 LLM 调用失败，使用当前的 `_summarize_messages` + `_merge_summary`

### 10.8 不变区域

以下区域**不应**被摘要注入修改：
- `_find_compress_boundary()` —— 边界逻辑保持不变
- `build_messages()` —— 消息组装模式保持不变
- `AgentRuntime.run()` —— 编排模式保持不变
- `Session` 模式 —— 此阶段不需要新字段
- `SQLiteSessionStore` —— `state_json` 格式不变
