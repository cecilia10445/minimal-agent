# Manual Test Plan — minimal_agent

This document records all manually executed test scenarios for the minimal_agent project.

Status labels:
- ✅ **Passed** — test completed successfully
- ❌ **Failed** — test exposed a defect (now fixed, needs re-test)
- 🔄 **Needs re-test** — failed scenario after fix
- ⏳ **Not executed** — planned but not yet run
- ❓ **Under discussion** — open design question

---

## A. Basic Agent Loop

### A-001: Direct greeting
| Field | Value |
|---|---|
| Purpose | Verify agent answers directly without tool calls |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | Fresh session, knowledge_docs with some files |
| Execution | `python -m src.cli --user-id test --session-id test-a001` |
| User input | `你好，你能做什么？` |
| Expected tool chain | (none — direct answer) |
| Expected result | Agent responds with greeting and capability summary |
| Actual result | ✅ Agent returned greeting with tool list |
| Status | ✅ Passed |
| Cleanup | None |

### A-002: Calculator tool
| Field | Value |
|---|---|
| Purpose | Verify calculator tool invocation |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | Fresh session |
| User input | `请使用计算器计算 89 的平方。` |
| Expected tool chain | calculator |
| Expected result | Answer includes 7921 |
| Actual result | ✅ Calculator called, 89^2 = 7921 |
| Status | ✅ Passed |
| Cleanup | None |

### A-003: search + todo_add multi-tool
| Field | Value |
|---|---|
| Purpose | Verify chaining search then todo_add |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | Fresh session |
| User input | `搜索一下 Agent Runtime 的定义，然后添加到待办` |
| Expected tool chain | search → todo_add |
| Expected result | Search finds definition, todo is added |
| Actual result | ✅ search found definition, todo added |
| Status | ✅ Passed |
| Cleanup | `/new` or ignore |

### A-004: Todo list with follow-up
| Field | Value |
|---|---|
| Purpose | Verify listing after add |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | Previous session has todos |
| User input | `查看我的待办` |
| Expected tool chain | todo_list |
| Expected result | Lists all pending todos |
| Status | ✅ Passed |
| Cleanup | None |

### A-005: Max steps / tool error
| Field | Value |
|---|---|
| Purpose | These are covered by automated tests (test_agent.py) |
| Type | Automated |
| API required | No |
| Status | ✅ Covered by test_agent.py |

---

## B. Session and Persistence

### B-001: Same session follow-up
| Field | Value |
|---|---|
| Purpose | Verify agent remembers context within same session |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | Fresh session |
| User input | Round 1: `我的名字是张三` → Round 2: `我叫什么名字？` |
| Expected tool chain | Round 1: direct answer; Round 2: direct answer from memory |
| Expected result | Round 2 correctly recalls "张三" |
| Actual result | ✅ Agent remembered name across turns |
| Status | ✅ Passed |
| Cleanup | None |

### B-002: CLI restart session recovery
| Field | Value |
|---|---|
| Purpose | Verify session persistence across CLI restart |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | Previous session with todos and conversation |
| Execution | Exit CLI, restart with same `--user-id test --session-id test-b002` |
| User input | `查看我的待办` |
| Expected result | Previous todos restored |
| Actual result | ✅ Todos persisted after restart |
| Status | ✅ Passed |
| Cleanup | None |

### B-003: Same user, different session isolation
| Field | Value |
|---|---|
| Purpose | Verify `/new` creates isolated session |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | Session exists with todos |
| Steps | `/new` → check todos |
| Expected result | New session has no todos |
| Actual result | ✅ New session empty |
| Status | ✅ Passed |
| Cleanup | None |

### B-004: Different user, same session_id isolation
| Field | Value |
|---|---|
| Purpose | Verify user isolation |
| Type | Automated |
| API required | No |
| Status | ✅ Covered by tests |

### B-005: /whoami
| Field | Value |
|---|---|
| Purpose | Verify identity display |
| Type | Manual |
| API required | No |
| Steps | `/whoami` |
| Expected result | Shows user_id, session_id, db_path |
| Actual result | ✅ Correct display |
| Status | ✅ Passed |

### B-006: SQLite cross-process recovery
| Field | Value |
|---|---|
| Purpose | Verify different Python process reads same DB |
| Type | Manual |
| API required | No |
| Status | ✅ Covered by test_sqlite_session.py |

---

## C. Document Dynamic Scan

### C-001: Dynamic new file detected
| Field | Value |
|---|---|
| Purpose | Verify list_docs detects newly created file without restart |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | CLI running, knowledge_docs exists |
| Steps | Create `唯一测试文档.md` before start, then ask `请列出所有本地文档` |
| Expected tool chain | list_docs |
| Expected result | New file appears in listing |
| Actual result | ✅ list_docs returned correct listing |
| Status | ✅ Passed |
| Cleanup | Delete temp file |

