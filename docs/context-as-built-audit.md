# Context-as-Built Audit

Source-level audit of `minimal_agent` Context management based on current source code (Round 8, 189 tests passing).

---

## 1. Classes and Responsibilities

### `Session` (src/session.py:8-15)

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

| Field | Type | Purpose |
|---|---|---|
| `user_id` | `str` | Logical user identifier |
| `session_id` | `str` | Session identifier within user |
| `messages` | `list[dict[str, str]]` | Ordered conversation history (role, content, tool_calls, etc.) |
| `summary` | `str` | Deterministic text summary of compressed messages |
| `todos` | `list[dict[str, Any]]` | Todo items (not sent to LLM context) |
| `traces` | `list[dict[str, Any]]` | Step-by-step execution traces (not sent to LLM context) |

Note: The type annotation `list[dict[str, str]]` on `messages` is overly restrictive — at runtime it contains `dict[str, Any]` including `tool_calls` (list), `tool_call_id` (str), `name` (str), etc.

### `SessionStore` (src/session.py:18-38)

In-memory dict-based store. Keyed by `(user_id, session_id)` tuple.

| Method | Behavior |
|---|---|
| `get_or_create(key)` | Returns existing or creates new `Session` |
| `get(key)` | Returns `Session` or `None` |
| `list_user_sessions(uid)` | Lists all sessions for a user |
| `save(session)` | Upserts into dict |
| `clear()` | Empties all sessions |

### `SQLiteSessionStore` (src/sqlite_session.py:88-190)

SQLite-backed store with in-memory cache for object identity.

| Aspect | Detail |
|---|---|
| Table | `sessions(user_id TEXT, session_id TEXT, state_json TEXT, created_at TEXT, updated_at TEXT)` |
| PK | `(user_id, session_id)` composite |
| Serialization | `_serialize()` writes `messages`, `summary`, `todos`, `traces` as JSON |
| Deserialization | `_deserialize()` validates all 4 keys exist |
| Cache | `_cache: dict[tuple[str, str], Session]` — same Python object returned per process |
| Upsert | `INSERT ... ON CONFLICT DO UPDATE SET state_json, updated_at` |

`save()` is called at 8 points in `agent.py` (before/after every modification to session.messages, session.traces).

### `ContextPolicy` (src/context_manager.py:10-15)

```python
@dataclass(frozen=True)
class ContextPolicy:
    max_estimated_tokens: int = 6000
    keep_recent_user_turns: int = 4
    max_summary_chars: int = 3000
    max_item_chars: int = 300
```

Configurable via `src/config.py:load_context_policy()` from env vars:
- `AGENT_CONTEXT_MAX_TOKENS` → `max_estimated_tokens`
- `AGENT_CONTEXT_KEEP_RECENT_TURNS` → `keep_recent_user_turns`
- `AGENT_CONTEXT_MAX_SUMMARY_CHARS` → `max_summary_chars`
- `AGENT_CONTEXT_MAX_ITEM_CHARS` → `max_item_chars`

### `ContextManager` (src/context_manager.py:105-153)

Two public methods:

| Method | Location | Purpose |
|---|---|---|
| `prepare_session(session)` | Line 109-130 | Conditional compression: truncates old messages into summary |
| `build_messages(system_prompt, session)` | Line 132-153 | Assembles final message list for LLM |

### `AgentRuntime` (src/agent.py:42-247)

The main orchestrator. Key context-related operations:

| Operation | Location | Detail |
|---|---|---|
| `prepare_session()` call | Line 84 | Before appending user message |
| User message append | Line 86 | After compression |
| `build_messages()` call | Line 91 | Inside step loop, before every LLM call |
| Tool call append | Line 194 | assistant msg with tool_calls |
| Tool result append | Line 239-246 | tool msg per tool call |
| Assistant answer append | Line 110-112 | final assistant content msg |
| `_save_session()` calls | Lines 85, 87, 113, 123, 132, 143, 149, 159, 165, 168, 195, 247 | After every mutation |

### `LLMClient` Protocol (src/llm.py:21-29)

