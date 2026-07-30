# Minimal Agent

一个不依赖 LangGraph、OpenHands、OpenClaw 等 Agent 框架的最小可用 Agent Runtime。项目使用真实的 DashScope OpenAI 兼容 API，核心循环、工具注册、会话持久化、Context 管理与 Trace 均在仓库内自行实现。

这不是一个追求功能数量的通用 Agent 平台，而是一份便于运行、录屏和源码审查的笔试实现。

## 一、先看完成链路

### 1. 一次请求如何完成

```text
用户输入
  → 按 (user_id, session_id) 恢复 Session
  → 必要时压缩旧 Context
  → 将 System Prompt、Session Summary、近期消息发送给 LLM
  → LLM 直接回答，或按 JSON Schema 返回 tool_calls
  → Runtime 查找并执行工具
  → 将 Observation 回填给 LLM
  → LLM 继续调用工具，或给出最终答案
  → 持久化消息、待办与 Trace
```

主循环位于 `src/agent.py`，模型适配位于 `src/qwen_client.py`，工具注册与分发位于 `src/registry.py`。主流程没有交给第三方 Agent 框架。

### 2. 对照题目要求

| 要求 | 当前实现 | 主要位置 |
|---|---|---|
| 真实 LLM API | DashScope OpenAI 兼容接口，模型可通过环境变量配置 | `src/qwen_client.py`、`src/config.py` |
| 自研 Agent Loop | 直接回答、工具调用、Observation 回填、继续循环、最大步数 | `src/agent.py` |
| 工具注册机制 | 工具包含名称、描述、JSON Schema；Registry 统一导出并执行 | `src/tool.py`、`src/registry.py` |
| 至少 3 个工具 | 共 8 个：计算、Mock 搜索、文档列表/搜索/读取、待办新增/列表/完成 | `src/tools/` |
| LLM 输出解析 | 解析公开的 `content` 与结构化 `tool_calls`，校验参数 JSON | `src/qwen_client.py` |
| 多窗口 Session | `(user_id, session_id)` 复合键隔离，SQLite 持久化并支持恢复 | `src/sqlite_session.py` |
| 持续对话与追问 | 同一 Session 恢复近期消息与摘要；动态状态通过工具按需读取 | `src/context_manager.py` |
| Context 过长压缩 | 阈值触发、保留近期完整轮次、旧消息摘要、工具链不拆分 | `src/context_manager.py` |
| 异常处理 | 工具、参数、LLM 响应、鉴权、限流、超时、最大步数均有处理 | `src/agent.py`、`src/qwen_client.py` |
| Trace / 执行日志 | 记录步骤、工具、参数、结果、耗时、成功状态与错误类型 | `src/trace.py` |
| 测试用例 | 单元、集成、Session、Context、文档工具、真实 LLM 可选测试 | `tests/`、`scenarios/` |
| AI Prompt 与过程 | 保存各轮 Prompt、问题发现、修复与验证记录 | `docs/ai-development-log.md` |

### 3. 最短运行路径

要求 Python 3.11 或更高版本。

```powershell
git clone https://github.com/cecilia10445/minimal-agent.git
cd minimal-agent

python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .

Copy-Item .env.example .env
# 编辑 .env，填写 DASHSCOPE_API_KEY

python -m src.cli --user-id user-a --session-id window-1
```

macOS / Linux 激活环境时使用：

```bash
source .venv/bin/activate
```

可以依次输入：

```text
你好，请记住我正在准备 Agent 笔试
计算 89 的平方
搜索 agent runtime
在本地文档中搜索 JavaScript
添加待办：完成录屏
列出待办
/trace
/memory
```

另开终端并使用相同 `user-id`、不同 `session-id`，即可演示同一用户的两个独立窗口：

```powershell
python -m src.cli --user-id user-a --session-id window-2
```

关闭后再次以原来的 `(user_id, session_id)` 启动，消息、摘要、待办和 Trace 会从 SQLite 恢复。

### 4. CLI 与提交材料

CLI 支持 `/new`、`/sessions`、`/switch <id>`、`/trace`、`/history`、`/memory`、`/whoami` 和 `/quit`。脚本回放方式如下：

```powershell
python -m src.cli `
  --user-id demo `
  --session-id recording `
  --script scenarios/recording-demo.txt `
  --step-delay 1
```

