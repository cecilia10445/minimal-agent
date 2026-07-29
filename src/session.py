from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Session:
    user_id: str
    session_id: str
    messages: list[dict[str, str]] = field(default_factory=list)
    summary: str = ""
    todos: list[dict[str, Any]] = field(default_factory=list)
    traces: list[dict[str, Any]] = field(default_factory=list)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str], Session] = {}

    def get_or_create(self, user_id: str, session_id: str) -> Session:
        key = (user_id, session_id)
        if key not in self._sessions:
            self._sessions[key] = Session(user_id=user_id, session_id=session_id)
        return self._sessions[key]

    def get(self, user_id: str, session_id: str) -> Session | None:
        return self._sessions.get((user_id, session_id))

    def list_user_sessions(self, user_id: str) -> list[Session]:
        return [s for (uid, sid), s in self._sessions.items() if uid == user_id]

    def save(self, session: Session) -> None:
        self._sessions[(session.user_id, session.session_id)] = session

    def clear(self) -> None:
        self._sessions.clear()