```python
class LLMClient(Protocol):
    def complete(self, *, messages: list[dict], tools: list[dict]) -> LLMResponse: ...
```

Implementations: `ScriptedLLMClient` (test double, `src/llm.py:32-58`), `OpenAICompatibleLLMClient` (real, `src/qwen_client.py`).

### `TraceStep` (src/trace.py:7-19)

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

## 2. Complete Data Flow

### Flow diagram with source locations

```
User Input
    │
    ▼
1. session = store.get_or_create(user_id, session_id)
   └─ src/agent.py:79
   └─ src/sqlite_session.py:112 (or src/session.py:22)
    │
    ▼
2. context_manager.prepare_session(session)
   └─ src/agent.py:84
   └─ src/context_manager.py:109
   │  ├─ estimate_tokens(session.messages) → False if < threshold
   │  ├─ find_compress_boundary() → 0 if not enough turns
   │  ├─ slice messages[:boundary] → to_compress
   │  ├─ summarize_messages(to_compress) → entries list
   │  ├─ merge_summary(existing, entries) → new summary string
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
4. FOR each step (1 to max_steps):
    │
    ├─ msgs = build_messages(system_prompt, session)
    │  └─ src/agent.py:91
    │  └─ src/context_manager.py:132
    │     ├─ [{"role": "system", "content": system_prompt}]
    │     ├─ IF summary: [{"role": "system", "content": "Session memory..." + summary}]
    │     └─ + session.messages (includes current user msg + any prior tool results)
    │
    ├─ response = llm_client.complete(messages=msgs, tools=tools_schema)
    │  └─ src/agent.py:96-98
    │
    ├─ IF tool_calls:
    │  ├─ append assistant msg (with tool_calls) → session.messages [agent.py:194]
    │  ├─ store.save(session) [agent.py:195]
    │  ├─ FOR each tool call:
    │  │  ├─ execute tool [agent.py:201]
    │  │  ├─ append trace [agent.py:237]
    │  │  ├─ append tool msg → session.messages [agent.py:239-246]
    │  │  └─ store.save(session) [agent.py:247]
    │  └─ loop back to step 4 (next iteration)
    │
    ├─ ELIF content:
    │  ├─ append assistant msg → session.messages [agent.py:110-112]
    │  ├─ store.save(session) [agent.py:113]
    │  ├─ append trace [agent.py:122]
    │  ├─ store.save(session) [agent.py:123]
    │  └─ return AgentResult [agent.py:124-129]
    │
    └─ ELSE (empty):
       ├─ store.save(session) [agent.py:132]
       ├─ append error trace [agent.py:142]
       ├─ store.save(session) [agent.py:143]
       └─ raise InvalidLLMResponseError [agent.py:144-147]
```

Key observation: `prepare_session` is called **once per run**, **before** the current user message is appended. It only compresses messages from **previous** runs, never the current turn.

---

## 3. Current Context Composition

### Final message list sent to LLM

```
Index  Role       Content
────── ────────── ──────────────────────────────────────────────
0      system     SYSTEM_PROMPT (from src/prompt.py)
1*     system     "Session memory summary. Treat this as previous
                  conversation context, but prefer current tool
                  results when conflicts exist:\n" + session.summary
2..N   user/      session.messages (remaining after compression
       assistant  + current turn's user message
       /tool      + tool_call messages + tool result messages)
```

`*` — only present if `session.summary` is non-empty.

### What IS included in context

| Data | Included | Source |
|---|---|---|
| System Prompt | ✅ Always | `src/prompt.py` |
| Summary (deterministic) | ✅ When `session.summary != ""` | `build_messages()` line 141 |
| Current user input | ✅ Appended at agent.py:86 | `session.messages` |
| Previous user inputs | ✅ Remaining after compression | `session.messages` |
| Assistant tool_call msgs | ✅ Appended at agent.py:194 | `session.messages` |
| Tool result msgs | ✅ Appended at agent.py:239-246 | `session.messages` |
| Assistant final answers | ✅ Appended at agent.py:110 | `session.messages` |
| Tool schema | ✅ Passed as `tools` param | `export_openai_schema()` |

