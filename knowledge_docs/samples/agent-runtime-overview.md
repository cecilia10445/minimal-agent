# Agent Runtime Overview

An Agent Runtime is the core execution engine of an LLM-powered agent system. It orchestrates the interaction between the language model, tools, and session state.

## Key Components

1. **LLM Client** — Communicates with the language model API
2. **Tool Registry** — Maintains available tools and their schemas
3. **Session Store** — Persists conversation history and state
4. **Context Manager** — Compresses old messages to fit context windows

## Execution Flow

1. Receive user input
2. Prepare session (compress old context if needed)
3. Append user message to session
4. Build message array: system prompt + summary + recent messages
5. Call LLM with message array and tool schemas
6. If LLM returns tool calls, execute them and append results
7. Repeat from step 5 until LLM returns a final answer
8. Return answer to user

## Design Principles

- **Structural safety**: Code ensures tool calls and results stay together
- **Deterministic by default**: Context compression does not depend on external APIs
- **Failure isolation**: Semantic summary failures fall back to deterministic
- **No hidden state**: All session data is explicitly stored and retrievable
