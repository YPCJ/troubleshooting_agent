from __future__ import annotations

from typing import Any, Callable

from backend.tool_runtime import ToolSpec


def spec(description: str) -> ToolSpec:
    return ToolSpec(
        name="load_skills",
        description=description,
        parameters={"type": "object", "properties": {"name": {"type": "string"}}},
        category="skills",
    )


def build_handler(skills: Any, *, wrap_in_skill_tag: bool) -> Callable[[dict[str, Any]], str]:
    def _handler(args: dict[str, Any]) -> str:
        name = str(args.get("name", ""))
        markdown = skills.get_markdown(name)
        if not wrap_in_skill_tag:
            return markdown
        return f"<skill name=\"{name}\">\n{markdown}\n</skill>"

    return _handler

