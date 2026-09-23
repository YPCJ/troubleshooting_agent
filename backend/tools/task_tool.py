from __future__ import annotations

from backend.tool_runtime import ToolSpec


def spec(description: str) -> ToolSpec:
    return ToolSpec(
        name="task",
        description=description,
        parameters={
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["prompt"],
        },
        category="other",
    )


def run(prompt: str, description: str = "") -> str:
    return (
        "Task tool invoked. "
        "Subtask execution is not supported in this runtime environment. "
        "Received prompt: "
        f"{prompt}. "
        f"Description: {description}"
    )

