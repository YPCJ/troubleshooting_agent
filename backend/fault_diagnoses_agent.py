from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import sys
from typing import Any, Callable, Mapping

import requests
try:
    import chardet
except Exception:  # pragma: no cover
    chardet = None
try:
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None

PROJECT_ROOT = next((p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents] if (p / ".env").exists()), Path(__file__).resolve().parent.parent)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from llm import chat_reply
from llm.config import default_profiles, load_profiles, project_root


WORKDIR = project_root()
DATA_URL = os.getenv("DATA_URL", "http://49.233.215.205:5000/api/external-query")


def _sanitize_filename(text: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_-]+", "_", text or "")
    return sanitized.strip("_")[:140] or "data"


def _now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _estimate_tokens(text: str) -> int:
    return max(1, len(text.strip()) // 4) if text else 0


def _short_text(value: Any, limit: int = 1200) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return f"{text[:limit]} ... (truncated, total={len(text)} chars)"


def _normalize_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    chunks.append(text)
            elif isinstance(item, str):
                chunks.append(item)
        return "\n".join(part for part in chunks if part).strip()
    return str(content)


def _safe_path(path: str) -> Path:
    resolved = (WORKDIR / path).resolve()
    if not resolved.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {path}")
    return resolved


def _infer_artifact_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}:
        return "image"
    if suffix in {".md", ".txt", ".doc", ".docx", ".pdf", ".html"}:
        return "document"
    return "data"


def _artifact_scan_roots() -> list[Path]:
    roots: list[Path] = []
    for rel in ("skills", "assets", "outputs"):
        p = WORKDIR / rel
        if p.exists():
            roots.append(p)
    roots.append(WORKDIR)
    return roots


def _snapshot_artifact_candidates() -> dict[str, tuple[int, int]]:
    candidates: dict[str, tuple[int, int]] = {}
    allowed = {
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg",
        ".md", ".txt", ".doc", ".docx", ".pdf", ".html",
        ".json", ".csv", ".xlsx", ".xls",
    }
    for root in _artifact_scan_roots():
        if root == WORKDIR:
            iterator = (p for p in WORKDIR.iterdir() if p.is_file())
        else:
            iterator = root.rglob("*")
        for file_path in iterator:
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in allowed:
                continue
            try:
                stat = file_path.stat()
            except OSError:
                continue
            candidates[str(file_path.resolve())] = (int(stat.st_mtime_ns), int(stat.st_size))
    return candidates


def _collect_new_artifacts(
    before: dict[str, tuple[int, int]],
    after: dict[str, tuple[int, int]],
    existing_paths: set[str],
    next_id: int,
) -> tuple[list[dict[str, Any]], int]:
    new_items: list[dict[str, Any]] = []
    for path, meta in after.items():
        old_meta = before.get(path)
        if old_meta == meta:
            continue
        if path in existing_paths:
            continue
        existing_paths.add(path)
        new_items.append(
            {
                "id": f"art_{next_id:04d}",
                "name": Path(path).name,
                "path": path,
                "artifact_type": _infer_artifact_type(path),
                "session_id": "",
            }
        )
        next_id += 1
    return new_items, next_id


