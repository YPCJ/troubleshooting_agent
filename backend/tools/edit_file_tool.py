from __future__ import annotations

from backend.tool_runtime import ToolSpec
from backend.tools._common import safe_path


def spec(description: str) -> ToolSpec:
    return ToolSpec(
        name="edit_file",
        description=description,
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}},
        },
        category="file",
    )


def run(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        content = fp.read_text(encoding="utf-8")
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
        return f"Edited {path}"
    except Exception as exc:
        return f"Error: {exc}"