- 录屏流程：[`docs/recording-script.md`](docs/recording-script.md)
- 提交检查：[`docs/submission-checklist.md`](docs/submission-checklist.md)
- 系统审计：[`docs/submission-audit.md`](docs/submission-audit.md)
- AI 开发记录：[`docs/ai-development-log.md`](docs/ai-development-log.md)
- 手工测试计划：[`docs/manual-test-plan.md`](docs/manual-test-plan.md)

## 二、再看设计

### 1. Agent Runtime

`AgentRuntime.run()` 每次只处理一个用户输入：

1. 校验 `user_id`、`session_id` 和输入；
2. 恢复 Session，并在追加本轮输入前检查是否需要压缩旧历史；
3. 向 LLM 发送消息与全部工具 Schema；
4. 若模型返回一个或多个 `tool_calls`，逐个执行并写回对应的 `tool_call_id`；
5. 将工具结果作为 `tool` 消息加入 Context，再进入下一步；
6. 若模型返回文本且没有工具调用，则作为最终答案；
7. 达到最大步骤后中止，避免无界循环。

Runtime 不硬编码“某句话必须调用某个 Python 函数”。工具选择由 LLM 根据名称、描述和参数 Schema 决定；Python 只负责协议、校验、执行和状态管理。

### 2. 工具体系

默认注册 8 个工具：

| 工具 | 作用 | 状态来源 |
|---|---|---|
| `calculator` | 使用受限 AST 计算四则运算、幂、取模等表达式 | 当前调用 |
| `search` | 关键词搜索演示 | 内置 Mock 数据 |
| `list_docs` | 列出本地 Markdown 文档 | `knowledge_docs/` |
| `search_docs` | 按文件名和正文关键词检索 | `knowledge_docs/` |
| `read_docs` | 安全读取指定 Markdown，限制目录穿越与长度 | `knowledge_docs/` |
| `todo_add` | 添加当前 Session 的待办 | Session |
| `todo_list` | 读取当前 Session 的待办 | Session |
| `todo_complete` | 按 ID 完成当前 Session 的待办 | Session |

新增工具只需实现 `Tool` 接口并注册，无需修改 Agent 主循环。Registry 会将工具转换为 OpenAI Function Calling Schema；未知工具、参数不匹配和执行异常会被包装成结构化 Observation 回传给模型，由模型决定修正调用还是解释失败。

### 3. Session：窗口隔离与恢复

Session 的逻辑主键是：

```text
(user_id, session_id)
```

因此：

- `user-a/window-1` 与 `user-a/window-2` 相互独立；
- 不同用户即使使用相同 `session_id` 也相互独立；
- 重启 CLI 后可从 SQLite 恢复原窗口；
- 待办属于 Session，不会自动跨窗口共享；
- 本地知识文档是共享的只读数据源，不属于某个 Session。

每个 Session 持久化四类状态：

```text
messages   原始近期对话与工具交互
summary    被压缩的较早对话
todos      当前窗口的动态待办状态
traces     调试与执行记录
```

SQLite Store 在单进程内保留对象缓存，并在关键状态变化后立即保存，重点是实现可恢复与可审查，而不是提供分布式事务能力。

### 4. Context 与 Memory

本项目把二者分开理解：

- **Context**：某一次 LLM 调用实际看到的消息。
- **Memory**：Session 中可跨轮次、跨进程恢复的状态；只有其中一部分会在当前调用中被召回。

每次 LLM 调用的 Context 组成如下：

```text
System Prompt
+ Session Summary（存在时）
+ Session 中尚未压缩的近期 messages
+ 本轮已产生的 assistant tool_calls / tool observations
```

不同信息的召回策略：

| 信息 | 何时召回 | 放置方式 |
|---|---|---|
| 系统规则 | 每次 LLM 调用 | 第一条 `system` 消息 |
| 较早对话摘要 | Session 已发生压缩时，每次调用 | 第二条 `system` memory 消息 |
| 近期对话 | 每次调用 | 保留原始 `user` / `assistant` / `tool` 结构 |
| 当前待办 | 用户询问或操作待办时 | 通过 `todo_*` 工具实时读取，不复制进 Prompt |
| 当前文档 | 用户列出、搜索或读取文档时 | 通过文档工具实时读取 |
| Trace | 仅调试时 | 持久化但不自动放进 LLM Context |

这样处理的原因是：用户目标、偏好和追问依赖对话历史；待办列表、文件列表等动态状态则可能变化，应在需要时通过工具获取最新值，避免把过期快照当成事实。

#### 压缩触发与结构安全

默认使用字符数近似 Token：序列化消息长度除以 4。当旧消息估算值达到阈值时：

