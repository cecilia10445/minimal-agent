# Context Baseline Report — Round 10A

Generated: 2026-07-30T02:25:21.556669

Status: **FAILED**

- Semantic probe recall: 8/10

## Run Metadata

| Field | Value |
|---|---|
| user_id | user-c |
| session_id | context-baseline-v1 |
| db_path | reports\context-hybrid\context-baseline.db |
| max_estimated_tokens | 1800 |
| keep_recent_user_turns | 4 |
| is_accelerated threshold | False |
| production default max_tokens | 6000 |

## Compression

| Metric | Value |
|---|---|
| Compression events | 30 |
| Tokens before (total) | 21302 |
| Tokens after (total) | 26347 |
| Avg compression ratio | 1.223 |
| Max token reduction | 20.3% |

## Structural Integrity

| Metric | Value |
|---|---|
| Orphan tool results | 0 |
| Missing tool results | 0 |

## Semantic Probes

| Metric | Value |
|---|---|
| Recall | 8/10 |
| Rate | 0.8 |

## Isolation

| Metric | Value |
|---|---|
| Cross-session leak count | 0 |
| Cross-user leak count | 0 |

## Overhead

| Metric | Value |
|---|---|
| Real LLM calls | 53 |
| Answer chars total | 2252 |
| Total latency | 123453ms |
| Compression API calls (deterministic) | 0 |
