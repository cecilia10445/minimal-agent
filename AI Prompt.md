# AI Prompt 使用记录

## 1. 说明

本项目为“从零实现一个最小可用 Agent”笔试题目。

开发过程中使用了 ChatGPT、OpenCode 等 AI 工具辅助完成方案分析、代码生成、测试补充和文档整理。本人主要负责：

- 理解并拆解题目要求；
    
- 确定产品场景和功能边界；
    
- 选择技术方案；
    
- 约束 AI 不使用现成 Agent 框架接管主流程；
    
- 审查每轮实现结果；
    
- 通过真实 CLI 操作发现问题；
    
- 决定哪些功能需要补充、哪些功能不继续扩张；
    
- 设计验收场景和提交范围。


AI 主要负责：

- 根据约束给出具体实现方案；
    
- 生成或修改代码；
    
- 补充自动化测试；
    
- 根据人工测试结果定位问题；
    
- 生成开发日志和辅助文档。

**具体实现prompt轮次在ai-development-log.md**

---

## 2. 第一轮：确定最小产品范围和工具层

### 阶段目标

将题目中的抽象“最小 Agent”落到一个能够真实演示的产品场景中，并先搭建不依赖模型的基础设施。

### 我的设计方向

我将产品定位为“多 Session 个人工作助手”，而不是通用聊天机器人。

初始工具确定为：

- `calculator`
    
- `search`
    
- `read_docs`
    
- `todo_add`
    
- `todo_list`
    
- `todo_complete`
    

我要求工具不能只是写几个普通函数，而应当通过统一注册机制管理。每个工具都必须包含：

- name；
    
- description；
    
- parameters JSON Schema；
    
- execute 方法。
    

对于 Todo 状态，我要求它属于当前 Session，而不是所有用户共享。

同时明确：

- calculator 无状态；
    
- search 和本地文档属于全局只读资源；
    
- Todo 属于 Session 状态；
    
- user_id 和 session_id 由 Runtime 注入；
    
- LLM 不能通过工具参数修改当前用户或 Session。
    

### Prompt

提示词：第一轮次

### 本轮验收重点

- 是否实现统一 Tool 抽象；
    
- 是否实现 ToolRegistry；
    
- 是否具备参数校验和工具异常；
    
- 是否初步实现 SessionStore；
    
- Todo 是否按照 Session 隔离；
    
- 是否有确定性测试。
    

### 实际结果

完成工具抽象、工具注册、基础 SessionStore、6 个工具和首批自动化测试，为后续 Agent Runtime 提供稳定执行层。

---

## 3. 第二轮：实现核心 Agent Runtime

### 阶段目标

实现题目要求的核心循环，而不是依赖 LangGraph、AutoGen、OpenHands 等框架控制流程。

### 我的设计方向

我要求核心流程明确写在项目源码中：

```
接收用户输入
→ 调用 LLM
→ 判断直接回答或 Tool Call
→ Runtime 执行工具
→ Tool Result 回填模型
→ 继续循环或返回最终答案
```

我要求把模型调用抽象为 `LLMClient` 协议，使 Runtime 不依赖具体厂商。

为了能够先验证 Runtime，我接受使用 `ScriptedLLMClient` 作为测试替身，由测试预设模型返回的 Tool Call 或 Final Answer。

我还要求：

- ToolContext 必须由 Runtime 注入；
    
- 工具异常不能直接终止整个 Agent；
    
- 工具异常应转成 Observation 回填模型；
    
- 必须有最大步骤限制；
    
- 必须记录每一步 Trace；
    
- 不保存或要求模型输出完整隐藏思维链。
    

### Prompt

提示词：第二轮次

### 本轮验收重点

- Agent Loop 是否确实由 `AgentRuntime` 自己控制；
    
- LLM Client 是否只负责模型请求；
    
- 工具执行是否仍由 ToolRegistry 完成；
    
- Tool Result 是否以标准消息格式回填；
    
- 最大步骤是否生效；
    
- 工具异常后是否还能继续 Loop；
    
- 测试是否覆盖直接回答、单工具、多工具和异常。
    

### 实际结果

完成自研 Agent Runtime、LLMClient 协议、ScriptedLLMClient、Trace 和 Agent Loop 自动测试。

---

## 4. 第三轮：接入真实 qwen3.6-plus 和 CLI

### 阶段目标

将测试替身替换为真实 LLM API，并提供可操作的终端入口。

### 我的设计方向

我选择阿里云百炼 `qwen3.6-plus`，通过 OpenAI-compatible 接口接入。

我要求模型适配层只负责：

```
SDK 请求
→ SDK 响应
→ 内部 LLMResponse
```

不得在模型 Client 中执行工具或实现第二套 Agent Loop。

API Key 必须通过 `.env` 管理，不能写入源码或 Git。

CLI 需要支持：

- 普通对话；
    
- 创建 Session；
    
- 切换 Session；
    
- 查看 Session；
    
- 查看 Trace；
    
- 查看历史；
    
- 退出程序。
    

真实 API 测试必须显式开启，普通 pytest 不得消耗额度。

### Prompt

提示词：第三轮次

