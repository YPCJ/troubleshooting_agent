from __future__ import annotations

from typing import Any, Callable

from backend.tool_runtime import ToolSpec


def spec(description: str) -> ToolSpec:
    return ToolSpec(
        name="todo",
        description=description,
        parameters={
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": (
                        "完整任务清单。任意时刻最多只能有一个任务的 status 为 "
                        "in_progress；开始下一项前应先把上一项标为 completed。"
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "text": {"type": "string"},
                            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                        },
                        "required": ["id", "text", "status"],
                    },
                }
            },
            "required": ["items"],
        },
        category="other",
    )


def build_handler(todo_manager: Any) -> Callable[[dict[str, Any]], Any]:
    return lambda args: todo_manager.update(list(args.get("items") or []))
