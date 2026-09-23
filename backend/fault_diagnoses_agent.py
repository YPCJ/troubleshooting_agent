from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import sys
from typing import Any, Callable

import tool_boxes

PROJECT_ROOT = next((p for p in [Path(__file__).resolve().parent, *Path(__file__).resolve().parent.parents] if (p / ".env").exists()), Path(__file__).resolve().parent.parent)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from llm import chat_reply
from llm.config import default_profiles, load_profiles, project_root
from backend.tool_runtime import ToolRegistry
from llm.call_tracking import (
    format_model_call_progress,
    is_model_call_progress,
)
from backend.tools.registry import FAULT_DIAGNOSES_TOOLING_CONFIG, build_tooling


WORKDIR = project_root()


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

    def get_item(self, skill_id: str):
        return self.skills.get(skill_id)

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


TODO_HINT_KEYWORDS = (
    "排查",
    "分析",
    "生成报告",
    "报告",
    "方案",
    "步骤",
    "拆分",
    "规划",
    "梳理",
    "多步骤",
    "多个",
    "同时",
    "对比",
    "时间段",
    "原因",
)

TODO_SOFT_REMINDER_GAP_ROUNDS = 3
TODO_ENFORCE_ON_EACH_TOOL_ROUND = True
def _latest_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if str(message.get("role", "")).lower() != "user":
            continue
        return _normalize_text(message.get("content")).strip()
    return ""


def _model_history_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for message in messages:
        role = str(message.get("role", "")).strip()
        if role not in {"user", "assistant"}:
            continue
        if str(message.get("kind", "")).strip() == "log":
            continue
        content = _normalize_text(message.get("content")).strip()
        if not content:
            continue
        if role == "assistant" and is_model_call_progress(content):
            continue
        normalized = {"role": role, "content": content}
        if history and history[-1] == normalized:
            continue
        history.append(normalized)
    return history


def _should_soft_prompt_todo(messages: list[dict[str, Any]]) -> bool:
    text = _latest_user_text(messages)
    if len(text) < 24:
        return False
    compact = re.sub(r"\s+", "", text)
    keyword_hits = sum(1 for keyword in TODO_HINT_KEYWORDS if keyword in compact)
    multi_clause = any(sep in text for sep in ("，", "、", "；", "以及", "并且", "同时", "和"))
    return keyword_hits >= 2 or (keyword_hits >= 1 and multi_clause)


def _todo_soft_reminder_text() -> str:
    return (
        "<reminder>这是一个多步骤任务，请尽量在每完成一个阶段、一个关键分支或结论发生变化时及时更新 todo。"
        "不要等到所有步骤都做完才一次性勾选；如果已经连续几轮没有同步 todo，请先补一次状态再继续。"
        "如果你已经有更好的推进方式，也可以直接继续。</reminder>"
    )


def _todo_hard_reminder_text() -> str:
    return (
        "<reminder>你上一轮已经执行了工具，但没有同步 todo。"
        "下一步请先调用 todo，更新各事项的状态（至少把当前进行中的事项标为 in_progress，已完成事项标为 completed），"
        "完成后再继续其他工具调用。</reminder>"
    )


def _record_meta_for_tool(tool_name: str, arguments: dict[str, Any], skills: SkillCatalog) -> dict[str, Any]:
    if tool_name in {"read_file", "write_file", "edit_file"}:
        path = str(arguments.get("path", "")).strip()
        source_name = Path(path).name or path
        return {
            "source_kind": "file",
            "source_name": source_name,
            "source_path": path,
        }
    if tool_name == "load_skills":
        skill_name = str(arguments.get("name", "")).strip()
        skill = skills.get_item(skill_name)
        source_path = str(skill.path) if skill else ""
        return {
            "source_kind": "skill",
            "source_name": skill_name,
            "source_path": source_path,
        }
    return {}


