from __future__ import annotations

import argparse
import time
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from src.agent import (
    AgentResult,
    AgentRuntime,
    InvalidLLMResponseError,
    MaxStepsExceededError,
)
from src.bootstrap import build_default_registry
from src.config import LLMConfigurationError, load_context_policy, load_llm_settings
from src.context_manager import ContextManager, estimate_tokens
from src.prompt import SYSTEM_PROMPT
from src.qwen_client import (
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMServiceError,
    LLMTimeoutError,
    OpenAICompatibleLLMClient,
)
from src.sqlite_session import SQLiteSessionStore


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Work Assistant Agent CLI")
    parser.add_argument("--user-id", default="local-user", help="Logical user ID")
    parser.add_argument("--session-id", default="default", help="Session ID")
    parser.add_argument(
        "--db-path",
        default=None,
        help="SQLite database path (overrides AGENT_SESSION_DB_PATH env var)",
    )
    parser.add_argument(
        "--script",
        default=None,
        help="Path to script file with one user input per line (for recording demos)",
    )
    parser.add_argument(
        "--step-delay",
        type=float,
        default=0.0,
        help="Delay in seconds between script steps (for recording pace)",
    )
    return parser.parse_args()


def _print_traces(result: AgentResult) -> None:
    for t in result.traces:
        etype = t["event_type"]
        if etype == "tool_call":
            name = t.get("tool_name", "?")
            ok = "success" if t.get("success") else "FAILED"
            dur = f"{t.get('duration_ms', 0):.0f}ms" if t.get("duration_ms") is not None else "?ms"
            print(f"  Step {t['step_number']} | {name} | {ok} | {dur}")
        elif etype == "final_answer":
            print(f"  Step {t['step_number']} | final_answer")
        elif etype == "llm_error":
            print(f"  Step {t['step_number']} | LLM_ERROR | {t.get('observation', '')}")
        elif etype == "max_steps_exceeded":
            print(f"  Step {t['step_number']} | MAX_STEPS_EXCEEDED")


def _print_history(session) -> None:
    for i, msg in enumerate(session.messages):
        role = msg["role"]
        if role == "system":
            continue
        content = msg.get("content", "")
        if content is None:
            content = ""
        if role == "user":
            print(f"  [{i}] user: {content[:120]}")
        elif role == "assistant":
            if "tool_calls" in msg:
                names = [tc["function"]["name"] for tc in msg["tool_calls"]]
                print(f"  [{i}] assistant \u2192 tools: {', '.join(names)}")
            else:
                print(f"  [{i}] assistant: {content[:120]}")
        elif role == "tool":
            print(f"  [{i}] tool ({msg.get('name', '?')}): {content[:80]}")


def _print_memory(session) -> None:
    has_summary = bool(session.summary)
    print(f"Session Memory:")
    print(f"  Summary exists: {'yes' if has_summary else 'no'}")
    print(f"  Summary length: {len(session.summary)} chars")
    print(f"  Raw messages in session: {len(session.messages)}")
    est = estimate_tokens(session.messages)
    print(f"  Estimated token count: {est}")
    if has_summary:
        print(f"  Summary content:")
        for line in session.summary.split("\n"):
            print(f"    {line}")


