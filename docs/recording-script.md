# 录制脚本 — 5-8 分钟演示

## 前置条件

- `.env` 已配置有效的 `DASHSCOPE_API_KEY`
- 虚拟环境已激活
- 工作目录为项目根目录

## 清理旧数据

每次录制前运行以确保全新开始：

```powershell
Remove-Item -Force data\demo-recording.db -ErrorAction SilentlyContinue
Remove-Item -Force data\demo-recording-2.db -ErrorAction SilentlyContinue
```

## 场景

### 场景 1：项目结构与 AgentRuntime（30 秒）

用 `tree` 或 `ls` 展示项目结构。打开 `src/agent.py`，指出 `AgentRuntime` 类、`run()` 方法和 `_handle_tool_calls()`。

### 场景 2：直接回答（30 秒）

```powershell
python -m src.cli --user-id demo --session-id recording
```

输入：

```
> Hello
```

预期：Agent 回复问候语。

### 场景 3：计算器工具（30 秒）

```
> 89 的平方是多少？
```

预期：Agent 调用计算器工具，返回 7921。

### 场景 4：多工具链 — 搜索 + 阅读（1 分钟）

```
> 在知识库中搜索 HiveServer2 端口排查
```

预期：Agent 调用 `search_docs`，找到 HiveServer2 文档。

```
> 阅读并总结根因
```

预期：Agent 调用 `read_docs`，读取文档，总结 HiveServer2 端口 10000 的问题。

### 场景 5：待办添加/列表/完成（1 分钟）

```
> 添加待办：写文档
```

预期：Agent 调用 `todo_add`。

```
> 添加待办：录制演示
```

预期：Agent 调用 `todo_add`。

```
> 列出我的待办
```

预期：Agent 调用 `todo_list`，显示两项。

```
> 完成第一个待办
```

预期：Agent 调用 `todo_complete`。

```
> 再次列出待办
```

预期：Agent 显示一项已完成、一项待办。

### 场景 6：会话持久化（1 分钟）

退出 CLI（`Ctrl+C` 或 `/exit`）。

```powershell
python -m src.cli --user-id demo --session-id recording
```

```
> 列出我的待办
```

预期：之前的待办仍然存在。

### 场景 7：跨会话隔离（30 秒）

退出 CLI。

```powershell
python -m src.cli --user-id demo --session-id another-session
```

```
> 列出我的待办
```

预期：空列表 — 不同会话不共享待办。

### 场景 8：系统命令（30 秒）

```
> /trace
```

预期：显示当前会话的步骤追踪。

```
> /memory
```

预期：显示会话摘要（如果已发生过压缩）。

### 场景 9：测试结果（30 秒）

退出 CLI。在终端中：

```powershell
pytest --tb=short -q
```

预期：显示 270 passed, 2 skipped。

## 总时长

约 5-6 分钟。清晰表述，工具调用间稍作停顿。

## 替代方案：脚本化回放

使用已有的录制演示脚本进行全自动运行：

```powershell
python -m src.cli --user-id demo --session-id recording --script scenarios/recording-demo.txt --step-delay 2.0
```

调整 `--step-delay` 控制播放速度。
