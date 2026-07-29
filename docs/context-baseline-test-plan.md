# 上下文基线测试计划 —— 第 10A 轮

## 为什么不用手动聊天？

手动聊天：
- **不可复现** —— 不同用户给出不同输入，导致对比无意义
- **耗时** —— 30+ 轮手动对话不切实际
- **不一致** —— 用户会忘记说过哪些事实及何时说的
- **基线差** —— 无法以相同方式重新运行进行 A/B 对比

因此，我们使用**固定的 30 轮脚本**（20 轮对话 + 10 轮工具）针对真实 qwen3.6-plus 执行。每次运行使用完全相同的输入、session_id 和 user_id。这样可获得完全可复现的基线。

## 场景设计：20 + 10

### 20 轮对话

目的：构建丰富的会话历史以：
1. 确立关键事实（项目代号、截止时间、偏好、约束）
2. 包含一次**事实修正**（截止时间从周五改为周六）
3. 包含一次**顺序变更**（任务完成顺序）
4. 讨论 Agent Runtime 设计的概念性话题（第 9-16 轮）
5. 提供足够多的轮次，使上下文压缩在 30 轮内触发

植入的关键事实：
- 项目代号：蓝色港湾
- 原始截止时间：周五晚上九点半（后被修正）
- 最终截止时间：周六上午十点
- 回答偏好：先给结论，再解释原因
- 禁止框架：LangGraph
- 学习目标：Agent Runtime + Context Management
- 完成顺序：README → 录屏 → AI 开发记录
- 测试短语：青铜罗盘31415
- 最终要求：代码链接

### 10 轮工具调用

目的：验证压缩不会破坏工具功能：
1. calculator —— 单次工具调用
2. search —— 公共信息搜索（可能返回空）
3-4. todo_add —— 两次连续添加
5. todo_list —— 状态查询
6. todo_complete —— 状态修改
7. todo_list —— 状态验证
8. read_docs（未找到）→ list_docs —— 错误恢复
9. search_docs → read_docs —— 多工具链（HiveServer2）
10. read_docs（截断）→ search_docs —— 长文档 + 结束标记

### 10 个语义探针

30 轮之后，同一会话继续回答 10 个问题：
1. 项目代号回忆
2. 最终截止时间（不得使用被覆盖的值）
3. 禁止框架
4. 回答偏好
5. 学习目标
6. 完成顺序
7. 测试短语
8. 缺少什么
9. 带工具调用的待办状态
10. 早期文档回忆

## 真实 API 与合成边界回放

### 真实 API（`scripts/run_context_baseline.py`）

- 调用真实的 qwen3.6-plus 完成全部 30 轮 + 探针 + 隔离检查
- 测量实际的压缩耗时、LLM 行为和语义召回率
- 使用 `RecordingLLMClient` 记录每次 LLM 调用
- 在 `reports/context-baseline-v1/` 下生成完整报告
- 需要 `RUN_REAL_LLM_TESTS=1` 和已配置的 `DASHSCOPE_API_KEY`

### 合成边界回放（`scripts/run_context_edge_replay.py`）

- 零 API —— 构建合成消息历史
- 覆盖 30 轮基线中未遇到的边界情况：
  - 多次并行工具调用
  - 工具错误结果
  - 工具成功但结果为空
  - 超长工具结果
  - Assistant 内容为 None
  - 事实修正
  - 不完整的轮次（无最终答案）
- 验证压缩后的结构完整性

## 语义探针事实表

| 序号 | 问题 | 必须包含 | 禁止包含 |
|---|---|---|---|
| 1 | 项目代号 | 蓝色港湾 | — |
| 2 | 最终截止时间 | 周六, 十点, 10 | 周五, 九点半, 9:30 |
| 3 | 禁止框架 | LangGraph | — |
| 4 | 回答偏好 | 先给结论, 再解释 | — |
| 5 | 学习目标 | Agent Runtime, Context Management | — |
| 6 | 完成顺序 | README, 录屏, AI 开发记录 | — |
| 7 | 测试短语 | 青铜罗盘31415 | — |
| 8 | 缺少什么 | 代码链接 | — |
| 9 | Todo 状态 | README（完成）, 录制（未完成） | — |
| 10 | Hive 文档 | HiveServer2, 端口, 10000 | — |

## 指标定义

### 压缩效率
```
compression_ratio = tokens_after / tokens_before
token_reduction_percent = (1 - compression_ratio) * 100
```

### 结构正确性
```
orphan_tool_result_count = 无对应调用的工具结果数
missing_tool_result_count = 无结果的工具调用数
```

### 语义召回
```
core_fact_recall_rate = 正确探针数 / 总探针数
```

### 隔离性
```
cross_session_leak_count = 同用户不同会话中的泄露关键词数
cross_user_leak_count = 不同用户同会话中的泄露关键词数
```

## 测试加速阈值与生产环境默认值对比

| 参数 | 测试（本轮） | 生产环境默认值 |
|---|---|---|
| `max_estimated_tokens` | 1800 | 6000 |
| `keep_recent_user_turns` | 4 | 4 |
| `max_summary_chars` | 3000 | 3000 |
| `max_item_chars` | 300 | 300 |

降低的 `max_estimated_tokens`（1800 vs 6000）确保压缩在 30 轮内触发。
所有报告已明确标注此差异。

## 如何回放

```powershell
# 零 API 边界情况回放
python scripts/run_context_edge_replay.py

# 试运行
python scripts/run_context_baseline.py --dry-run

# 完整基线（需要 API 密钥）
$env:RUN_REAL_LLM_TESTS="1"
python scripts/run_context_baseline.py `
  --scenario scenarios/context-baseline-v1.json `
  --max-estimated-tokens 1800 `
  --keep-recent-user-turns 4

# 查看结果
Get-ChildItem reports/context-baseline-v1/
```

## 如何作为第 10B 轮的基线

当前确定性压缩基线提供：

1. **指标** —— 压缩事件数、Token 减少率、结构错误、语义召回率
2. **报告** —— 完整转录、LLM 调用历史、上下文快照、探针结果
3. **数据库** —— 保存的 SQLite 会话可重新加载和分析
4. **对比点** —— 下一轮加入混合语义摘要器后，所有指标均可与此基线数据对比
