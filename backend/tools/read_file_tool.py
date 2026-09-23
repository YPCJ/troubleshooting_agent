from __future__ import annotations

from backend.tool_runtime import ToolSpec
from backend.tools._common import read_file_auto


def spec(description: str) -> ToolSpec:
    return ToolSpec(
        name="read_file",
        description=description,
        parameters={"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}},
        category="file",
    )


def run(path: str, limit: int | None = None) -> str:
    try:
        return read_file_auto(path, limit)
    except Exception as exc:
        return f"Error: {exc}"