### 本轮验收重点

- 模型是否真实返回 Tool Call；
    
- Tool Call arguments 是否正确解析；
    
- API 认证、超时、限流和服务异常是否映射；
    
- `.env` 是否被忽略；
    
- 普通测试是否全部使用 Mock；
    
- 真实 API 测试是否默认跳过。
    

### 实际结果

完成真实 qwen3.6-plus 接入、CLI、环境变量配置和模型适配器测试。随后通过真实 CLI 验证了直接回答、搜索、Todo、计算器和工具追问链路。

---

## 5. 第四轮：修复 Trace 展示和演示数据

### 阶段目标

修复真实使用中暴露的可观察性问题。

### 我的判断

真实 CLI 使用后，我发现每次回答打印的是整个 Session 的累计 Trace，多个请求的 Step 1、Step 2 混在一起，虽然执行结果正确，但展示容易误导。

同时，Mock Search 没有 Agent Runtime 相关数据，导致模型调用了正确工具却返回空结果，不利于展示核心链路。

我决定：

- 普通回答只显示当前 run 的 Trace；
    
- `/trace` 单独显示当前 Session 全部 Trace；
    
- Trace 增加 run_id；
    
- Mock Search 增加少量稳定演示数据；
    
- 不接入真实网络搜索，避免扩大范围。
    

### Prompt

提示词：第四轮次

### 实际结果

完成 Trace 隔离、run_id 分组和搜索演示数据补全，真实 CLI 多工具执行过程可以清晰展示。

---

## 6. 第五轮：基础 Context 压缩

### 阶段目标

满足题目中“Context 过长要有基础压缩”的要求。

### 我的设计方向

我没有选择简单截断最后若干条消息，因为可能拆开：

```
assistant tool_call
→ tool result
→ assistant final answer
```

我要求以完整用户轮次为边界压缩。

当前 Context 组成确定为：

```
System Prompt
+ 可选 Session Summary
+ 最近完整原始对话
+ 当前 Tool Call 和 Tool Result
```

我决定保留：

- 用户输入；
    
- 最近几轮助手回答；
    
- Tool Call；
    
- Tool Result；
    
- 用户目标、约束和重要操作的摘要。
    

不放入：

- 完整隐藏思维链；
    
- 全部 Trace；
    
- API Key；
    
- SQLite 元数据；
    
- Todo 的完整副本。
    

Todo 等动态状态需要时通过工具查询，而不是长期复制进 Prompt。

第一版压缩采用确定性规则，避免额外调用模型，并保证自动测试稳定。

### Prompt

提示词：第五轮次

### 实际结果

完成 ContextPolicy、ContextManager、Token 粗略估算、完整轮次压缩、Session Summary 和 `/memory` 命令。

---

## 7. 第六轮：SQLite 持久化和用户隔离

### 阶段目标

解决内存 SessionStore 在关闭 CLI 后全部丢失的问题。

### 我的判断

我在多个终端测试后发现：

- 同一个进程中的 Session 可以隔离；
    
- 关闭终端后重新进入，之前的 Todo 和对话全部消失；
    
- 多个终端实际上使用的是多个互不共享的 Python 内存字典。
    

题目要求用户可以随时继续窗口 1 和窗口 2，因此只使用内存不够有说服力。

我决定引入 SQLite，但不实现完整登录、密码、JWT 或复杂权限系统。

隔离键确定为：

```
(user_id, session_id)
```

CLI 支持显式传入：

```
--user-id
--session-id
--db-path
```

### Prompt

提示词：第六轮次

### 实际结果

完成 SQLiteSessionStore、跨进程恢复、同用户不同 Session 隔离、不同用户隔离和 `/whoami`。

关闭 CLI 后重新进入相同 user_id 和 session_id，可以恢复消息、Summary、Todo 和 Trace。

---

## 8. 第七轮：完善本地文档工具链

### 阶段目标

解决 `read_docs` 只能在知道具体文件名时读取，不能查看目录和跨文档搜索的问题。

### 我的判断

人工测试中发现：

- 已知准确文件名时可以读取；
    
- 全新 Session 不知道目录中有哪些文档；
    
- 搜索本地关键词时模型可能错误调用通用 Mock Search；
    
- 旧 Session 能列出以前读取过的文件，但那只是历史记忆，不代表当前磁盘状态。
    

我确认应将本地文档能力拆成三个职责单一的工具：

```
list_docs
→ 查看当前有哪些本地文档

search_docs
→ 在本地 Markdown 文件名和正文中搜索

read_docs
→ 读取指定文档
```

通用 `search` 继续表示模拟外部公开资料搜索。

我要求工具每次执行都重新扫描目录，不能永久缓存，以便 CLI 运行期间新增或删除文件后立即生效。

### Prompt

提示词：第七轮次

### 实际结果

完成 `list_docs`、`search_docs`、增强版 `read_docs`、路由规则和真实 qwen3.6-plus 文档工具链演示。

---

## 9. 第八轮：基于人工测试收口文档链路

### 阶段目标

将人工测试发现的问题转成稳定规则、自动测试和可重复演示场景。

### 我发现的问题

