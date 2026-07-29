from typing import Any

from src.context import ToolContext
from src.tool import Tool


class TodoAddTool(Tool):
    name = "todo_add"
    description = "Add a todo item to the current session."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "待办内容",
                }
            },
            "required": ["content"],
        }

    def execute(self, context: ToolContext, content: str) -> str:
        session = context.store.get_or_create(context.user_id, context.session_id)
        todo_id = len(session.todos) + 1
        session.todos.append({"id": todo_id, "content": content, "done": False})
        return f"Todo #{todo_id} added: {content}"


class TodoListTool(Tool):
    name = "todo_list"
    description = "List all todo items in the current session."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
        }

    def execute(self, context: ToolContext, **kwargs: Any) -> str:
        session = context.store.get_or_create(context.user_id, context.session_id)
        if not session.todos:
            return "No todos."
        lines = []
        for t in session.todos:
            status = "[x]" if t["done"] else "[ ]"
            lines.append(f"#{t['id']} {status} {t['content']}")
        return "\n".join(lines)


class TodoCompleteTool(Tool):
    name = "todo_complete"
    description = "Mark a todo item as completed by its ID."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "id": {
                    "type": "integer",
                    "description": "待办 ID",
                }
            },
            "required": ["id"],
        }

    def execute(self, context: ToolContext, id: int) -> str:
        session = context.store.get_or_create(context.user_id, context.session_id)
        for t in session.todos:
            if t["id"] == id:
                t["done"] = True
                return f"Todo #{id} marked as completed."
        return f"Todo #{id} not found."