def _trace_summary_for_tool(tool_name: str, arguments: dict[str, Any], output: Any) -> str | None:
    if tool_name == "read_file":
        path = str(arguments.get("path", "")).strip()
        label = Path(path).name or path or "unknown"
        return f"### 读取文件完成：{label}"
    if tool_name == "load_skills":
        name = str(arguments.get("name", "")).strip() or "unknown"
        return f"### 加载技能完成：{name}"
    return None


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
    record_meta_factory: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    trace_summary_factory: Callable[[str, dict[str, Any], Any], str | None] | None = None,
    required_tool_sequence: tuple[str, ...] = (),
) -> dict[str, Any]:
    model_history = _model_history_messages(messages)
    session_messages = [
        {"role": "system", "content": system_prompt},
        *model_history,
    ]
    assistant_messages: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    trace_messages: list[str] = []
    artifacts: list[dict[str, Any]] = []
    usage_total = 0
    latest_tool_output: Any = None
    artifact_paths: set[str] = set()
    next_artifact_id = 1
    last_todo_round_index = 0
    last_todo_reminder_round = 0
    todo_soft_prompt_enabled = _should_soft_prompt_todo(model_history)
    enforce_todo_next_round = False
    required_tool_index = 0
    model_call_count = 0

    def add_record(record_type: str, label: str, meta: dict[str, Any] | None = None) -> None:
        rec = {"id": f"rec_{len(records) + 1:04d}", "type": record_type, "label": label}
        if meta:
            rec.update(meta)
        records.append(rec)
        if on_record:
            on_record(rec)

    def add_trace(line: str) -> None:
        if line:
            trace_messages.append(line)
            if on_trace:
                on_trace(line)

    for _ in range(max_rounds):
        model_call_count += 1
        round_index = model_call_count
        active_tools = tools
        required_tool = (
            required_tool_sequence[required_tool_index]
            if required_tool_index < len(required_tool_sequence)
            else None
        )
        if required_tool:
            active_tools = [
                tool for tool in tools
                if str(((tool.get("function") or {}).get("name") or "")).strip()
                == required_tool
            ]
            if not active_tools:
                unavailable_text = (
                    f"无法继续排查：必需工具 `{required_tool}` 未注册或已禁用。"
                )
                assistant_message = {
                    "role": "assistant",
                    "content": unavailable_text,
                    "model": runtime_profile,
                    "tokens": _estimate_tokens(unavailable_text),
                }
                assistant_messages.append(assistant_message)
                usage_total += assistant_message["tokens"]
                add_trace(f"### 必需工具不可用：{required_tool}")
                if on_assistant_message:
                    on_assistant_message(assistant_message)
                break
        elif enforce_todo_next_round:
            todo_only_tools = [
                tool for tool in tools
                if str(((tool.get("function") or {}).get("name") or "")).strip() == "todo"
            ]
            if todo_only_tools:
                active_tools = todo_only_tools
        try:
            response = chat_reply(session_messages, tools=active_tools, profile_name=runtime_profile)
        except Exception as exc:
            add_trace(f"## {format_model_call_progress(round_index)}")
            add_trace(f"### 基座模型调用失败：{exc}")
            if not records:
                raise RuntimeError(f"基座模型调用失败（第 {round_index} 次调用）：{exc}") from exc
            # Tool evidence already exists; surface it instead of discarding the
            # whole round because of a transient model outage.
            interrupted_text = (
                f"基座模型在第 {round_index} 次调用失败：{exc}\n\n"
                f"本轮已完成 {len(records)} 次工具调用，结果已保留在会话记录中。"
                "请重试或切换模型继续，未完成的判断不要当作结论。"
            )
            assistant_message = {
                "role": "assistant",
                "content": interrupted_text,
                "model": runtime_profile,
                "tokens": _estimate_tokens(interrupted_text),
            }
            assistant_messages.append(assistant_message)
            usage_total += assistant_message["tokens"]
            if on_assistant_message:
                on_assistant_message(assistant_message)
            break

        content = _normalize_text(response.get("content")).strip()
        tool_calls = list(response.get("tool_calls") or [])
        tokens = int((response.get("usage") or {}).get("total_tokens") or _estimate_tokens(content))
        add_trace(f"## {format_model_call_progress(round_index)}")
        add_trace(f"### 模型返回 content length={len(content)}, tool_calls count={len(tool_calls)}")
        assistant_message = {"role": "assistant", "content": content, "model": runtime_profile, "tokens": tokens}
        if tool_calls:
            assistant_message["tool_calls"] = tool_calls
        assistant_messages.append(assistant_message)
        session_messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls or None})
        usage_total += tokens
        if on_assistant_message and content:
            on_assistant_message(assistant_message)

        if not tool_calls and required_tool:
            reminder = (
                f"<reminder>当前阶段必须先调用 {required_tool}，"
                "请使用该工具完成本阶段，不要直接给出结论。</reminder>"
            )
            add_trace(f"### 提示：{reminder}")
            session_messages.append({"role": "user", "content": reminder})
            continue
        if not tool_calls:
            break

        has_todo_call = any(str((call.get("function") or {}).get("name") or "") == "todo" for call in tool_calls)
        has_non_todo_tool_call = any(str((call.get("function") or {}).get("name") or "") != "todo" for call in tool_calls)
        if has_todo_call:
            last_todo_round_index = round_index
            enforce_todo_next_round = False

        successful_tool_names: set[str] = set()
        for call in tool_calls:
            function = call.get("function") or {}
            tool_name = str(function.get("name") or "")
            try:
                arguments = json.loads(function.get("arguments") or "{}")
                if not isinstance(arguments, dict):
                    raise ValueError("Tool arguments must be a JSON object")
                argument_error = None
            except (json.JSONDecodeError, ValueError) as exc:
                arguments = {}
                argument_error = str(exc)
            record_meta = record_meta_factory(tool_name, arguments) if record_meta_factory else {}
            add_record("tool" if tool_name != "load_skills" else "skill", f"{tool_name}({json.dumps(arguments, ensure_ascii=False)})", record_meta)
            add_trace(f"### [tool call] {tool_name}() requested")
            add_trace(f"### 本次工具调用：{tool_name}")
            add_trace(f"### 本次工具调用的参数：{_short_text(arguments)}")
            before_files = _snapshot_artifact_candidates()
            if argument_error:
                output: Any = {
                    "status": "error",
                    "error": f"Invalid tool arguments: {argument_error}",
                }
            else:
                try:
                    output = dispatch_tool(tool_name, arguments)
                except Exception as exc:
                    output = {
                        "status": "error",
                        "error": str(exc).strip() or exc.__class__.__name__,
                    }
            after_files = _snapshot_artifact_candidates()
            discovered, next_artifact_id = _collect_new_artifacts(before_files, after_files, artifact_paths, next_artifact_id)
            artifacts.extend(discovered)
            latest_tool_output = output
            add_trace(f"### 本次工具调用的结果为：")
            summary_line = trace_summary_factory(tool_name, arguments, output) if trace_summary_factory else None
            add_trace(summary_line or _short_text(output, limit=2500))
            tool_failed = isinstance(output, dict) and (
                bool(output.get("error")) or output.get("status") == "error"
            )
            if tool_failed:
                if tool_name == "todo":
                    enforce_todo_next_round = True
            else:
                successful_tool_names.add(tool_name)
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

        if required_tool and required_tool in successful_tool_names:
            required_tool_index += 1

        should_soft_prompt_todo = (
            todo_soft_prompt_enabled
            and not has_todo_call
            and round_index - max(last_todo_round_index, last_todo_reminder_round) >= TODO_SOFT_REMINDER_GAP_ROUNDS
        )
        if should_soft_prompt_todo:
            add_trace(f"### 提示：{_todo_soft_reminder_text()}")
            session_messages.append({"role": "user", "content": _todo_soft_reminder_text()})
            last_todo_reminder_round = round_index

        should_hard_enforce_todo = (
            TODO_ENFORCE_ON_EACH_TOOL_ROUND
            and todo_soft_prompt_enabled
            and has_non_todo_tool_call
            and not has_todo_call
        )
        if should_hard_enforce_todo:
            add_trace(f"### 提示：{_todo_hard_reminder_text()}")
            session_messages.append({"role": "user", "content": _todo_hard_reminder_text()})
            enforce_todo_next_round = True

    if not any((msg.get("content") or "").strip() for msg in assistant_messages):
        try:
            model_call_count += 1
            add_trace(f"## {format_model_call_progress(model_call_count)}")
            final_response = chat_reply([*session_messages, {"role": "user", "content": final_prompt}], profile_name=runtime_profile)
            final_text = _normalize_text(final_response.get("content")).strip()
            final_tokens = int((final_response.get("usage") or {}).get("total_tokens") or _estimate_tokens(final_text))
        except Exception as exc:
            raise RuntimeError(f"基座模型调用失败（生成最终答复）：{exc}") from exc

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
        "model_calls": model_call_count,
        "usage": {"total_tokens": usage_total},
        "model_profile": runtime_profile,
    }