def _parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return ""
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part) for part in inner.split(",")]
    if (value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"')):
        return value[1:-1]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return value


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not match:
        return {}, text.strip()
    meta: dict[str, Any] = {}
    current_list_key: str | None = None
    for raw_line in match.group(1).splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.startswith("  - ") and current_list_key:
            meta.setdefault(current_list_key, []).append(_parse_scalar(raw_line[4:]))
            continue
        if ":" in raw_line:
            key, value = raw_line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value:
                meta[key] = _parse_scalar(value)
                current_list_key = None
            else:
                meta[key] = []
                current_list_key = key
    return meta, match.group(2).strip()


def _dump_frontmatter(meta: dict[str, Any]) -> str:
    lines = []
    for key, value in meta.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


@dataclass
class SkillItem:
    id: str
    markdown: str
    path: Path
    meta: dict[str, Any] = field(default_factory=dict)


class SkillCatalog:
    def __init__(self, root: Path):
        self.root = root
        self.skills: dict[str, SkillItem] = {}
        self.reload()

    def reload(self) -> None:
        self.skills.clear()
        if not self.root.exists():
            return
        for file in sorted(self.root.rglob("SKILL.md")):
            text = file.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(text)
            name = str(meta.get("name") or file.parent.name)
            self.skills[name] = SkillItem(id=name, markdown=body, path=file, meta=meta)

    def list_items(self) -> list[dict[str, Any]]:
        return [{"skill_id": skill.id, "markdown": skill.markdown} for skill in self.skills.values()]

    def descriptions(self) -> str:
        if not self.skills:
            return "(no skills available)"
        lines = []
        for name, skill in self.skills.items():
            desc = skill.meta.get("description", "No description")
            lines.append(f"  - {name}: {desc}")
        return "\n".join(lines)

    def get_markdown(self, skill_id: str) -> str:
        skill = self.skills.get(skill_id)
        if not skill:
            raise KeyError(skill_id)
        return skill.markdown

    def update_markdown(self, skill_id: str, markdown: str) -> None:
        skill = self.skills.get(skill_id)
        if not skill:
            raise KeyError(skill_id)
        frontmatter = _dump_frontmatter(skill.meta).strip()
        skill.path.write_text(f"---\n{frontmatter}\n---\n{markdown.strip()}\n", encoding="utf-8")
        self.reload()


def _resolve_model_profile(model_profile: str | None) -> str:
    profiles = load_profiles()
    default_profile = profiles["default_profile"]
    return model_profile or os.getenv("MODEL_PROFILE") or default_profile


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
        r = subprocess.run(args, shell=False, cwd=str(WORKDIR), capture_output=True, text=True, timeout=120, encoding="utf-8", errors="ignore")
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except Exception as exc:
        return f"Error: {exc}"


def _run_bash_with_file_preview(command: str) -> str:
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


def _run_read(path: str, limit: int | None = None) -> str:
    try:
        text = _safe_path(path).read_text(encoding="utf-8")
        lines = text.splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)[:50000]
    except Exception as exc:
        return f"Error: {exc}"


def _detect_file_encoding(path: str) -> str:
    if chardet is None:
        return "utf-8"
    try:
        raw = _safe_path(path).read_bytes()[:50000]
        detected = chardet.detect(raw).get("encoding")
        return str(detected or "utf-8")
    except Exception:
        return "utf-8"


def _run_read_text_smart(path: str, limit: int | None = None) -> str:
    enc_guess = _detect_file_encoding(path)
    for enc in [enc_guess, "utf-8", "gbk", "gb2312", "gb18030"]:
        try:
            text = _safe_path(path).read_text(encoding=enc)
            lines = text.splitlines()
            if limit and limit < len(lines):
                lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
            return "\n".join(lines)[:50000]
        except UnicodeDecodeError:
            continue
        except Exception as exc:
            return f"Error: {exc}"
    return "Error: failed to decode file with supported encodings"


def _run_read_csv(path: str, limit: int | None = None) -> str:
    if pd is None:
        return "Error in read csv files:pandas is not installed"
    nrows = limit or 5
    enc_guess = _detect_file_encoding(path)
    for enc in [enc_guess, "utf-8", "gbk", "gb2312", "gb18030"]:
        try:
            df = pd.read_csv(_safe_path(path), encoding=enc, nrows=nrows)
            try:
                table = df.to_markdown(index=False)
            except Exception:
                table = df.to_string(index=False)
            return f"读取的csv文件内容为:\n{table}"
        except UnicodeDecodeError:
            continue
        except Exception as exc:
            return f"Error in read csv files:{exc}"
    return "Error in read csv files: failed to decode CSV with supported encodings"


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
        return _run_read_csv(file_arg, line_limit)
    if suffix in {".txt", ".md", ".log", ".json", ".yaml", ".yml"}:
        return _run_read_text_smart(file_arg, line_limit)
    return None


