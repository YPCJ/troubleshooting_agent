from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from backend.tool_runtime import ToolHandler, ToolSpec
from backend.tools import (
    bash_tool,
    data_query_tool,
    edit_file_tool,
    load_skills_tool,
    read_csv_tool,
    read_file_tool,
    task_tool,
    todo_tool,
    web_search_tool,
    write_file_tool,
)


@dataclass(frozen=True)
class ToolingConfig:
    tool_order: tuple[str, ...]
    descriptions: dict[str, str]
    wrap_skill_tag: bool
    use_raw_data_query: bool


FAULT_DIAGNOSES_TOOLING_CONFIG = ToolingConfig(
    tool_order=("bash", "read_file", "write_file", "edit_file", "data_query", "load_skills", "todo", "task"),
    descriptions={
        "bash": "运行一个shell command。读取 csv/txt/md 文件内容时优先使用 read_file。",
        "read_file": "读取一个文件；遇到 .csv 时会自动按表格方式解析。",
        "write_file": "将指定内容写入文件。",
        "edit_file": "修改文件中的指定内容。",
        "data_query": "查询指定卫星遥测参数在某个时间段内的值。",
        "load_skills": "根据skill名称加载技能内容。",
        "todo": "更新任务列表；对于复杂/多步骤任务，第一轮先规划，后续每一轮有实质工具执行都应同步更新状态。",
        "task": "启动一个子任务描述，用于拆分复杂问题并整理下一步动作。",
    },
    wrap_skill_tag=False,
    use_raw_data_query=False,
)


LOG_TRANSFORM_TOOLING_CONFIG = ToolingConfig(
    tool_order=("bash", "read_file", "read_csv", "write_file", "edit_file", "data_query", "load_skills"),
    descriptions={
        "bash": "运行一个shell command。读取 csv/txt/md 文件内容时优先使用 read_csv 或 read_file。",
        "read_file": "读取一个文本文件。",
        "read_csv": "读取一个后缀为.csv的文件。",
        "write_file": "将指定内容写入文件。",
        "edit_file": "修改文件中的指定内容。",
        "data_query": "查询指定卫星遥测参数在某个时间段内的值。",
        "load_skills": "根据skill名称加载技能内容。",
    },
    wrap_skill_tag=True,
    use_raw_data_query=True,
)


def build_tooling(
    *,
    skills: Any,
    config: ToolingConfig,
    todo_manager: Any | None = None,
) -> tuple[list[ToolSpec], dict[str, ToolHandler]]:
    spec_factories: dict[str, Callable[[str], ToolSpec]] = {
        "bash": bash_tool.spec,
        "read_file": read_file_tool.spec,
        "read_csv": read_csv_tool.spec,
        "write_file": write_file_tool.spec,
        "edit_file": edit_file_tool.spec,
        "data_query": data_query_tool.spec,
        "load_skills": load_skills_tool.spec,
        "todo": todo_tool.spec,
        "task": task_tool.spec,
        "web_search": web_search_tool.spec,
    }

    data_query_handler: ToolHandler
    if config.use_raw_data_query:
        data_query_handler = lambda args: data_query_tool.run_raw(
            str(args.get("sat_id", "")),
            list(args.get("para_name") or []),
            str(args.get("start_time", "")),
            str(args.get("end_time", "")),
        )
    else:
        data_query_handler = lambda args: data_query_tool.run(
            str(args.get("sat_id", "")),
            list(args.get("para_name") or []),
            str(args.get("start_time", "")),
            str(args.get("end_time", "")),
        )

    handler_factories: dict[str, Callable[[], ToolHandler]] = {
        "bash": lambda: (lambda args: bash_tool.run(str(args.get("command", "")))),
        "read_file": lambda: (lambda args: read_file_tool.run(str(args.get("path", "")), args.get("limit"))),
        "read_csv": lambda: (lambda args: read_csv_tool.run(str(args.get("path", "")), args.get("limit"))),
        "write_file": lambda: (lambda args: write_file_tool.run(str(args.get("path", "")), str(args.get("content", "")))),
        "edit_file": lambda: (
            lambda args: edit_file_tool.run(
                str(args.get("path", "")),
                str(args.get("old_text", "")),
                str(args.get("new_text", "")),
            )
        ),
        "data_query": lambda: data_query_handler,
        "load_skills": lambda: load_skills_tool.build_handler(skills, wrap_in_skill_tag=config.wrap_skill_tag),
        "todo": lambda: todo_tool.build_handler(todo_manager),
        "task": lambda: (lambda args: task_tool.run(str(args.get("prompt", "")), str(args.get("description", "")))),
        "web_search": lambda: (lambda args: web_search_tool.run(str(args.get("query", "")))),
    }

    specs: list[ToolSpec] = []
    handlers: dict[str, ToolHandler] = {}
    for tool_name in config.tool_order:
        if tool_name not in config.descriptions:
            raise ValueError(f"Missing description for tool: {tool_name}")
        if tool_name == "todo" and todo_manager is None:
            raise ValueError("todo_manager is required when todo tool is enabled")
        spec_factory = spec_factories.get(tool_name)
        handler_factory = handler_factories.get(tool_name)
        if spec_factory is None or handler_factory is None:
            raise ValueError(f"Unsupported tool in config: {tool_name}")
        specs.append(spec_factory(config.descriptions[tool_name]))
        handlers[tool_name] = handler_factory()
    return specs, handlers