### What is NOT included in context

| Data | Excluded? | Where stored | Why |
|---|---|---|---|
| Todo items | ❌ NOT in context | `session.todos` | Accessed via tool calls only |
| Trace steps | ❌ NOT in context | `session.traces` | CLI display / debugging only |
| `decision_summary` | ❌ NOT in context | `TraceStep.decision_summary` | For trace/debug, not model input |
| Full chain-of-thought | ❌ NOT in context | Not stored at all | Prompt says "do not output" |
| API Key | ❌ NOT in context | `os.environ` / `LLMSettings` | Never logged or serialized |
| SQLite metadata | ❌ NOT in context | SQLite `created_at`/`updated_at` | Storage-only |
| `ToolContext` | ❌ NOT in context | Created per-run | Runtime-only, not serialized |

---

## 4. Compression Trigger Conditions

### Default threshold

```python
ContextPolicy(max_estimated_tokens=6000)  # src/context_manager.py:12
```

Can be overridden via `AGENT_CONTEXT_MAX_TOKENS` env var.

### Token estimation method

```python
def estimate_tokens(messages: list[dict]) -> int:
    # src/context_manager.py:98-102
    text = json.dumps(messages, ensure_ascii=False, default=str)
    return max(1, len(text) // 4)
```

This is a **byte-length proxy** — serializes all messages to JSON, divides character count by 4. This is a rough estimator, not a real tokenizer. It counts all keys, tool_calls structures, etc.

### Judgement expression (actual code)

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
    # ... compress ...
    return True
```

Three conditions must ALL be true:
1. `estimate_tokens >= max_estimated_tokens`
2. `_find_compress_boundary() > 0` (more user turns than keep count)
3. `session.messages` is non-empty

### `prepare_session` call timing

- Called at `src/agent.py:84` — **once per `agent.run()` invocation**
- Called **before** `session.messages.append({"role": "user", "content": user_input})` (agent.py:86)
- Therefore, compression acts on the **previous run's messages**, never the current input
- Not called a second time during the step loop, even if many tool calls add many more messages

### Whether compression can trigger multiple times in one `run()`

**No.** `prepare_session()` is called once at line 84, before the step loop. The step loop (lines 90-163) appends tool_calls and tool results but never calls `prepare_session()` again. A single `run()` can add up to `max_steps` rounds of tool calls without re-evaluating for compression.

---

## 5. Compression Boundary Algorithm

### Core algorithm (`_find_compress_boundary`, src/context_manager.py:83-95)

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

**Strategy:** Count user messages, determine how many "excess" turns precede the `keep_turns` most recent ones. Walk forward and return the index of the first message of the first turn to keep.

### Examples

#### Example 1: Plain chat (2 turns, keep=4)

```
Messages: [user:q1, asst:a1, user:q2, asst:a2]
user_count = 2 ≤ 4  →  return 0  (no compression)
```

#### Example 2: Plain chat (3 turns, keep=2)

```
Messages: [user:q1, asst:a1, user:q2, asst:a2, user:q3, asst:a3]
user_count = 3 > 2
turns_to_skip = 1
Walk:
  i=0: user:q1 → seen=1, seen ≤ 1 → continue
  i=1: asst:a1
  i=2: user:q2 → seen=2, seen > 1 → return 2
```
Result: compress indices [0, 1) (messages 0-1), keep [2, 3, 4, 5].

#### Example 3: Single tool call turn (3 turns, keep=2)

```
[user:q1, asst(tc), tool, asst:final, user:q2, asst:a2, user:q3, asst:a3]
user_count = 3 > 2
turns_to_skip = 1
Walk:
  i=0: user:q1 → seen=1, seen ≤ 1 → continue
  i=1: asst(tc) → not user
  i=2: tool → not user
  i=3: asst:final → not user
  i=4: user:q2 → seen=2, seen > 1 → return 4
