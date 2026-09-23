from __future__ import annotations

from typing import Any

from backend.tool_runtime import ToolSpec
from backend.tools._common import infer_artifact_type, safe_path


def spec(description: str) -> ToolSpec:
    return ToolSpec(
        name="write_file",
        description=description,
        parameters={"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}},
        category="file",
    )


def run(path: str, content: str) -> dict[str, Any] | str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        return {
            "message": f"Wrote {len(content)} bytes to {path}",
            "saved_to": str(fp),
            "artifact_type": infer_artifact_type(str(fp)),
            "bytes": len(content),
        }
    except Exception as exc:
        return f"Error: {exc}"

