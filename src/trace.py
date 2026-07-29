from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TraceStep:
    step_number: int
    event_type: str
    run_id: int = 0
    decision_summary: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None
    observation: str | None = None
    success: bool | None = None
    error_type: str | None = None
    duration_ms: float | None = None