```
Result: compress [0..3] (entire first tool turn), keep [4..7].

#### Example 4: Parallel tool calls (2 turns, keep=1)

```
[user:q1, asst:final:q1, user:q2, asst(tc1+tc2), tool:r1, tool:r2, asst:done]
user_count = 2 > 1
turns_to_skip = 1
Walk:
  i=0: user:q1 → seen=1, seen ≤ 1 → continue
  i=1: asst:a1 → not user
  i=2: user:q2 → seen=2, seen > 1 → return 2
```
Result: compress [0..1], keep [2..6].

#### Example 5: Tool error (assistant content=null, tool fails)

Same as Example 3 — the algorithm only counts user messages, so the error messages are treated as part of their turn.

#### Example 6: Last turn has no final answer

If the last turn is `[user, asst(tc), tool]` without a final assistant message, the user_count still counts it as a turn. The boundary will be placed at the user message of the next turn to keep. The incomplete turn will be included in the kept messages.

#### Example 7: Orphan tool messages

If a tool result exists without a preceding user message (unlikely in normal operation), the algorithm would still group around user boundaries. Orphan tool messages between two user turns would be kept with the second turn.

### Critical property: user boundary alignment

The boundary always lands on a `user` message (or at the very end). This guarantees:
- Tool call sequences (assistant with tool_calls → zero or more tool results → assistant final) are **never split** across the compress boundary.
- No orphan `tool` messages in the remaining messages (all tool results belong to turns that are fully kept).
- The to_compress slice starts at index 0, always a coherent sequence of complete turns.

---

## 6. Current Summary Format

### `_summarize_messages` (src/context_manager.py:24-56)

Each message role is converted to a deterministic text line:

| Role | Pattern | Example |
|---|---|---|
| user | `- 用户请求：{content}` | `- 用户请求：Calculate 15 * 23` |
| assistant (with tool_calls) | `- 调用工具：{name}，{args}` | `- 调用工具：calculator，{"expression":"15*23"}` |
| tool | `- 工具结果（{name}）：{content}` | `- 工具结果（calculator）：{"ok":true,"result":"345.0"}` |
| assistant (final) | `- 助手回答：{content}` | `- 助手回答：15 * 23 = 345` |

### Character truncation per item

Each item is truncated to `max_item_chars` (default 300) via:
```python
def _truncate(text: str, max_chars: int) -> str:
    return text[:max_chars] + "..."
```

### Summary merge (`_merge_summary`, src/context_manager.py:59-80)

```python
def _merge_summary(existing: str, new_entries: list[str], max_chars: int) -> str:
```

| Scenario | Behavior |
|---|---|
| No existing summary | Use new_entries; truncate if exceeds max_chars |
| Combined fits | `existing + "\n" + new_text` |
| Combined exceeds | Reserve 50 chars for truncation marker; try to keep all new_text |
| New text too long | Truncate new_text to `max_chars - 50` |
| New fits, old too long | Keep last `max_chars - len(new_text) - 1` chars of old |
| Very little room | Discard old, return new_text + truncation marker |

### Real summary example

For a compressed session with 2 plain turns and 1 tool turn:

```
- 用户请求：What is the weather today?
- 助手回答：It is sunny and 25 degrees.
- 用户请求：Calculate 15 * 23
- 调用工具：calculator，{"expression":"15*23"}
- 工具结果（calculator）：{"ok":true,"result":"345.0"}
- 助手回答：15 * 23 = 345
```

### `None` content handling

```python
# Line 31-32
content = msg.get("content", "")
if content is None:
    content = ""
```

Assistant tool_call messages typically have `"content": null`, which is converted to empty string and summarized as `- 助手回答：` (for the `assistant` without tool_calls branch). But if it has `tool_calls` key, it's caught by the earlier branch at line 35:
```python
elif msg.get("role") == "assistant" and "tool_calls" in msg:
```

So tool_call messages never hit the "assistant" text branch.

---

## 7. SQLite Persistence

### Serialization (`_serialize`, src/sqlite_session.py:38-48)

```python
def _serialize(session: Session) -> str:
    return json.dumps({
        "messages": session.messages,
        "summary": session.summary,
        "todos": session.todos,
        "traces": session.traces,
    }, ensure_ascii=False, default=str)