### C-002: Read newly created dynamic file
| Field | Value |
|---|---|
| Purpose | Verify read_docs works on dynamically added file |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | `__agent_dynamic_demo__.md` exists with known content |
| User input | `读取 __agent_dynamic_demo__.md` |
| Expected tool chain | read_docs |
| Expected result | Content displayed correctly |
| Actual result | ✅ Content read successfully |
| Status | ✅ Passed |
| Cleanup | Delete temp file |

### C-003: search_docs on dynamic content
| Field | Value |
|---|---|
| Purpose | Verify search_docs finds content in dynamic file |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | Dynamic file with keyword "蓝色鲸鱼2468" |
| User input | `搜索蓝色鲸鱼2468` |
| Expected tool chain | search_docs |
| Expected result | Dynamic file found |
| Actual result | ✅ Search found the keyword |
| Status | ✅ Passed |
| Cleanup | None |

### C-004: Dynamic delete detected
| Field | Value |
|---|---|
| Purpose | Verify list_docs reflects file deletion without restart |
| Type | Manual — CLI |
| API required | Yes |
| Steps | 1. Create `临时新增测试.md`; 2. list_docs shows 5 files; 3. Delete file; 4. Ask "目前本地知识库有哪些文档?" |
| Expected tool chain | list_docs (must re-call, not use history) |
| Expected result | Second listing shows 4 files |
| Actual result | ❌ Agent used cached history, reported 5 instead of 4. Only re-called after user pushed "你确定吗". **Defect #1 identified.** |
| Status | ❌ **Defect #1 — SEE FIX** |
| Cleanup | Ensure temp file is deleted |

### C-005: Dynamic delete — re-test after fix
| Field | Value |
|---|---|
| Purpose | Verify list_docs is re-called when asking current state |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | Fix applied for freshness rules |
| Status | 🔄 Needs re-test |
| Cleanup | None |

---

## D. Natural Language Routing

### D-001: search_docs from description
| Field | Value |
|---|---|
| Purpose | Verify route to search_docs for "find JavaScript doc" |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | knowledge_docs contains JavaScript-related files |
| User input | `我记得本地有一份介绍 JavaScript 的资料，你帮我找到它` |
| Expected tool chain | search_docs |
| Expected result | Returns matching documents |
| Actual result | ✅ search_docs called, found JavaScript docs |
| Status | ✅ Passed |
| Cleanup | None |

### D-002: read_docs after search_docs
| Field | Value |
|---|---|
| Purpose | Verify reading a previously found document |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | Search_docs returned candidates |
| User input | `把刚才找到的文档读一下` |
| Expected tool chain | read_docs |
| Expected result | Document content displayed |
| Actual result | ✅ Document read successfully |
| Status | ✅ Passed |
| Cleanup | None |

### D-003: Single-turn search → read → summarize
| Field | Value |
|---|---|
| Purpose | Verify full chain: search_docs → read_docs → final answer |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | knowledge_docs has JavaScript doc |
| User input | `在本地知识库中找到介绍 JavaScript 的文档，读取后总结三个重点` |
| Expected tool chain | search_docs → read_docs |
| Expected result | Summary of three key points |
| Actual result | ✅ Chain completed, three points summarized |
| Status | ✅ Passed |
| Cleanup | None |

### D-004: Local search vs public search distinction
| Field | Value |
|---|---|
| Purpose | Verify local docs search uses search_docs, not search |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | knowledge_docs has local files |
| User input | `在本地知识库搜索"Agent Runtime"` |
| Expected tool chain | search_docs (not search) |
| Expected result | search_docs called, no forbidden_tools search |
| Actual result | ✅ search_docs used correctly |
| Status | ✅ Passed |
| Cleanup | None |

---

## E. Fuzzy Matching

### E-001: Exact Chinese filename
| Field | Value |
|---|---|
| Purpose | Verify exact Chinese filename read |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | File `唯一测试文档.md` exists |
| User input | `读取 唯一测试文档.md` |
| Expected tool chain | read_docs |
| Expected result | File content returned |
| Actual result | ✅ Correct content returned |
| Status | ✅ Passed |
| Cleanup | None |

### E-002: Auto-append .md
| Field | Value |
|---|---|
| Purpose | Verify .md extension auto-append |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | File `readme.md` exists |
| User input | `读取 readme` |
| Expected tool chain | read_docs |
| Expected result | Content of readme.md |
| Actual result | ✅ Auto-appended .md, read correctly |
| Status | ✅ Passed |
| Cleanup | None |

