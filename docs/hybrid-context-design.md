# Hybrid Context Compression Design

## 1. Why Not Fully Replace Deterministic Compression

Deterministic compression is reliable, predictable, and zero-cost. It guarantees:
- No API dependency
- Bounded latency
- Deterministic output
- No credential exposure

Hybrid mode adds semantic summarization only when explicitly enabled, and always falls back to deterministic on failure.

## 2. Code Responsibilities

The Python code layer is **always** responsible for structural integrity:

- Finding the compression boundary via `_find_compress_boundary()`
- Preserving recent N raw user turns
- Keeping tool call ↔ tool result pairs intact
- Ensuring no orphan/missing tool results
- Managing `session.summary` and `session.messages`

The semantic summarizer only processes the **old messages** that are already slated for compression. It does not make structural decisions.

## 3. Qwen's Role

Qwen (via `QwenSemanticSummarizer`) handles **semantic abstraction** of old conversation history:

- Extracts goals, facts, corrections, preferences
- Produces structured JSON
- Follows correction priority (newer overrides older)
- Avoids fabricating information

The summarizer receives:
- `previous_summary`: existing compressed context
- `messages`: the old messages being compressed
- `max_output_chars`: character budget

## 4. Recent Turns Are Always Preserved

`keep_recent_user_turns` (default: 4) ensures the most recent user-assistant exchanges remain in raw message form. The summarizer never sees or influences these.

## 5. Dynamic State via Tools

Todo items, file listings, and other dynamic state are **not** captured in the semantic summary. They remain accessible only through explicit tool calls (`todo_list`, `list_docs`, etc.). This prevents stale data from being treated as ground truth.

## 6. Failure Fallback

All of these trigger deterministic fallback:

| Failure | Handling |
|---|---|
| API timeout | Catch exception → fallback |
| Auth error | Catch exception → fallback |
| Rate limit | Catch exception → fallback |
| Network error | Catch exception → fallback |
| Empty response | Detect empty → fallback |
| Invalid JSON | Parse error → fallback |
| Bad field types | Validation error → fallback |
| Output too long | Truncate after formatting |

Fallback does **not** propagate to the user — the Agent Loop continues normally.

## 7. Default Mode

The default mode is `deterministic`. Hybrid mode must be explicitly enabled:

```dotenv
AGENT_CONTEXT_SUMMARY_MODE=hybrid
```

## 8. Metrics Comparison

Only five categories are compared between modes:

1. **Compression**: event count, token reduction %
2. **Fact recall**: rate from semantic probes
3. **Latest corrections**: correct deadline value
4. **Structure**: orphan/missing tool results, isolation leaks
5. **Overhead**: semantic call count, fallback count, latency