def _run_write(path: str, content: str) -> dict[str, Any] | str:
    try:
        fp = _safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        return {
            "message": f"Wrote {len(content)} bytes to {path}",
            "saved_to": str(fp),
            "artifact_type": _infer_artifact_type(str(fp)),
            "bytes": len(content),
        }
    except Exception as exc:
        return f"Error: {exc}"


def _run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = _safe_path(path)
        content = fp.read_text(encoding="utf-8")
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
        return f"Edited {path}"
    except Exception as exc:
        return f"Error: {exc}"


def _run_data_query(sat_id: str, para_name: list[str], start_time: str, end_time: str) -> dict[str, Any]:
    request_body = {
        "sat_id": sat_id,
        "para_name": para_name,
        "start_time": start_time,
        "end_time": end_time,
    }
    try:
        response = requests.post(DATA_URL, json=request_body, timeout=60)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, list):
            return {"error": "Unexpected response format", "body": result}
        total_points = 0
        preview = []
        for item in result:
            if not isinstance(item, dict):
                continue
            values = item.get("value", [])
            total_points += len(values)
            for point in values[:10]:
                preview.append({"time": point.get("time"), "point_value": point.get("point_value")})
        target_dir = WORKDIR / "skills" / "figure-plot" / "assets"
        target_dir.mkdir(parents=True, exist_ok=True)
        param_slug = _sanitize_filename("_".join(para_name))
        time_slug = _sanitize_filename(f"{start_time}_{end_time}")
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"data_query_{sat_id}_{param_slug}_{time_slug}_{timestamp}.json"
        file_path = target_dir / filename
        file_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "saved_to": str(file_path),
            "sat_id": sat_id,
            "para_name": para_name,
            "start_time": start_time,
            "end_time": end_time,
            "data_points": total_points,
            "preview": preview,
        }
    except Exception as exc:
        return {"error": str(exc)}