1. 删除文件后，模型可能继续相信上一轮的文件列表；
    
2. 旧 Session 可能使用历史文件名替换用户当前明确输入的文件名；
    
3. Mock Search 无结果时，模型可能使用相同参数连续调用三次；
    
4. 长文档被截断后，模型没有向用户披露。
    

### 我的判断

这些问题不需要修改 Agent Runtime，也不应通过关键词 if/else 绕过模型自主决策。

我选择：

- 强化 System Prompt 中的 freshness 规则；
    
- 明确当前工具结果优先于历史记忆；
    
- 显式文件名必须忠实传递；
    
- 相同空结果不立即重复调用；
    
- 工具结果含 `truncated=true` 时必须披露；
    
- 增加人工测试计划和机器可读场景。
    

对于终端录屏，我没有使用 Playwright 操作 PowerShell，而是要求 CLI 增加 `--script` 模式，直接读取预设问题并调用真实 Runtime。

### Prompt

提示词：第八轮次

### 实际结果

完成缺陷修复、46 个人工测试用例、16 个机器场景、真实模型场景运行器、CLI 脚本模式和长文档截断检查。

---

## 10. 第九轮：Context 现状审计和可视化

### 阶段目标

在继续修改 Context 之前，先完整理解现有实现，而不是继续叠加功能。

### 我的判断

虽然 Context 已有约 39 个自动测试，但只有“测试通过”还不足以解释：

- 压缩前后消息是什么结构；
    
- Tool Call 和 Tool Result 如何保留；
    
- Summary 实际写入了什么；
    
- Todo、Trace 是否进入 Context；
    
- SQLite 中实际保存了什么；
    
- 规则摘要可能丢失什么语义。
    

因此我要求本轮不修改业务逻辑，只做源码级审计、可视化和真实 Session 检查。

### Prompt

提示词：第九轮次

### 实际结果

完成 Context 审计文档、压缩前后可视化脚本和 SQLite Session 只读检查脚本。

确认当前模型 Context 为：

```
System Prompt
+ Session Summary
+ 最近原始消息
```

Todo、Trace、decision_summary 和隐藏思维链不进入 Context。

---

## 11. 第十轮 A：确定性压缩基线评测

### 阶段目标

不修改当前压缩策略，先建立可量化基线。

### 我的设计方向

我不采用人工无意义聊天几十轮的方式，而是设计：

- 20 轮有意义的普通对话；
    
- 10 轮真实工具调用；
    
- 10 个语义保持探针；
    
- 合成边界消息回放。
    

普通对话包含：

- 项目代号；
    
- 截止时间；
    
- 回答偏好；
    
- 技术约束；
    
- 后续事实修正；
    
- 测试识别短语。
    

工具场景包含：

- calculator；
    
- search；
    
- Todo；
    
- 文档搜索和读取；
    
- 工具错误后的继续 Loop；
    
- 长文档截断。
    

指标收敛为：

- 是否触发压缩；
    
- Token 是否减少；
    
- 关键事实召回；
    
- 最新修正是否正确；
    
- Todo 状态；
    
- Tool 结构完整性；
    
- Session 隔离。
    

### Prompt

提示词：第十轮次 A

### 实际结果

完成真实长对话基线运行器、LLM 调用记录器、合成边界回放和评测报告结构。

---

## 12. 第十轮 B：Hybrid 语义压缩

### 阶段目标

在保证代码结构安全的前提下，引入真实模型语义摘要，但不将 Context 管理全部交给模型。

### 我的设计方向

我没有替换现有确定性压缩，而是设计 Hybrid 模式：

```
代码确定安全压缩边界
→ 保留最近完整轮次
→ 对旧消息调用 Qwen 生成结构化语义摘要
→ 摘要成功则使用
→ 摘要失败则回退确定性摘要
```

语义摘要只保存：

- goals；
    
- confirmed facts；
    
- latest corrections；
    
- preferences；
    
- constraints；
    
- completed actions；
    
- open items；
    
- document references。
    

我要求：

- 默认仍为 deterministic，避免意外消耗 API；
    
- Hybrid 必须显式开启；
    
- Todo、Trace 不发送给摘要模型；
    
- 不保存完整思维链；
    
- JSON 非法、超时、限流、空结果时自动回退；
    
- 摘要失败不能影响用户当前请求。
    

### Prompt

提示词：第十轮次 B

### 实际结果

完成 QwenSemanticSummarizer、Hybrid ContextManager、确定性回退、Fake 摘要测试和两种模式对比脚本。

---

## 13. 总结

整个开发过程不是一次性让 AI 自由生成项目，而是按照以下方式推进：

```
题目拆解
→ 确定最小产品范围
→ AI 分轮实现
→ 自动测试
→ 真实 CLI 验收
→ 人工发现问题
→ 定向修复
→ 再次测试
→ 形成可重复场景和文档
```

本人负责项目方向、架构边界、范围控制和最终验收；AI 工具负责提供具体实现建议和辅助生成代码。

项目最终保持“最小可用 Agent”定位，没有继续扩展向量数据库、RAG、多 Agent、MCP、Web UI 或完整身份认证系统。