1. 从用户轮次边界切分；
2. 保留最近 4 个用户轮次及其完整交互；
3. 将更早消息合并进 `session.summary`；
4. 保证 `assistant(tool_calls) → tool result` 不被拆开；
5. 下一次构建 Context 时注入摘要与近期原文。

默认阈值为约 6000 estimated tokens，可通过以下变量调整：

```dotenv
AGENT_CONTEXT_MAX_TOKENS=6000
AGENT_CONTEXT_KEEP_RECENT_TURNS=4
AGENT_CONTEXT_MAX_SUMMARY_CHARS=3000
AGENT_CONTEXT_MAX_ITEM_CHARS=300
```

默认的确定性摘要不调用额外 API，行为可预测，失败面较小。仓库还实现了 `QwenSemanticSummarizer` 与 Hybrid 回退逻辑，用于提取目标、事实、修正、偏好和未完成事项；语义摘要失败时会回退到确定性摘要。该能力目前由实验脚本和测试直接组装，尚未接入默认 CLI，详见 [`docs/hybrid-context-design.md`](docs/hybrid-context-design.md)。

#### 关于“思考过程”

Runtime 解析模型公开返回的 `content` 和 `tool_calls`，并可将简短公开内容作为 `decision_summary` 写入 Trace。项目不请求、不解析、也不持久化模型的完整隐藏思维链。最终答案、工具决策和可审计执行记录是分开的。

### 5. 异常与 Trace

主要异常路径：

- LLM 鉴权、限流、超时和服务错误映射为明确异常；
- 非法工具参数 JSON 在适配层拒绝；
- 未知工具、参数错误、工具内部错误转成失败 Observation，允许 LLM 继续处理；
- 空响应触发 `InvalidLLMResponseError`；
- 超过步骤上限触发 `MaxStepsExceededError`；
- 语义摘要失败时回退，不阻断主对话。

每次工具执行 Trace 包含步骤号、运行编号、工具名、参数、Observation、耗时、成功状态和错误类型。Trace 便于录屏与排错，但它也可能含用户输入或工具结果，生产环境需要额外做脱敏和保留期限控制。

### 6. 测试设计

测试覆盖以下层次：

- 工具注册、Schema 和单工具行为；
- 直接回答、单工具、多工具、并行 tool calls 与追问；
- 工具错误回填、空响应与最大步数；
- 同用户跨 Session、跨用户隔离和 SQLite 重启恢复；
- Context 阈值、压缩边界、摘要注入、工具链完整性；
- 文档实时性、模糊文件名、目录穿越、超长内容截断；
- Qwen 响应解析与异常映射；
- 真实 LLM 的可选集成用例与录屏场景。

普通测试使用 `ScriptedLLMClient`，不会调用真实 API。需要真实模型的测试默认跳过，只有显式提供 Key 和开关时才运行。

```powershell
python -m pip install pytest
pytest
```

仓库开发记录中的最近一次完整自动化结果为 `270 passed, 2 skipped`。

## 三、最后声明边界

- `search` 是 Mock 搜索，不是实时互联网搜索。
- 文档检索是本地关键词匹配，不是向量数据库或 RAG；默认只处理 `knowledge_docs/` 顶层 Markdown。
- `(user_id, session_id)` 是逻辑隔离键，不包含登录、鉴权或权限系统。
- SQLite 适合本地演示；多进程同时写同一 Session 时采用最后写入覆盖，没有分布式锁。
- 压缩前的消息保存在 Session；压缩后较早原文由摘要替代，不提供独立的完整历史归档。
- Token 数量是 `字符数 / 4` 的近似值，不是模型 tokenizer 的精确结果。
- 默认 CLI 使用确定性摘要；Hybrid 语义摘要组件尚未接入 CLI 启动路径。
- `AgentRuntime` 的最大步数可由构造参数控制；当前 CLI 使用 `AGENT_MAX_RETRIES + 6` 作为步数上限，`.env.example` 中的 `AGENT_MAX_STEPS` 尚未被 CLI 读取。
- 仓库中的 Context 报告是实验快照，其中存在失败运行，不能视为已经通过的性能基线；应结合对应 `run-metadata.json` 阅读。
- 当前没有 Web UI、多 Agent、MCP、任务调度、流式输出或生产级可观测平台。

这些边界保留了项目的重点：用较少的代码完整展示 Agent 的决策循环、工具协议、Session 隔离、Memory 召回、Context 压缩和可追踪执行。