def _run_data_query_raw(sat_id: str, para_name: list[str], start_time: str, end_time: str) -> Any:
    request_body = {
        "sat_id": sat_id,
        "para_name": para_name,
        "start_time": start_time,
        "end_time": end_time,
    }
    try:
        response = requests.post(DATA_URL, json=request_body, timeout=60)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        return {"error": str(exc)}


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "运行一个shell command。",
            "parameters": {"type": "object", "properties": {"command": {"type": "string"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取一个文本文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "将指定内容写入文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "修改文件中的指定内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "data_query",
            "description": "查询指定卫星遥测参数在某个时间段内的值。",
            "parameters": {
                "type": "object",
                "properties": {
                    "sat_id": {"type": "string"},
                    "para_name": {"type": "array", "items": {"type": "string"}},
                    "start_time": {"type": "string"},
                    "end_time": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_skills",
            "description": "根据skill名称加载技能内容。",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
            },
        },
    },
]

def _run_turn_with_tools(
    *,
    system_prompt: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    dispatch_tool: callable,
    runtime_profile: str,
    max_rounds: int,
    final_prompt: str,
    on_trace: Callable[[str], None] | None = None,
    on_record: Callable[[dict[str, Any]], None] | None = None,
    on_assistant_message: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    session_messages = [{"role": "system", "content": system_prompt}, *messages]
    assistant_messages: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    trace_messages: list[str] = []
    artifacts: list[dict[str, Any]] = []
    usage_total = 0
    latest_tool_output: Any = None
    artifact_paths: set[str] = set()
    next_artifact_id = 1

    def add_record(record_type: str, label: str) -> None:
        rec = {"id": f"rec_{len(records) + 1:04d}", "type": record_type, "label": label}
        records.append(rec)
        if on_record:
            on_record(rec)

    def add_trace(line: str) -> None:
        if line:
            trace_messages.append(line)
            if on_trace:
                on_trace(line)

    for _ in range(max_rounds):
        round_index = len(assistant_messages) + 1
        add_trace(f"## 这是本次任务中大模型的第{round_index}次调用")
        try:
            response = chat_reply(session_messages, tools=tools, profile_name=runtime_profile)
        except Exception as exc:
            latest_user = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
            fallback = f"###（本地模拟）已接收：{str(latest_user)[:120]}。当前模型不可用：{exc}"
            assistant_messages.append({"role": "assistant", "content": fallback, "model": runtime_profile, "tokens": _estimate_tokens(fallback)})
            session_messages.append({"role": "assistant", "content": fallback})
            usage_total += _estimate_tokens(fallback)
            add_trace(f"[stream fallback] sync request failed: {exc}")
            break

        content = _normalize_text(response.get("content")).strip()
        tool_calls = list(response.get("tool_calls") or [])
        tokens = int((response.get("usage") or {}).get("total_tokens") or _estimate_tokens(content))
        add_trace(f"### 模型返回 content length={len(content)}, tool_calls count={len(tool_calls)}")
        assistant_message = {"role": "assistant", "content": content, "model": runtime_profile, "tokens": tokens}
        if tool_calls:
            assistant_message["tool_calls"] = tool_calls
        assistant_messages.append(assistant_message)
        session_messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls or None})
        usage_total += tokens
        if on_assistant_message and content:
            on_assistant_message(assistant_message)

        if not tool_calls:
            break

        for call in tool_calls:
            function = call.get("function") or {}
            tool_name = str(function.get("name") or "")
            before_files = _snapshot_artifact_candidates()
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            output = dispatch_tool(tool_name, arguments)
            after_files = _snapshot_artifact_candidates()
            discovered, next_artifact_id = _collect_new_artifacts(before_files, after_files, artifact_paths, next_artifact_id)
            artifacts.extend(discovered)
            latest_tool_output = output
            add_record("tool" if tool_name != "load_skills" else "skill", f"{tool_name}({json.dumps(arguments, ensure_ascii=False)})")
            add_trace(f"### [tool call] {tool_name}() requested")
            add_trace(f"### 本次工具调用：{tool_name}")
            add_trace(f"### 本次工具调用的参数：{_short_text(arguments)}")
            add_trace(f"### 本次工具调用的结果为：")
            add_trace(_short_text(output, limit=2500))
            if tool_name == "load_skills":
                add_trace(f"### 本次运行中，加载了技能文件，内容为{_short_text(output, limit=3000)}")
            if isinstance(output, dict) and output.get("saved_to"):
                path = str(output["saved_to"])
                if path not in artifact_paths:
                    artifact_paths.add(path)
                    artifacts.append({
                        "id": f"art_{next_artifact_id:04d}",
                        "name": Path(path).name,
                        "path": path,
                        "artifact_type": str(output.get("artifact_type") or _infer_artifact_type(path)),
                        "session_id": "",
                    })
                    next_artifact_id += 1
            session_messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": json.dumps(output, ensure_ascii=False, default=str)})

    if not any((msg.get("content") or "").strip() for msg in assistant_messages):
        try:
            final_response = chat_reply([*session_messages, {"role": "user", "content": final_prompt}], profile_name=runtime_profile)
            final_text = _normalize_text(final_response.get("content")).strip()
            final_tokens = int((final_response.get("usage") or {}).get("total_tokens") or _estimate_tokens(final_text))
        except Exception:
            final_text = ""
            final_tokens = 0

        if not final_text:
            if isinstance(latest_tool_output, dict) and latest_tool_output.get("saved_to"):
                final_text = (
                    "### 已完成工具调用。"
                    f" 文件已保存到：{latest_tool_output.get('saved_to')}"
                )
            elif isinstance(latest_tool_output, str) and latest_tool_output.strip():
                final_text = f"### 工具调用已完成，返回摘要：{latest_tool_output.strip()[:300]}"
            else:
                final_text = "### 工具调用已完成，但当前模型未返回可展示文本。请重试，或切换模型后再次提问。"
            final_tokens = _estimate_tokens(final_text)

        assistant_messages.append({"role": "assistant", "content": final_text, "model": runtime_profile, "tokens": final_tokens})
        usage_total += final_tokens
        if on_assistant_message and final_text:
            on_assistant_message({"role": "assistant", "content": final_text, "model": runtime_profile, "tokens": final_tokens})
        add_trace("[stream note] Gemini did not return direct assistant text in this round; generated fallback final reply.")

    reply_text = assistant_messages[-1]["content"] if assistant_messages else ""
    return {
        "assistant_messages": assistant_messages,
        "records": records,
        "trace_messages": trace_messages,
        "artifacts": artifacts,
        "reply_text": reply_text,
        "usage": {"total_tokens": usage_total},
        "model_profile": runtime_profile,
    }