```

### Deserialization (`_deserialize`, src/sqlite_session.py:51-67)

Validates:
- JSON is valid
- Root is a dict
- All 4 keys exist

If JSON is corrupted: raises `SessionPersistenceError`.

### Per-field handling

| Field | Stored as | Restored to |
|---|---|---|
| `messages` | Full JSON array | `Session.messages` (same structure) |
| `summary` | Plain string | `Session.summary` |
| `todos` | Full JSON array | `Session.todos` |
| `traces` | Full JSON array | `Session.traces` |

All fields survive `save()` → process restart → `get_or_create()` intact.

### `session.summary` persistence

`summary` is a string field in the dataclass, serialized as a JSON string value. It is **not** a separate SQLite column — it lives inside `state_json`. Its value is preserved across process restarts.

---

## 8. Test Mapping (`tests/test_context_manager.py`)

Total: **39 test functions** across 11 test classes + 1 standalone.

### Token Estimation (3 tests)

| Test | Assertion |
|---|---|
| `test_empty_returns_zero` | `estimate_tokens([]) == 0` |
| `test_non_empty_at_least_one` | `estimate_tokens([{"role":"user","content":"hi"}]) >= 1` |
| `test_includes_tool_calls` | Estimate includes tool_call + tool_result in count |

### Truncation (2 tests)

| Test | Assertion |
|---|---|
| `test_short_unchanged` | `_truncate("hello", 10)` returns `"hello"` |
| `test_long_truncated` | `_truncate("hello world", 5)` returns `"hello..."` (8 chars) |

### Boundary Identification (6 tests)

| Test | Assertion |
|---|---|
| `test_no_messages` | `_find_compress_boundary([], 4) == 0` |
| `test_fewer_turns_than_keep` | 1 turn with keep=4 → 0 |
| `test_exact_turns_no_compress` | 2 turns with keep=2 → 0 |
| `test_more_turns_than_keep` | 3 turns with keep=2 → boundary at index 2 |
| `test_more_turns_keeps_last_n` | 4 turns with keep=2 → boundary at index 4 |
| `test_tool_turns_boundary` | 3 turns (1 tool turn) with keep=2 → boundary at index 4 |

### Summary Generation (4 tests)

| Test | Assertion |
|---|---|
| `test_user_and_assistant` | Entries contain "用户请求" and "助手回答" |
| `test_tool_calls_summarized` | Entries contain "调用工具" and "工具结果" |
| `test_long_content_truncated` | Long content has "..." |
| `test_content_none_handled` | `None` content handled gracefully |

### Summary Merge (4 tests)

| Test | Assertion |
|---|---|
| `test_no_existing` | New entries become the summary |
| `test_combines_existing_and_new` | Both old and new appear |
| `test_trims_when_exceeds_max` | Length ≤ max_chars + slack |
| `test_prefers_newer_content` | New content retained over old |

### Session Compression (8 tests)

| Test | Assertion |
|---|---|
| `test_no_compress_when_below_threshold` | Returns False, messages unchanged |
| `test_compress_when_above_threshold` | Returns True, messages reduced |
| `test_keeps_recent_turns` | Keeps last 2 user turns (4 messages) |
| `test_no_compress_if_empty` | Empty messages → False |
| `test_summary_created_after_compress` | Summary non-empty, contains compressed content |
| `test_tool_call_not_split_from_result` | All 4 messages of tool turn kept, `remaining[0]` is "user" |
| `test_parallel_tool_calls_preserved` | 5 messages kept (user + 2 parallel tool_calls + 2 results + done) |
| `test_summary_length_limited` | Summary length ≤ max_summary_chars + slack |

### Session Isolation (2 tests)

| Test | Assertion |
|---|---|
| `test_session_a_not_affect_b` | Session A compressed does not affect Session B |
| `test_todos_and_traces_untouched` | Compression does not modify todos or traces |

### Message Building (4 tests)

| Test | Assertion |
|---|---|
| `test_no_summary_no_extra_message` | 3 messages: system + user + assistant |
| `test_with_summary_injected` | 3 messages: system + system(summary) + user |
| `test_summary_position_after_system` | Summary is 2nd message (after system prompt, before user) |
| `test_current_user_input_preserved` | Current user input appears in built messages |

### AgentRuntime Integration (4 tests)

| Test | Assertion |
|---|---|
| `test_llm_receives_summary_after_compress` | Summary in call_history after compression |
| `test_plain_chat_after_compress_still_works` | Second answer returned correctly |
| `test_todo_after_compress_still_accessible` | Todos survive compression |
| `test_normal_pytest_no_real_api` | ScriptedLLMClient used (index incremented) |

### Existing Tests Not Broken (1 test)

| Test | Assertion |
|---|---|
| `test_agent_tests_import` | Module imports without error |

---

## 9. Current Limitations and Risks

### 9.1 Rule-based summary loses implied semantics

The deterministic `_summarize_messages` uses fixed Chinese templates (`- 用户请求：`). It:
- Does NOT infer intent, sentiment, or implicit constraints
- Does NOT distinguish between a question and a command
- Loses the conversational nuance of the original exchange

Example: "I think it might rain" vs "Close the window" both become `- 用户请求：{exact text}`.

### 9.2 Fact correction is not special-cased

If a user says "My name is Alice" in turn 1 and "Actually, call me Bob" in turn 3:
- Turn 1 might be compressed into summary
- Summary records "用户请求：My name is Alice"
- No mechanism recognizes this as superseded information
- LLM receiving both the summary (Alice) and kept turn (Bob) could experience confusion

### 9.3 Repetitive information accumulates

Each compressed turn adds entries to the summary. Over many sessions, the summary grows and gets trimmed from the bottom (oldest content). But repeated information across turns (e.g., `- 工具结果（read_docs）：{truncated content}`) is preserved without deduplication.

### 9.4 Extra-long tool results

Tool results are serialized as JSON including the full result string:
```python
observation = json.dumps({"ok": True, "result": result}, ensure_ascii=False)
```

When this is summarized:
```python
content = msg.get("content", "")  # the full JSON string
entries.append(f"- 工具结果（{name}）：{_truncate(content, max_item_chars)}")
```

Default `max_item_chars=300` means long results (read_docs returning 10,000 chars) are truncated to 300 chars + "...". Semantically important content beyond 300 chars is silently lost in the summary.

### 9.5 Document read results are heavily truncated

A read_docs result may contain 10,000+ characters. After summarization, only the first 300 characters are retained. The summary loses:
- Which document was read
- The actual content after 300 chars
- Whether the result was truncated

### 9.6 User preferences and constraints degrade

If a user says "Always use Chinese" in turn 2, this statement:
- Is compressed into `- 用户请求：Always use Chinese`
- Becomes a detached text line, not a persistent instruction
- After multiple compressions, could be trimmed from the summary if space is needed for newer content

### 9.7 Stale dynamic state in old summaries

Summary entries like `- 工具结果（list_docs）：{"ok": true, "result": "file1, file2"}` represent past disk state. If the summary is injected as "current context", the LLM may mistakenly treat old file lists as current — even though Rule 13 says "prefer current tool results". The LLM must be relied upon to make this distinction.

### 9.8 No hallucination guard (currently)

The current summary is purely deterministic text extraction — no LLM involvement, so no hallucination risk. However:
- The `_truncate()` function appends `"..."` without structural markers
- Truncated JSON in tool results may look incomplete but the LLM might still try to use it
- The truncation point falls at an arbitrary character boundary, not a semantic boundary

### 9.9 Risks after LLM summary integration

When LLM semantic summarization is added, new risks include:
- **Hallucinated summary facts** — LLM could "remember" things that never happened
- **Contradiction between summary and recent messages** — LLM must resolve conflicts
- **Loss of critical details** — LLM may deem unimportant what the user considers important
- **Prompt injection via summary** — if a compressed message contained injected instructions, an LLM-powered summarizer might propagate them
- **Increased cost and latency** — each compression triggers an additional LLM call

---

## 10. Mixed Compression Integration Design Points

Based on the current code, the following are the precise interfaces and locations suitable for introducing Semantic Summarizer components. No implementation code is provided.

### 10.1 SemanticSummarizer Protocol — `_summarize_messages` replacement

**Current location:** `src/context_manager.py:24-56`, function `_summarize_messages()`

**Current signature:**
```python
def _summarize_messages(messages: list[dict], max_item_chars: int) -> list[str]:
```

**Design interface:**
```python
class SemanticSummarizer(Protocol):
    def summarize(self, messages: list[dict], max_chars: int) -> str: ...
