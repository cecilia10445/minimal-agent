from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.session import SessionStore


@dataclass
class ToolContext:
    user_id: str
    session_id: str
    store: "SessionStore" = field(repr=False)
