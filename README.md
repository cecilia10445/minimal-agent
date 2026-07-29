# Minimal Agent

自研的轻量级 Agent Runtime，支持工具执行、会话持久化和上下文记忆 —— 基于 qwen3.6-plus。

**没有 LangGraph、AutoGen 等框架控制主流程。** 核心运行时完全自实现：

```
LLM 决策 → Tool Registry → 工具执行 → Observation 回填 → 继续循环或最终回答
```

## 快速体验

```powershell
# 交互式运行：
python -m src.cli --user-id demo --session-id quick-start

# 在 CLI 中输入：
# > Hello
# > 89 的平方是多少？
# > 添加待办：写文档
# > 列出所有待办
# > /trace
```

## 功能特性

- **自研 Agent Runtime** — `AgentRuntime` 实现 LLM 调用循环、工具分发、步骤计数和结果聚合
- **8 个工具**：计算器、搜索（模拟）、文档管理（列表/搜索/读取）、待办（添加/列表/完成）
- **多用户、多会话持久化** — 基于 SQLite，关闭后重新打开，待办和历史恢复
- **确定性上下文压缩** — 旧消息按规则摘要，保留最近 N 轮完整对话，工具调用与结果不拆分
- **混合语义压缩**（可选）— `AGENT_CONTEXT_SUMMARY_MODE=hybrid` 使用 qwen3.6-plus 生成语义摘要，失败时自动回退到确定性摘要
- **Trace 记录** — 每一步的工具调用、耗时、错误信息
- **270+ 自动化测试** — 普通测试不依赖真实 API
- **CLI 脚本模式** — 录制和回放演示

## 架构设计

### Agent 循环

```
用户输入
  → prepare_session()        # 压缩旧上下文（如需要）
  → 追加用户消息
  → build_messages()          # 构建 system prompt + 摘要 + 最近消息
  → LLM.complete()
  → 如果有 tool_calls：
      → 执行工具
      → 追加工具结果
      → 继续 LLM 循环
  → 否则：
      → 返回最终回答
```

### 工具系统

每个工具实现 `BaseTool`，提供 JSON Schema 输入描述。ToolRegistry 导出 OpenAI 兼容的函数 Schema，LLM 自主选择工具，无需硬编码工具路由。

### 会话与持久化

```
Session(user_id, session_id, messages, summary, todos, traces)
  → SQLiteSessionStore(upsert + 缓存)
  → 单进程内安全
  → 跨用户隔离：(user_id, session_id) 复合键
```

### 上下文与记忆

```
自动召回（始终包含）：
  System Prompt
  + Session Summary（压缩后的历史）
  + 最近 N 轮原始对话

按需召回（需调用工具）：
  Todo 列表 → todo_list 工具
  文档 → list_docs / search_docs / read_docs

不会放入 Context：
  完整隐藏思维链
  全部 Trace
  API Key
  SQLite 元数据
  完整动态 Todo 副本
```

系统解析模型公开返回的 `content`、`tool_calls` 和 final answer。在 Trace 中记录简短的 `decision_summary`，但**不会请求或持久化模型的完整隐藏思维链**。

### 异常处理

| 异常 | 处理方式 |
|---|---|
| 工具不存在/参数错误/执行错误 | 捕获后把结果回传给 LLM |
| LLM 鉴权/限流/超时 | 映射为类型化异常 |
| 超过最大步骤 | `MaxStepsExceededError` 带 Trace |
| LLM 返回无效响应 | `InvalidLLMResponseError` |
| 语义摘要失败 | 自动回退到确定性压缩 |

## 测试结果

```
270 passed, 2 skipped（真实 LLM 测试需要 DASHSCOPE_API_KEY）
```

本地运行：

```powershell
pytest
python -m compileall src tests scripts
```

## 快速开始

1. 克隆仓库并创建虚拟环境：

```powershell
git clone https://github.com/cecilia10445/minimal-agent.git
cd minimal-agent
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. 复制 `.env.example` 为 `.env` 并填入 DashScope API Key：

```powershell
copy .env.example .env
# 编辑 .env：DASHSCOPE_API_KEY=your-key-here
```

3. 运行 CLI：

```powershell
python -m src.cli --user-id demo --session-id hello
```

## CLI 命令

| 命令 | 用途 |
|---|---|
| `python -m src.cli --help` | 显示帮助 |
| `python -m src.cli --user-id u --session-id s` | 交互式会话 |
| `python -m src.cli --user-id u --session-id s --script file.txt --step-delay 1.0` | 脚本回放 |
| `python -m src.cli /trace` | 显示当前会话的 Trace |
| `python -m src.cli /memory` | 显示会话摘要 |

## 录屏演示

详见 `docs/recording-script.md`，5-8 分钟演示包含：

1. 项目结构概览
2. 直接回答
3. 计算器工具
4. 搜索 + 读取多工具链
5. 待办添加/列表/完成
6. 会话持久化（关闭后重新打开）
7. 跨会话隔离
8. Trace 展示
9. 上下文记忆展示
10. 测试结果

## 项目结构

```
minimal-agent/
├── src/
│   ├── agent.py              AgentRuntime, AgentResult
│   ├── bootstrap.py          工具注册
│   ├── cli.py                交互式 CLI
│   ├── config.py             LLM 设置、上下文策略
│   ├── context_manager.py    上下文压缩、摘要
│   ├── context_summarizer.py 语义摘要器（hybrid 模式）
│   ├── llm.py                LLMClient 协议、ScriptedLLMClient
│   ├── prompt.py             System Prompt
│   ├── qwen_client.py        OpenAI 兼容的 LLM 客户端
│   ├── recording_llm_client.py 调用记录器
│   ├── registry.py           ToolRegistry
│   ├── session.py            Session 数据类、SessionStore
│   ├── sqlite_session.py     SQLite 持久化
│   └── tools/                8 个工具实现
├── scripts/                  上下文基线、对比、演示脚本
├── scenarios/                测试场景
├── docs/                     审计、设计、录屏、开发日志
├── tests/                    270+ 自动化测试
├── knowledge_docs/           示例文档
└── .env.example              环境变量模板
```

## AI 辅助开发说明

本项目使用 AI 辅助开发（详见 `docs/ai-development-log.md`，包含各轮次的 Prompt、问题发现和修复过程）。核心 Agent Runtime、Tool Registry、Context Management 和持久化层均由本项目源码明确实现，没有外部 Agent 框架控制主流程。

## 设计边界

- **搜索工具**：模拟实现，返回预设结果，非实时网络搜索
- **文档检索**：关键词匹配，非向量 RAG
- **用户隔离**：逻辑复合键，非身份认证
- **SQLite 并发**：同一会话最后写入覆盖
- **默认 deterministic**：Hybrid 模式需显式开启
- **Token 估算**：字符数/4 近似，非精确分词
- **不支持**：多 Agent、MCP、Web UI

## 上下文基线报告

- [上下文测试计划](docs/context-baseline-test-plan.md)
- [混合上下文设计](docs/hybrid-context-design.md)
- [对比报告](reports/context-comparison.md)（需要重新运行真实 LLM，见文档说明）
