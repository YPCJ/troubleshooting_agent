from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from backend.tool_runtime import ToolSpec
from backend.tools._common import WORKDIR, read_csv, read_text_smart


def spec(description: str) -> ToolSpec:
    return ToolSpec(
        name="bash",
        description=description,
        parameters={"type": "object", "properties": {"command": {"type": "string"}}},
        category="shell",
    )


def run(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    shell_operators = ["|", "&&", "||", ";", ">", "<", "`", "$"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    if any(op in command for op in shell_operators):
        return "Error: Shell operators are not allowed in bash tool"

    preview = _maybe_preview_file_via_bash(command)
    if preview is not None:
        return preview
    return _run_bash(command)


def _run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    shell_operators = ["|", "&&", "||", ";", ">", "<", "`", "$"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    if any(op in command for op in shell_operators):
        return "Error: Shell operators are not allowed in bash tool"
    try:
        args = shlex.split(command)
        if not args:
            return "Error: Empty command"
        result = subprocess.run(
            args,
            shell=False,
            cwd=str(WORKDIR),
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="ignore",
        )
        out = (result.stdout + result.stderr).strip()
        return out[:50000] if out else "(no output)"
    except Exception as exc:
        return f"Error: {exc}"


def _maybe_preview_file_via_bash(command: str) -> str | None:
    try:
        args = shlex.split(command)
    except ValueError:
        return None
    if not args:
        return None
    file_arg: str | None = None
    line_limit: int | None = None
    if args[0] == "head":
        if len(args) >= 4 and args[1] == "-n":
            try:
                line_limit = int(args[2])
            except Exception:
                line_limit = None
            file_arg = args[3]
        elif len(args) >= 2:
            file_arg = args[-1]
    elif args[0] == "cat" and len(args) == 2:
        file_arg = args[1]
    if not file_arg:
        return None
    suffix = Path(file_arg).suffix.lower()
    if suffix == ".csv":
        return read_csv(file_arg, line_limit)
    if suffix in {".txt", ".md", ".log", ".json", ".yaml", ".yml"}:
        return read_text_smart(file_arg, line_limit)
    return None