```

This is the most natural injection point. `prepare_session()` line 124 calls `_summarize_messages(to_compress, ...)` and receives a `list[str]` of entries. A `SemanticSummarizer` would return a single coherent summary string instead.

**Options:**
- `DeterministicSummarizer` — current logic, acts as fallback
- `QwenSemanticSummarizer` — calls LLM to produce a natural-language summary
- `FallbackSummarizer` — tries LLM, falls back to deterministic on error

### 10.2 ContextManager injection point — constructor parameter

**Current:** `ContextManager.__init__` line 106 takes only `ContextPolicy`

```python
class ContextManager:
    def __init__(self, policy: ContextPolicy | None = None) -> None:
```

**Design:** Add optional `summarizer: SemanticSummarizer | None = None` parameter. If summarizer is provided, use it in `prepare_session()`. If not, fall back to current deterministic logic.

### 10.3 Compression event notification — `prepare_session` return value

**Current:** `prepare_session()` returns `bool` (whether compression occurred).

```python
def prepare_session(self, session: Session) -> bool:
```

**Design:** Could return a `CompressionEvent` dataclass containing:
- `compressed: bool`
- `messages_before: int` / `messages_after: int`
- `summary_before_len: int` / `summary_after_len: int`
- `summarizer_used: str` ("deterministic" | "semantic")
- `tokens_saved: int`

### 10.4 ContextMetrics reporting — before/after `prepare_session`

**Current:** `agent.py:84` calls `prepare_session()` and ignores the bool.

**Design:** Both `ContextManager` and `AgentRuntime` could maintain metrics counters:
- Number of compressions
- Total tokens compressed
- Summarizer type distribution

### 10.5 Summary storage — `session.summary` already exists

**Current:** `session.summary: str` stores the compressed text.

**Design:** No schema change needed. LLM-generated summaries would also be stored as a plain string. A future enhancement could add `summary_type: str` ("deterministic" | "semantic") and `summary_version: int` fields to `Session`.

### 10.6 LLM call for summarization — when and how

**Design considerations:**

- `prepare_session()` is currently called synchronously in `agent.run()`.
- An LLM-based summarizer would make the first user response slower.
- Options:
  1. **Synchronous in prepare_session** — simple, predictable
  2. **Async/deferred** — summarization happens after returning the current response, but requires background processing
  3. **On-demand** — summarize only at explicit trigger (e.g., token threshold)
- The `ScriptedLLMClient` or a dedicated summarization LLM client should be used, not `qwen_client` directly.

### 10.7 Fallback strategy — `_merge_summary` compatibility

**Current:** `_merge_summary()` appends new entries to existing summary.

**Design:** The merge strategy changes fundamentally with LLM summary. Instead of text concatenation:
- LLM receives `existing_summary + "\n" + new_messages_text` and produces a single coherent summary
- Fallback: if LLM call fails, use current `_summarize_messages` + `_merge_summary`

### 10.8 No-change zones

These areas should NOT be modified by a summarization inject:
- `_find_compress_boundary()` — boundary logic stays unchanged
- `build_messages()` — message assembly pattern stays unchanged
- `AgentRuntime.run()` — the orchestration pattern stays unchanged
- `Session` schema — no new fields needed for this phase
- `SQLiteSessionStore` — `state_json` format unchanged
