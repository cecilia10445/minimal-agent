# Context-as-Built Visualization Report

Generated: 2026-07-30T01:36:45.124266

## Policy

| Parameter | Value |
|---|---|
| max_estimated_tokens | 1 |
| keep_recent_user_turns | 2 |
| max_summary_chars | 500 |
| max_item_chars | 100 |

## Compression

| Metric | Value |
|---|---|
| Triggered | True |
| Boundary index | 23 |

## Before / After

| Metric | Before | After |
|---|---|---|
| total | 4 | 4 |
| user | 2 | 2 |
| assistant | 2 | 2 |
| assistant_with_tool_calls | 1 | 1 |
| tool | 0 | 0 |

## Summary

| Metric | Value |
|---|---|
| Exists | True |
| Length (chars) | 513 |
| SHA-256 (first 16) | 5d7ff5319cb8f741 |
| Content |
| | `- 用户请求：你好，今天天气怎么样？` |
| | `- 助手回答：今天天气晴朗，气温25度。` |
| | `- 用户请求：计算 15 乘以 23` |
| | `- 调用工具：calculator，{"expression":"15*23"}` |
| | `- 工具结果（calculator）：{"ok": true, "result": "345.0"}` |
| | `- 助手回答：15 * 23 = 345` |
| | `- 用户请求：计算非法表达式` |
| | `- 调用工具：calculator，{"expression":"__import__"}` |
| | `- 工具结果（calculator）：{"ok": false, "error_type": "ToolExecutionError", "message": "Illegal expression"}` |
| | `- 助手回答：该表达式不合法，无法计算。` |
| | `- 用户请求：同时计算 100/5 和 2**8` |
| | `- 调用工具：calculator，{"expression":"100/5"}` |
| | `- 调用工具：calculator，{"expression":"2**8"}` |
| | `- 工具结果（calculator）：{"ok": true, "resul` |
| | `(较早内容已进一步压缩)` |

## Built Messages

Total messages sent to LLM: 6


## Orphan / Missing Tool Results

Orphan tool results: []
Missing tool results: ['call_wea']

## Tool Calls in Remaining Messages

- `call_wea`: search({"keywords":"tomorrow weather"})
