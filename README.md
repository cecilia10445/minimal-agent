# Minimal Agent

A minimal, self-implemented Agent Runtime with tool execution, session persistence, and context memory — powered by qwen3.6-plus.

**No LangGraph, AutoGen, or agent frameworks control the main loop.** The core runtime is implemented from scratch:

```
LLM decision → Tool Registry → tool execution → observation → continue loop or final answer
```

## Quick Demo

```powershell
# Convert README to recording-compatible script
# Or run interactively:
python -m src.cli --user-id demo --session-id quick-start

# Inside the CLI:
# > Hello
# > What is 89 squared?
# > Add todo: write documentation
# > List todos
# > /trace
```

## Features

- **Self-built Agent Runtime** — `AgentRuntime` with LLM call loop, tool dispatch, step counting, and result aggregation
- **8 tools**: Calculator, Web Search (mock), Doc management (ListDocs, SearchDocs, ReadDocs), Todo (Add, List, Complete)
- **Multi-user, multi-session persistence** via SQLite — close and reopen, todos and history restored
- **Deterministic context compression** — old messages summarized by rule, recent N turns preserved, tool calls never split
- **Hybrid semantic compression** (opt-in) — `AGENT_CONTEXT_SUMMARY_MODE=hybrid` uses qwen3.6-plus for semantic summarization, falls back to deterministic on failure
- **Trace recording** — per-step tool calls, durations, errors
- **270+ automated tests** — zero API dependency for normal test runs
- **CLI with script mode** — record and replay demos

## Architecture

### Agent Loop

```
User Input
  → prepare_session()        # compress old context if needed
  → append user message
  → build_messages()          # system prompt + summary + recent messages
  → LLM.complete()
  → if tool_calls:
      → execute tools
      → append tool results
      → loop back to LLM
  → else:
      → return final answer
```

### Tool System

Each tool implements `BaseTool` with JSON Schema input specification. The ToolRegistry exports OpenAI-compatible function schemas so the LLM autonomously selects tools. No hardcoded tool routing.

### Session & Persistence

```
Session(user_id, session_id, messages, summary, todos, traces)
  → SQLiteSessionStore(upsert + cache)
  → Multi-process safe within single process
  → Cross-user isolation: (user_id, session_id) composite key
```

### Context & Memory

```
Auto-recall (always included):
  System Prompt
  + Session Summary (compressed history)
  + Recent N raw conversation turns

On-demand recall (tool call required):
  Todo list → todo_list tool
  Documents → list_docs / search_docs / read_docs

Never included:
  Full hidden chain-of-thought
  All traces
  API keys
  SQLite metadata
  Full dynamic todo copies
```

The system parses the model's public `content`, `tool_calls`, and final answer. It records a short `decision_summary` for tracing but does **not** request or persist the model's hidden reasoning chain.

### Error Handling

| Error | Handling |
|---|---|
| Tool not found / parameter error / execution error | Caught, result reported back to LLM |
| LLM auth / ratelimit / timeout | Mapped to typed exceptions |
| Max steps exceeded | `MaxStepsExceededError` with trace |
| Invalid LLM response | `InvalidLLMResponseError` |
| Semantic summary failure | Falls back to deterministic compression |

## Test Results

```
270 passed, 2 skipped (real LLM tests need DASHSCOPE_API_KEY)
```

Run locally:

```powershell
pytest
python -m compileall src tests scripts
```

## Quick Start

1. Clone the repo and set up a virtual environment:

```powershell
git clone https://github.com/cecilia10445/minimal-agent.git
cd minimal-agent
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Copy `.env.example` to `.env` and add your DashScope API key:

```powershell
copy .env.example .env
# Edit .env: DASHSCOPE_API_KEY=your-key-here
```

3. Run the CLI:

```powershell
python -m src.cli --user-id demo --session-id hello
```

## CLI Commands

| Command | Purpose |
|---|---|
| `python -m src.cli --help` | Show CLI options |
| `python -m src.cli --user-id u --session-id s` | Interactive session |
| `python -m src.cli --user-id u --session-id s --script file.txt --step-delay 1.0` | Scripted replay |
| `python -m src.cli /trace` | Show trace for current session |
| `python -m src.cli /memory` | Show session summary |

## Recording Demo

See `docs/recording-script.md` for a 5-8 minute walkthrough script covering:

1. Project structure overview
2. Direct answer
3. Calculator tool
4. Search + read multi-tool chain
5. Todo add/list/complete
6. Session persistence (close and reopen)
7. Cross-session isolation
8. Trace display
9. Context memory display
10. Test results

## Project Structure

```
minimal-agent/
├── src/
│   ├── agent.py              AgentRuntime, AgentResult
│   ├── bootstrap.py          Tool registration
│   ├── cli.py                Interactive CLI
│   ├── config.py             LLM settings, context policy
│   ├── context_manager.py    ContextPolicy, compression, summarization
│   ├── context_summarizer.py Semantic summarizer (hybrid mode)
│   ├── llm.py                LLMClient protocol, ScriptedLLMClient
│   ├── prompt.py             System prompt
│   ├── qwen_client.py        OpenAI-compatible LLM client
│   ├── recording_llm_client.py Call metadata recorder
│   ├── registry.py           ToolRegistry
│   ├── session.py            Session dataclass, SessionStore
│   ├── sqlite_session.py     SQLite-backed persistence
│   └── tools/                8 tool implementations
├── scripts/                  Context baseline, comparison, demo scripts
├── scenarios/                Testing scenarios
├── docs/                     Audit, design, recording, development log
├── tests/                    270+ automated tests
├── knowledge_docs/           Sample documents for doc tool demo
└── .env.example              Environment template
```

## AI-Assisted Development

This project was developed with AI assistance (see `docs/ai-development-log.md` for full prompt history, issues encountered, and resolutions). The core Agent Runtime, Tool Registry, Context Management, and persistence layer are implemented in this repository's own code — no external agent framework controls the main loop.

## Design Boundaries

- **Search tool**: Mock implementation — returns predefined results, not live web search
- **Document retrieval**: Keyword matching, not vector RAG
- **User isolation**: Logical composite key, not authentication
- **SQLite concurrency**: Last-write-wins within same session
- **Deterministic by default**: Hybrid semantic mode requires explicit opt-in via environment
- **Token estimation**: Characters/4 approximation, not tokenizer
- **No multi-agent, MCP, or Web UI**

## Context Baseline Reports

- [Context test plan](docs/context-baseline-test-plan.md)
- [Hybrid context design](docs/hybrid-context-design.md)
- [Comparison report](reports/context-comparison.md) (requires fresh real LLM runs — see docs for known issues)
