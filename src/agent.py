from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any

from src.context import ToolContext
from src.context_manager import ContextManager
from src.llm import LLMClient, LLMResponse
from src.prompt import SYSTEM_PROMPT
from src.registry import (
    ToolNotFoundError,
    ToolParameterError,
    ToolExecutionError,
    ToolRegistry,
)
from src.session import SessionStore
from src.trace import TraceStep


class InvalidLLMResponseError(Exception):
    def __init__(self, message: str, traces: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.traces = traces or []


class MaxStepsExceededError(Exception):
    def __init__(self, message: str, traces: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.traces = traces or []


@dataclass
class AgentResult:
    answer: str
    session_id: str
    steps_used: int
    traces: list[dict[str, Any]]


class AgentRuntime:
    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        session_store: SessionStore,
        system_prompt: str = SYSTEM_PROMPT,
        max_steps: int = 10,
        context_manager: ContextManager | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._tool_registry = tool_registry
        self._session_store = session_store
        self._system_prompt = system_prompt
        self._max_steps = max_steps
        self._context_manager = context_manager or ContextManager()
        self._run_counter = 0

    def _save_session(self, session: Any) -> None:
        self._session_store.save(session)

    def run(
        self,
        user_id: str,
        session_id: str,
        user_input: str,
    ) -> AgentResult:
        if not user_id:
            raise ValueError("user_id must not be empty")
        if not session_id:
            raise ValueError("session_id must not be empty")
        if not user_input:
            raise ValueError("user_input must not be empty")

        self._run_counter += 1
        run_id = self._run_counter
        trace_start = len(self._session_store.get_or_create(user_id, session_id).traces)
        session = self._session_store.get_or_create(user_id, session_id)
        ctx = ToolContext(
            user_id=user_id, session_id=session_id, store=self._session_store
        )

        self._context_manager.prepare_session(session)
        self._save_session(session)
        session.messages.append({"role": "user", "content": user_input})
        self._save_session(session)

        try:
            for step in range(1, self._max_steps + 1):
                msgs = self._context_manager.build_messages(
                    system_prompt=self._system_prompt, session=session
                )
                tools_schema = self._tool_registry.export_openai_schema()

                response: LLMResponse = self._llm_client.complete(
                    messages=msgs, tools=tools_schema
                )

                if response.tool_calls:
                    self._handle_tool_calls(
                        session=session,
                        ctx=ctx,
                        response=response,
                        step=step,
                        run_id=run_id,
                    )

                elif response.content:
                    session.messages.append(
                        {"role": "assistant", "content": response.content}
                    )
                    self._save_session(session)
                    trace = TraceStep(
                        step_number=step,
                        event_type="final_answer",
                        run_id=run_id,
                        decision_summary=response.decision_summary,
                        observation=response.content,
                        success=True,
                    )
                    session.traces.append(asdict(trace))
                    self._save_session(session)
                    return AgentResult(
                        answer=response.content,
                        session_id=session_id,
                        steps_used=step,
                        traces=list(session.traces[trace_start:]),
                    )

                else:
                    self._save_session(session)
                    trace = TraceStep(
                        step_number=step,
                        event_type="llm_error",
                        run_id=run_id,
                        decision_summary=response.decision_summary,
                        observation="LLM returned empty content with no tool calls",
                        success=False,
                        error_type="InvalidLLMResponseError",
                    )
                    session.traces.append(asdict(trace))
                    self._save_session(session)
                    raise InvalidLLMResponseError(
                        "LLM returned empty content with no tool calls",
                        traces=list(session.traces[trace_start:]),
                    )

            self._save_session(session)
            trace = TraceStep(
                step_number=self._max_steps,
                event_type="max_steps_exceeded",
                run_id=run_id,
                observation=f"Exceeded maximum steps ({self._max_steps})",
                success=False,
                error_type="MaxStepsExceededError",
            )
            session.traces.append(asdict(trace))
            self._save_session(session)
            raise MaxStepsExceededError(
                f"Exceeded maximum steps ({self._max_steps})",
                traces=list(session.traces[trace_start:]),
            )
        except MaxStepsExceededError:
            self._save_session(session)
            raise
        except InvalidLLMResponseError:
            self._save_session(session)
            raise

    def _handle_tool_calls(
        self,
        session: Any,
        ctx: ToolContext,
        response: LLMResponse,
        step: int,
        run_id: int = 0,
    ) -> None:
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": response.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in response.tool_calls
            ],
        }
        session.messages.append(assistant_msg)
        self._save_session(session)

        for tc in response.tool_calls:
            start = time.monotonic()
            error_type: str | None = None
            try:
                result = self._tool_registry.execute(ctx, tc.name, tc.arguments)
                success = True
                observation = json.dumps(
                    {"ok": True, "result": result}, ensure_ascii=False
                )
            except (
                ToolNotFoundError,
                ToolParameterError,
                ToolExecutionError,
            ) as e:
                success = False
                error_type = type(e).__name__
                observation = json.dumps(
                    {
                        "ok": False,
                        "error_type": error_type,
                        "message": str(e),
                    },
                    ensure_ascii=False,
                )

            duration_ms = (time.monotonic() - start) * 1000

            trace = TraceStep(
                step_number=step,
                event_type="tool_call",
                run_id=run_id,
                decision_summary=response.decision_summary,
                tool_call_id=tc.id,
                tool_name=tc.name,
                arguments=tc.arguments,
                observation=observation,
                success=success,
                error_type=error_type,
                duration_ms=duration_ms,
            )
            session.traces.append(asdict(trace))

            session.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": observation,
                }
            )
            self._save_session(session)
