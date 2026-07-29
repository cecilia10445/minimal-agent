# 提交通知单

GitHub 发布的最终质量门禁。

## 必查项（阻塞 —— 须全部通过）

| 检查项 | 结果 | 备注 |
|---|---|---|
| `pytest` — 全部测试通过 | 通过 | 270 passed, 2 skipped（真实 LLM 跳过） |
| `python -m compileall src tests scripts` | 通过 | 无语法错误 |
| git diff --check | 通过 | 无空格错误 |
| 源码中无 API 密钥 | 通过 | 通过 `scripts\check_secrets.py` 检查 |
| git 历史中无 API 密钥 | 通过 | 无含密钥的提交 |
| 未提交 `.env` | 通过 | 已在 `.gitignore` 中 |
| 未提交 `data/*.db` | 通过 | 已在 `.gitignore` 中 |
| 未提交 `reports/**/*.db` | 通过 | 已加入 `.gitignore` |
| 未提交 `__pycache__` / `.pytest_cache` | 通过 | 已在 `.gitignore` 中 |
| README 命令可执行 | 通过 | 已验证 `python -m src.cli --help` |
| 知识文档已脱敏 | 通过 | 敏感内容已移除；仅有示例文档 |
| 核心需求已实现（25/25） | 通过 | 见 `docs/submission-audit.md` |
| Git 远程已配置 | 通过 | `origin → https://github.com/cecilia10445/minimal-agent.git` |
| 分支为 `main` | 通过 | |

## 非必查项（建议）

| 检查项 | 结果 | 备注 |
|---|---|---|
| 真实 LLM 重新运行完成 | 失败 | DashScope 免费配额耗尽 —— 代码修复已验证，重新运行需充值配额 |
| 上下文对比报告已生成 | 失败 | 需要重新运行（配额耗尽）—— 见 `reports/context-comparison.md` 占位文件 |
| 语义探针 10/10 | 失败 | 真实混合模式运行 8/10（2 个评分器假阴性已修复） |
| 上下文基线指标准确 | 失败 | 旧报告的事件计数有缺陷 —— 代码已修复，需要重新运行 |
| 录制脚本已验证 | 手动 | 按 `docs/recording-script.md` 操作 —— 需要 API 密钥 |
| .env.example 完整 | 通过 | 所有环境变量已记录 |

## 最终决定

**所有必查项通过。准备推送。**

非必查项的失败已记录：
1. API 配额耗尽无法重新运行上下文基线
2. 旧报告指标已保留但存在计算缺陷（当前代码已修复）
3. README 已如实反映这些限制
