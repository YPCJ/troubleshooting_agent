from __future__ import annotations

from typing import Any, Callable, Mapping

from backend.fault_diagnoses_agent import (
    SkillCatalog,
    WORKDIR,
    _now_stamp,
    _resolve_model_profile,
    _run_turn_with_tools,
    _run_bash_with_file_preview,
    _run_read_text_smart,
    _run_read_csv,
    _run_write,
    _run_edit,
    _run_data_query_raw,
)


LOG_TRANSFORM_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "运行一个shell command。读取 csv/txt/md 文件内容时优先使用 read_csv 或 read_file。",
            "parameters": {"type": "object", "properties": {"command": {"type": "string"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取一个文本文件。",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_csv",
            "description": "读取一个后缀为.csv的文件。",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "将指定内容写入文件。",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "修改文件中的指定内容。",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}},
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
            "parameters": {"type": "object", "properties": {"name": {"type": "string"}}},
        },
    },
]


class LogTransformAgentService:
    def __init__(self, skills_dir=None):
        self.skills_dir = skills_dir or (WORKDIR / "skills")
        self.skills = SkillCatalog(self.skills_dir)

    @property
    def system_prompt(self) -> str:
        return (
            f"你是一个故障排查专家.工作在{WORKDIR}目录下，现在的时间是{_now_stamp()}。\n"
            "你工作在跨平台环境中（macOS/Linux/Windows），请根据当前系统选择合适命令，并优先使用当前环境可用的 Python 解释器。\n"
            "读取 .csv/.txt/.md 等文件内容时，不要使用 bash 执行 head/cat/awk 等直接读取原始字节，优先使用 read_csv 或 read_file 工具。\n"
            "在处理你不熟悉的任务时使用你的skill技能来解决问题。你在调用函数工具时，会严格按照要求撰写。\n"
            f"可以采用的skill技能包括：\n{self.skills.descriptions()}\n"
        )

    def _dispatch_tool(self, tool_name: str, arguments: Mapping[str, Any]) -> Any:
        if tool_name == "bash":
            return _run_bash_with_file_preview(str(arguments.get("command", "")))
        if tool_name == "read_file":
            return _run_read_text_smart(str(arguments.get("path", "")), arguments.get("limit"))
        if tool_name == "read_csv":
            return _run_read_csv(str(arguments.get("path", "")), arguments.get("limit"))
        if tool_name == "write_file":
            return _run_write(str(arguments.get("path", "")), str(arguments.get("content", "")))
        if tool_name == "edit_file":
            return _run_edit(str(arguments.get("path", "")), str(arguments.get("old_text", "")), str(arguments.get("new_text", "")))
        if tool_name == "data_query":
            return _run_data_query_raw(
                str(arguments.get("sat_id", "")),
                list(arguments.get("para_name") or []),
                str(arguments.get("start_time", "")),
                str(arguments.get("end_time", "")),
            )
        if tool_name == "load_skills":
            skill_name = str(arguments.get("name", ""))
            return f"<skill name=\"{skill_name}\">\n{self.skills.get_markdown(skill_name)}\n</skill>"
        return {"error": f"Unknown tool: {tool_name}"}

    def run_turn(self, messages: list[dict[str, Any]], model_profile: str | None = None, max_rounds: int = 30,
                 on_trace: Callable[[str], None] | None = None,
                 on_record: Callable[[dict[str, Any]], None] | None = None,
                 on_assistant_message: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        runtime_profile = _resolve_model_profile(model_profile)
        return _run_turn_with_tools(
            system_prompt=self.system_prompt,
            messages=messages,
            tools=LOG_TRANSFORM_TOOLS,
            dispatch_tool=self._dispatch_tool,
            runtime_profile=runtime_profile,
            max_rounds=max_rounds,
            final_prompt="请不要再调用任何工具，基于已有上下文直接给出最终答复。需要包含：处理结论、关键步骤、输出文件路径（如果有）。",
            on_trace=on_trace,
            on_record=on_record,
            on_assistant_message=on_assistant_message,
        )

