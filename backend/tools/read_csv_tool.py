from __future__ import annotations

from backend.tool_runtime import ToolSpec
from backend.tools._common import read_csv


def spec(description: str) -> ToolSpec:
    return ToolSpec(
        name="read_csv",
        description=description,
        parameters={"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}},
        category="file",
    )


def run(path: str, limit: int | None = None) -> str:
    return read_csv(path, limit)