class FaultDiagnosesAgentService:
    def __init__(self, skills_dir: Path | None = None):
        self.skills_dir = skills_dir or (WORKDIR / "skills")
        self.skills = SkillCatalog(self.skills_dir)

    @property
    def system_prompt(self) -> str:
        return (
            f"你是一个故障排查专家.工作在{WORKDIR}目录下，现在的时间是{_now_stamp()}。\n"
            f"可用的skill技能包括：\n{self.skills.descriptions()}\n"
        )

    def list_skills(self) -> list[dict[str, Any]]:
        return self.skills.list_items()

    def update_skill_markdown(self, skill_id: str, markdown: str) -> None:
        self.skills.update_markdown(skill_id, markdown)

    def _dispatch_tool(self, tool_name: str, arguments: Mapping[str, Any]) -> Any:
        if tool_name == "bash":
            return _run_bash(str(arguments.get("command", "")))
        if tool_name == "read_file":
            return _run_read(str(arguments.get("path", "")), arguments.get("limit"))
        if tool_name == "write_file":
            return _run_write(str(arguments.get("path", "")), str(arguments.get("content", "")))
        if tool_name == "edit_file":
            return _run_edit(str(arguments.get("path", "")), str(arguments.get("old_text", "")), str(arguments.get("new_text", "")))
        if tool_name == "data_query":
            return _run_data_query(
                str(arguments.get("sat_id", "")),
                list(arguments.get("para_name") or []),
                str(arguments.get("start_time", "")),
                str(arguments.get("end_time", "")),
            )
        if tool_name == "load_skills":
            skill_name = str(arguments.get("name", ""))
            return self.skills.get_markdown(skill_name)
        return {"error": f"Unknown tool: {tool_name}"}

    def run_turn(self, messages: list[dict[str, Any]], model_profile: str | None = None, max_rounds: int = 30,
                 on_trace: Callable[[str], None] | None = None,
                 on_record: Callable[[dict[str, Any]], None] | None = None,
                 on_assistant_message: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        runtime_profile = _resolve_model_profile(model_profile)
        return _run_turn_with_tools(
            system_prompt=self.system_prompt,
            messages=messages,
            tools=TOOLS,
            dispatch_tool=self._dispatch_tool,
            runtime_profile=runtime_profile,
            max_rounds=max_rounds,
            final_prompt="请不要再调用任何工具，基于已有上下文直接给出最终答复。需要包含：结论、关键数据摘要、图表或文件位置（如果有）。",
            on_trace=on_trace,
            on_record=on_record,
            on_assistant_message=on_assistant_message,
        )


def _discover_app_cards() -> list[dict[str, str]]:
    candidates = [
        ("fault_diagnoses", "🛰️", "故障分析与诊断"),
        ("fault_search", "🔎", "故障检索与定位"),
        ("document_write", "📝", "报告生成"),
        ("log_transform", "🧹", "日志格式转换"),
    ]
    result = []
    for app_id, icon, desc in candidates:
        result.append({"app_id": app_id, "icon": icon, "description": desc})
    return result


class ServiceCatalog:
    def __init__(self):
        from backend.log_transform_agent import LogTransformAgentService

        self.agent = FaultDiagnosesAgentService()
        self.log_transform_agent = LogTransformAgentService()
        self.apps = _discover_app_cards()

    def list_apps(self) -> list[dict[str, str]]:
        return self.apps

    def list_items(self) -> list[dict[str, Any]]:
        return self.agent.list_skills()

    def update_markdown(self, skill_id: str, markdown: str) -> None:
        self.agent.update_skill_markdown(skill_id, markdown)
