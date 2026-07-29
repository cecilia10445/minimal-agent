# Recording Script — 5-8 Minute Walkthrough

## Prerequisites

- `.env` configured with valid `DASHSCOPE_API_KEY`
- Virtual environment activated
- Working directory is project root

## Cleanup Old Data

Run before each recording to ensure a fresh start:

```powershell
Remove-Item -Force data\demo-recording.db -ErrorAction SilentlyContinue
Remove-Item -Force data\demo-recording-2.db -ErrorAction SilentlyContinue
```

## Scenes

### Scene 1: Project Structure and AgentRuntime (30s)

Show `tree` or `ls` to display project structure. Open `src/agent.py` and point to `AgentRuntime` class, `run()` method, and `_handle_tool_calls()`.

### Scene 2: Direct Answer (30s)

```powershell
python -m src.cli --user-id demo --session-id recording
```

Type:

```
> Hello
```

Expected: Agent responds with greeting.

### Scene 3: Calculator Tool (30s)

```
> What is 89 squared?
```

Expected: Agent invokes calculator tool, returns 7921.

### Scene 4: Multi-Tool Chain — Search + Read (1 min)

```
> Search for HiveServer2 port troubleshooting in the knowledge base
```

Expected: Agent calls `search_docs`, finds HiveServer2 documents.

```
> Read it and summarize the root cause
```

Expected: Agent calls `read_docs`, reads the document, summarizes HiveServer2 port 10000 issue.

### Scene 5: Todo Add/List/Complete (1 min)

```
> Add todo: write documentation
```

Expected: Agent calls `todo_add`.

```
> Add todo: record demo
```

Expected: Agent calls `todo_add`.

```
> List my todos
```

Expected: Agent calls `todo_list`, shows both items.

```
> Complete the first todo
```

Expected: Agent calls `todo_complete`.

```
> List todos again
```

Expected: Agent shows one completed, one pending.

### Scene 6: Session Persistence (1 min)

Exit the CLI (`Ctrl+C` or `/exit`).

```powershell
python -m src.cli --user-id demo --session-id recording
```

```
> List my todos
```

Expected: Todos from previous session still present.

### Scene 7: Cross-Session Isolation (30s)

Exit CLI.

```powershell
python -m src.cli --user-id demo --session-id another-session
```

```
> List my todos
```

Expected: Empty list — different session does not share todos.

### Scene 8: System Commands (30s)

```
> /trace
```

Expected: Shows trace of current session's steps.

```
> /memory
```

Expected: Shows session summary (if compression has occurred).

### Scene 9: Test Results (30s)

Exit CLI. In terminal:

```powershell
pytest --tb=short -q
```

Expected: Shows 270 passed, 2 skipped.

## Total Time

Approximately 5-6 minutes. Speak clearly and pause briefly between tool calls.

## Alternative: Scripted Replay

Use the existing recording demo script for a fully automated run:

```powershell
python -m src.cli --user-id demo --session-id recording --script scenarios/recording-demo.txt --step-delay 2.0
```

Adjust `--step-delay` to control playback speed.