def main() -> None:
    load_dotenv()
    args = _parse_args()

    user_id = args.user_id
    current_session_id = args.session_id

    try:
        settings = load_llm_settings()
    except LLMConfigurationError as e:
        print(f"Configuration error: {e}")
        print("Please create a .env file based on .env.example.")
        return

    try:
        llm_client = OpenAICompatibleLLMClient(settings=settings)
    except Exception as e:
        print(f"Failed to create LLM client: {e}")
        return

    store = SQLiteSessionStore(db_path=args.db_path)

    if args.db_path:
        db_display = args.db_path
    else:
        db_display = store._db_path

    registry = build_default_registry()

    store.get_or_create(user_id, current_session_id)

    context_policy = load_context_policy()
    runtime = AgentRuntime(
        llm_client=llm_client,
        tool_registry=registry,
        session_store=store,
        system_prompt=SYSTEM_PROMPT,
        max_steps=settings.max_retries + 6,
        context_manager=ContextManager(context_policy),
    )

    print(f"Work Assistant Agent")
    print(f"  user_id:    {user_id}")
    print(f"  session_id: {current_session_id}")
    print(f"  db_path:    {db_display}")
    print("Type /help for commands.")

    script_lines: list[str] | None = None
    script_index = 0
    if args.script:
        script_path = Path(args.script)
        if not script_path.exists():
            print(f"Script file not found: {args.script}")
            return
        script_lines = script_path.read_text(encoding="utf-8").splitlines()
        script_lines = [ln.strip() for ln in script_lines if ln.strip() and not ln.strip().startswith("#")]
        print(f"Script mode: {len(script_lines)} commands loaded from {args.script}")
        if args.step_delay > 0:
            print(f"Step delay: {args.step_delay}s")

    while True:
        try:
            if script_lines is not None:
                if script_index >= len(script_lines):
                    print("\nScript finished.")
                    break
                raw = script_lines[script_index]
                script_index += 1
                print(f"\n[{user_id} @ {current_session_id}] > {raw}")
                if args.step_delay > 0:
                    time.sleep(args.step_delay)
            else:
                raw = input(f"\n[{user_id} @ {current_session_id}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not raw:
            continue

        # Handle slash commands
        if raw.startswith("/"):
            parts = raw.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""

            if cmd == "/quit":
                print("Goodbye!")
                break

            elif cmd == "/help":
                print("Commands:")
                print("  /new              Create and switch to a new session (persisted)")
                print("  /sessions         List all sessions for current user")
                print("  /switch <id>      Switch to a session (current user)")
                print("  /trace            Show traces for current session")
                print("  /history          Show message history")
                print("  /memory           Show session memory / summary status")
                print("  /whoami           Show current user, session, db path")
                print("  /help             Show this help")
                print("  /quit             Exit")
                print("Anything else is sent to the agent as your input.")

            elif cmd == "/new":
                new_id = str(uuid.uuid4())[:8]
                store.get_or_create(user_id, new_id)
                current_session_id = new_id
                print(f"Switched to new session: {current_session_id}")

            elif cmd == "/sessions":
                sessions = store.list_user_sessions(user_id)
                if not sessions:
                    print("No sessions.")
                else:
                    for s in sessions:
                        marker = " <-- current" if s.session_id == current_session_id else ""
                        print(f"  {s.session_id}{marker}")

            elif cmd == "/switch":
                if not arg:
                    print("Usage: /switch <session_id>")
                    continue
                session = store.get(user_id, arg)
                if session is None:
                    print(f"Session '{arg}' not found.")
                    continue
                current_session_id = arg
                print(f"Switched to session: {current_session_id}")

            elif cmd == "/trace":
                session = store.get(user_id, current_session_id)
                if session is None or not session.traces:
                    print("No traces yet.")
                else:
                    runs: dict[int, list[dict]] = {}
                    for t in session.traces:
                        rid = t.get("run_id", 0)
                        runs.setdefault(rid, []).append(t)
                    for rid in sorted(runs):
                        print(f"--- Run #{rid} ---")
                        for t in runs[rid]:
                            etype = t["event_type"]
                            if etype == "tool_call":
                                name = t.get("tool_name", "?")
                                ok = "success" if t.get("success") else "FAILED"
                                dur = f"{t.get('duration_ms', 0):.0f}ms" if t.get("duration_ms") is not None else "?ms"
                                print(f"  Step {t['step_number']} | {name} | {ok} | {dur}")
                            elif etype == "final_answer":
                                print(f"  Step {t['step_number']} | final_answer")
                            elif etype == "llm_error":
                                print(f"  Step {t['step_number']} | LLM_ERROR")
                            elif etype == "max_steps_exceeded":
                                print(f"  Step {t['step_number']} | MAX_STEPS_EXCEEDED")

            elif cmd == "/history":
                session = store.get(user_id, current_session_id)
                if session is None or not session.messages:
                    print("No messages yet.")
                else:
                    _print_history(session)

            elif cmd == "/memory":
                session = store.get(user_id, current_session_id)
                if session is None:
                    print("No session.")
                else:
                    _print_memory(session)

            elif cmd == "/whoami":
                print(f"  user_id:    {user_id}")
                print(f"  session_id: {current_session_id}")
                print(f"  db_path:    {db_display}")

            else:
                print(f"Unknown command: {cmd}. Type /help for available commands.")

            continue

        # Process user input via agent
        try:
            result = runtime.run(
                user_id=user_id,
                session_id=current_session_id,
                user_input=raw,
            )
            print(f"\nAnswer: {result.answer}")
            print(f"(Steps: {result.steps_used})")
            _print_traces(result)

        except MaxStepsExceededError as e:
            print(f"\nMax steps exceeded: {e}")
            if e.traces:
                _print_traces(
                    AgentResult(
                        answer="",
                        session_id=current_session_id,
                        steps_used=0,
                        traces=e.traces,
                    )
                )

        except InvalidLLMResponseError as e:
            print(f"\nInvalid LLM response: {e}")

        except LLMAuthenticationError as e:
            print(f"\nAuthentication error: {e}")
            print("Check your DASHSCOPE_API_KEY.")

        except LLMRateLimitError as e:
            print(f"\nRate limit exceeded: {e}")
            print("Please wait and try again.")

        except LLMTimeoutError as e:
            print(f"\nRequest timed out: {e}")
            print("Check your network or increase AGENT_REQUEST_TIMEOUT.")

        except LLMServiceError as e:
            print(f"\nLLM service error: {e}")

        except LLMConfigurationError as e:
            print(f"\nConfiguration error: {e}")

        except Exception as e:
            print(f"\nUnexpected error: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