### E-003: Single fuzzy candidate
| Field | Value |
|---|---|
| Purpose | Verify unique fuzzy match succeeds |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | File `HiveServer2-排障总结.md` or similar unique name |
| Status | ✅ Covered by test_docs_tools.py |
| Cleanup | None |

### E-004: Two similar candidates
| Field | Value |
|---|---|
| Purpose | Verify ambiguity returns both candidates for user to choose |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | Both `JavaScript介绍基础.md` and `JavaScript介绍进阶.md` exist |
| User input | `读取 JavaScript介绍.md` |
| Expected tool chain | read_docs |
| Expected result | Returns ambiguous result with both candidates |
| Actual result | ❌ In old Session, model substituted with historical `介绍.md`. **Defect #2 identified.** |
| Status | ❌ **Defect #2 — SEE FIX** |
| Cleanup | None |

### E-005: Ambiguity re-test after fix
| Field | Value |
|---|---|
| Purpose | Verify new Session correctly returns both candidates |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | Fix applied; fresh session |
| Status | 🔄 Needs re-test |
| Cleanup | None |

### E-006: Old session must not substitute filenames
| Field | Value |
|---|---|
| Purpose | Verify old Session doesn't replace user's filename with historical one |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | Old session previously read `介绍.md`; disk now has `JavaScript介绍基础.md`, `JavaScript介绍进阶.md` |
| User input | `读取 JavaScript介绍.md` |
| Expected tool chain | read_docs (with `JavaScript介绍.md` as filename) |
| Expected result | Must pass `JavaScript介绍.md` to read_docs, not substitute |
| Actual result | ❌ Old session substituted with historical `介绍.md`. **Defect #2** |
| Status | ❌ **Defect #2 — SEE FIX** |
| Cleanup | None |

---

## F. Memory & Dynamic State

### F-001: Old session recalls past document
| Field | Value |
|---|---|
| Purpose | Verify session memory retains document read history |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | Session previously read `readme.md` |
| User input | `我之前读了哪个文档？` |
| Expected result | Agent recalls readme.md from memory |
| Actual result | ✅ Agent recalled correctly |
| Status | ✅ Passed |
| Cleanup | None |

### F-002: Fresh session has no cross-session history
| Field | Value |
|---|---|
| Purpose | Verify `/new` clears conversation context |
| Type | Manual — CLI |
| API required | Yes |
| Steps | `/new` → `我之前读了哪个文档？` |
| Expected result | Fresh session has no memory |
| Actual result | ✅ Correct — no history in new session |
| Status | ✅ Passed |
| Cleanup | None |

### F-003: Current document listing must re-call list_docs
| Field | Value |
|---|---|
| Purpose | Verify freshness rule — asking "current" list must re-call |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | Just called list_docs in previous turn; file deleted |
| User input | `现在本地知识库有哪些文档？` |
| Expected tool chain | list_docs (must re-call) |
| Expected result | Current disk state returned |
| Actual result | ❌ Did not re-call. **Defect #1** |
| Status | ❌ **Defect #1 — SEE FIX** |
| Cleanup | None |

### F-004: Tool results override session memory
| Field | Value |
|---|---|
| Purpose | Verify current tool results take precedence over historical memory |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | Session memory says file exists; file actually deleted |
| Steps | Call list_docs (which now shows file missing) |
| Expected result | Agent reports current state, not memory |
| Status | ✅ Covered by rule #13 |
| Cleanup | None |

---

## G. Security

### G-001: Path traversal
| Field | Value |
|---|---|
| Purpose | Verify path traversal blocked |
| Type | Automated |
| API required | No |
| Status | ✅ Covered by test_docs_tools.py |
| Cleanup | None |

### G-002: Non-Markdown
| Field | Value |
|---|---|
| Purpose | Verify non-.md files rejected |
| Type | Automated |
| API required | No |
| Status | ✅ Covered by test_docs_tools.py |

### G-003: Prompt injection in document
| Field | Value |
|---|---|
| Purpose | Verify document content with injection attempt is read as data, not executed |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | knowledge_docs has document containing injected instructions |
| User input | `请读取提示注入测试文档.md` |
| Expected result | Tool reads content; model should not follow injected instructions |
| Actual result | ⏳ Not yet executed |
| Status | ⏳ Not executed |
| Cleanup | None |

### G-004: API key not in trace
| Field | Value |
|---|---|
| Purpose | Verify sensitive key not exposed in trace/logs |
| Type | Automated |
| API required | No |
| Status | ✅ Covered by test_agent.py |

### G-005: Read only knowledge_docs
| Field | Value |
|---|---|
| Purpose | Verify tool cannot escape docs directory |
| Type | Automated |
| API required | No |
| Status | ✅ Covered by test_docs_tools.py |

