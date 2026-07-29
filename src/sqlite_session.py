"""
SQLite-backed Session Store with in-memory cache for object identity.

Within a single process, get_or_create returns the same Python Session object
for the same (user_id, session_id) pair.  save() persists to SQLite and also
updates the cache.  Multiple CLI processes can access the same database;
concurrent writes use last-writer-wins (no distributed locking).
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.session import Session


class SessionPersistenceError(Exception):
    ...


_DEFAULT_DB_PATH = "data/agent_sessions.db"


def _get_db_path() -> str:
    return os.environ.get("AGENT_SESSION_DB_PATH", _DEFAULT_DB_PATH)


def _ensure_dir(path: str) -> None:
    parent = Path(path).parent
    parent.mkdir(parents=True, exist_ok=True)


def _serialize(session: Session) -> str:
    return json.dumps(
        {
            "messages": session.messages,
            "summary": session.summary,
            "todos": session.todos,
            "traces": session.traces,
        },
        ensure_ascii=False,
        default=str,
    )


def _deserialize(state_json: str) -> dict[str, Any]:
    try:
        data = json.loads(state_json)
    except json.JSONDecodeError as e:
        raise SessionPersistenceError(
            f"Failed to parse session state JSON: {e}"
        ) from e
    if not isinstance(data, dict):
        raise SessionPersistenceError(
            f"Session state is not a JSON object, got {type(data).__name__}"
        )
    for key in ("messages", "summary", "todos", "traces"):
        if key not in data:
            raise SessionPersistenceError(
                f"Missing required field '{key}' in session state"
            )
    return data


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_from_row(
    user_id: str, session_id: str, state_json: str
) -> Session:
    data = _deserialize(state_json)
    return Session(
        user_id=user_id,
        session_id=session_id,
        messages=data["messages"],
        summary=data["summary"],
        todos=data["todos"],
        traces=data["traces"],
    )


class SQLiteSessionStore:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _get_db_path()
        _ensure_dir(self._db_path)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()
        # In-memory cache: same (user_id, session_id) always returns same
        # Session object within this process, matching MemorySessionStore.
        self._cache: dict[tuple[str, str], Session] = {}

    def _init_db(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                user_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                state_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, session_id)
            )
        """)
        self._conn.commit()

    def get_or_create(self, user_id: str, session_id: str) -> Session:
        key = (user_id, session_id)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        row = self._conn.execute(
            "SELECT state_json FROM sessions WHERE user_id = ? AND session_id = ?",
            (user_id, session_id),
        ).fetchone()
        if row is not None:
            session = _session_from_row(
                user_id, session_id, row["state_json"]
            )
            self._cache[key] = session
            return session

        session = Session(user_id=user_id, session_id=session_id)
        self._cache[key] = session
        self.save(session)
        return session

    def get(self, user_id: str, session_id: str) -> Session | None:
        key = (user_id, session_id)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        row = self._conn.execute(
            "SELECT state_json FROM sessions WHERE user_id = ? AND session_id = ?",
            (user_id, session_id),
        ).fetchone()
        if row is None:
            return None

        session = _session_from_row(user_id, session_id, row["state_json"])
        self._cache[key] = session
        return session

    def list_user_sessions(self, user_id: str) -> list[Session]:
        rows = self._conn.execute(
            "SELECT session_id, state_json FROM sessions WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
        result: list[Session] = []
        for row in rows:
            session = _session_from_row(
                user_id, row["session_id"], row["state_json"]
            )
            # Populate cache for any loaded sessions
            key = (user_id, row["session_id"])
            self._cache[key] = session
            result.append(session)
        return result

    def save(self, session: Session) -> None:
        now = _now()
        state_json = _serialize(session)
        self._conn.execute(
            """
            INSERT INTO sessions (user_id, session_id, state_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, session_id) DO UPDATE SET
                state_json = excluded.state_json,
                updated_at = excluded.updated_at
            """,
            (session.user_id, session.session_id, state_json, now, now),
        )
        self._conn.commit()
        key = (session.user_id, session.session_id)
        self._cache[key] = session

    def clear(self) -> None:
        self._conn.execute("DELETE FROM sessions")
        self._conn.commit()
        self._cache.clear()

    def close(self) -> None:
        self._conn.close()