class FaultDiagnosesAgentService:
    def __init__(
        self,
        skills_dir: Path | None = None,
        *,
        enabled_checker: Callable[[str], bool] | None = None,
    ):
        self.skills_dir = skills_dir or (WORKDIR / "skills")
        self.skills = SkillCatalog(self.skills_dir)
        self.todo_manager = tool_boxes.TodoManager()
        specs, handlers = build_tooling(
            skills=self.skills,
            config=FAULT_DIAGNOSES_TOOLING_CONFIG,
            todo_manager=self.todo_manager,
        )
        self.tool_registry = ToolRegistry(
            specs,
            handlers,
            enabled_checker=enabled_checker,
        )

    @property
    def system_prompt(self) -> str:
        return (
            f"你是本系统的通用智能体，工作在{WORKDIR}目录下，现在的时间是{_now_stamp()}。\n"
            "你需要根据用户意图自主选择是否加载 skill：当用户请求某个领域流程、规范或模板时，优先调用 load_skills 获取对应技能内容，再结合工具执行。\n"
            "对于复杂或多步骤任务，第一轮优先使用 todo 生成/更新待办列表；随后每一轮只要执行了实质性工具步骤，都要同步一次 todo（进行中/已完成状态），避免等到最后才一次性更新。\n"
            "你可以使用 todo/task 来拆分复杂问题和跟踪步骤。\n"
            "读取 .csv/.txt/.md 等文件内容时，不要使用 bash 执行 head/cat/awk 等直接读取原始字节，优先使用 read_file 工具。\n"
            f"可用的skill技能包括：\n{self.skills.descriptions()}\n"
        )

    def list_skills(self) -> list[dict[str, Any]]:
        return self.skills.list_items()

    def update_skill_markdown(self, skill_id: str, markdown: str) -> None:
        self.skills.update_markdown(skill_id, markdown)

    def list_tools(self) -> list[dict[str, Any]]:
        return self.tool_registry.list_items()

    def list_tool_names(self) -> list[str]:
        return [item["tool_name"] for item in self.list_tools()]

    def set_tool_enabled_checker(self, checker: Callable[[str], bool] | None) -> None:
        self.tool_registry.set_enabled_checker(checker)

    def run_turn(self, messages: list[dict[str, Any]], model_profile: str | None = None, max_rounds: int = 30,
                 on_trace: Callable[[str], None] | None = None,
                 on_record: Callable[[dict[str, Any]], None] | None = None,
                 on_assistant_message: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        runtime_profile = _resolve_model_profile(model_profile)
        return _run_turn_with_tools(
            system_prompt=self.system_prompt,
            messages=messages,
            tools=self.tool_registry.openai_tools(),
            dispatch_tool=self.tool_registry.dispatch,
            runtime_profile=runtime_profile,
            max_rounds=max_rounds,
            final_prompt="请不要再调用任何工具，基于已有上下文直接给出最终答复。需要包含：结论、关键数据摘要、图表或文件位置（如果有）。",
            on_trace=on_trace,
            on_record=on_record,
            on_assistant_message=on_assistant_message,
            record_meta_factory=lambda tool_name, arguments: _record_meta_for_tool(tool_name, arguments, self.skills),
            trace_summary_factory=_trace_summary_for_tool,
        )


def _discover_app_cards() -> list[dict[str, str]]:
    candidates = [
        ("fault_diagnoses", "🛰️", "故障诊断智能体（默认）"),
        ("sbc_network_troubleshooting", "🕸️", "天基承载网故障排查智能体"),
        ("fault_search", "🔎", "故障检索与定位"),
        ("document_write", "📝", "报告生成"),
        ("log_transform", "🧹", "日志格式转换"),
    ]
    if os.getenv("AGENT_APP_MODE") == "sbc":
        candidates = [item for item in candidates if item[0] == "sbc_network_troubleshooting"]
    result = []
    for app_id, icon, desc in candidates:
        result.append({"app_id": app_id, "icon": icon, "description": desc})
    return result


class ServiceCatalog:
    def __init__(self, enabled_checker: Callable[[str], bool] | None = None):
        from backend.agents.sbc_network_troubleshooting import (
            SBCNetworkTroubleshootingAgentService,
        )
        from backend.log_transform_agent import LogTransformAgentService

        self.agent = FaultDiagnosesAgentService(enabled_checker=enabled_checker)
        self.sbc_network_troubleshooting_agent = SBCNetworkTroubleshootingAgentService(
            enabled_checker=enabled_checker,
        )
        self.log_transform_agent = LogTransformAgentService(enabled_checker=enabled_checker)
        self.apps = _discover_app_cards()

    def close(self) -> None:
        """Release resources held by the sub-agents (e.g. checkpoint connections)."""
        for agent in (
            self.agent,
            self.sbc_network_troubleshooting_agent,
            self.log_transform_agent,
        ):
            closer = getattr(agent, "close", None)
            if callable(closer):
                closer()

    def list_apps(self) -> list[dict[str, str]]:
        return self.apps

    def list_items(self) -> list[dict[str, Any]]:
        return self.agent.list_skills()

    def update_markdown(self, skill_id: str, markdown: str) -> None:
        self.agent.update_skill_markdown(skill_id, markdown)

    def list_tools(self) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for app_id, tools in (
            ("fault_diagnoses", self.agent.list_tools()),
            (
                "sbc_network_troubleshooting",
                self.sbc_network_troubleshooting_agent.list_tools(),
            ),
            ("log_transform", self.log_transform_agent.list_tools()),
        ):
            for item in tools:
                name = str(item["tool_name"])
                current = merged.get(name)
                if not current:
                    merged[name] = {
                        "tool_name": name,
                        "description": str(item.get("description", "")),
                        "category": str(item.get("category", "other")),
                        "enabled": bool(item.get("enabled", True)),
                        "available": item.get("available", True),
                        "apps": [app_id],
                    }
                    continue
                current["enabled"] = bool(item.get("enabled", True))
                current["available"] = bool(current.get("available", True)) or bool(
                    item.get("available", True)
                )
                apps = list(current.get("apps", []))
                if app_id not in apps:
                    apps.append(app_id)
                current["apps"] = apps
        return [merged[name] for name in sorted(merged.keys())]

    def list_tool_names(self) -> list[str]:
        return [item["tool_name"] for item in self.list_tools()]

    def set_tool_enabled_checker(self, checker: Callable[[str], bool] | None) -> None:
        self.agent.set_tool_enabled_checker(checker)
        self.sbc_network_troubleshooting_agent.set_tool_enabled_checker(checker)
        self.log_transform_agent.set_tool_enabled_checker(checker)