---

## H. Long Documents

### H-001: 115 KB document read
| Field | Value |
|---|---|
| Purpose | Verify large document read with truncation metadata |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | Large file `smart-cultural-platform-interview-learning-guide-v2.md` (~115 KB, ~2500 lines) |
| User input | `读取 smart-cultural-platform-interview-learning-guide-v2.md` |
| Expected tool chain | read_docs |
| Expected result | Content returned with truncated=true |
| Actual result | ❌ Document was read but agent did not disclose truncation. **Defect #4 identified.** |
| Status | ❌ **Defect #4 — SEE FIX** |
| Cleanup | None |

### H-002: Truncation metadata
| Field | Value |
|---|---|
| Purpose | Verify original_chars > returned_chars when truncated |
| Type | Automated |
| API required | No |
| Status | ✅ New test added |
| Cleanup | None |

### H-003: Truncation disclosure in answer
| Field | Value |
|---|---|
| Purpose | Verify agent explicitly mentions truncation when truncated=true |
| Type | Manual — CLI |
| API required | Yes |
| Precondition | Long document exists |
| User input | `读取大型文档.md` |
| Expected result | Answer must state "only part of the document was read" |
| Status | 🔄 Needs re-test after prompt fix |

### H-004: search_docs finds content beyond truncation point
| Field | Value |
|---|---|
| Purpose | Verify search_docs scans full file, not truncated content |
| Type | Automated |
| API required | No |
| Status | ✅ New test added |

### H-005: Document end identifier after truncation
| Field | Value |
|---|---|
| Purpose | Verify "银色狮子8642" not present in truncated read_docs result, but searchable by search_docs |
| Type | Automated |
| API required | No |
| Status | ✅ New test added |

---

## I. Context

### I-001: /memory command
| Field | Value |
|---|---|
| Purpose | Verify session memory display |
| Type | Manual — CLI |
| API required | No |
| Steps | `/memory` |
| Expected result | Shows message count, summary length, todo count |
| Actual result | ✅ Displayed correctly |
| Status | ✅ Passed |

### I-002: Deterministic compression demo
| Field | Value |
|---|---|
| Purpose | Verify context compression without API |
| Type | Automated script |
| API required | No |
| Steps | `python scripts/demo_context_compression.py` |
| Expected result | Runs without error |
| Actual result | ✅ Runs successfully |
| Status | ✅ Passed |

### I-003: Summary injection
| Field | Value |
|---|---|
| Purpose | Verify summary is injected into LLM messages |
| Type | Automated |
| API required | No |
| Status | ✅ Covered by test_context_manager.py |

### I-004: Recent turns preserved
| Field | Value |
|---|---|
| Purpose | Verify recent full turns kept after compression |
| Type | Automated |
| API required | No |
| Status | ✅ Covered by test_context_manager.py |

### I-005: Tool call + result not split
| Field | Value |
|---|---|
| Purpose | Verify tool_call + tool_result pairs stay together |
| Type | Automated |
| API required | No |
| Status | ✅ Covered by test_context_manager.py |

### I-006: Semantic recall after compression
| Field | Value |
|---|---|
| Purpose | Verify real LLM can still answer based on compressed summary |
| Type | Manual — CLI |
| API required | Yes |
| Status | ❓ Under discussion — deferred to next phase |

---

## Summary

| Group | Total | ✅ Passed | ❌ Failed (defect) | 🔄 Needs re-test | ⏳ Not executed | ❓ Discussion |
|---|---|---|---|---|---|---|
| A. Basic Loop | 5 | 4 | 0 | 0 | 0 | 0 |
| B. Session/Persistence | 6 | 5 | 0 | 0 | 0 | 0 |
| C. Dynamic Scan | 5 | 3 | 1 | 1 | 0 | 0 |
| D. NL Routing | 4 | 4 | 0 | 0 | 0 | 0 |
| E. Fuzzy Matching | 6 | 2 | 1 | 2 | 0 | 0 |
| F. Memory & State | 4 | 2 | 1 | 0 | 0 | 0 |
| G. Security | 5 | 4 | 0 | 0 | 1 | 0 |
| H. Long Docs | 5 | 1 | 1 | 1 | 0 | 0 |
| I. Context | 6 | 5 | 0 | 0 | 0 | 1 |
| **Total** | **46** | **30** | **4** | **4** | **1** | **1** |

Defects identified:
- **Defect #1**: Dynamic state not re-called (list_docs cached in history)
- **Defect #2**: Explicit filename replaced by historical filename
- **Defect #3**: Same no-result search repeated 3 times
- **Defect #4**: Truncation not disclosed to user

All four defects addressed by System Prompt fixes and read_docs metadata enhancement.
