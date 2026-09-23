from __future__ import annotations

from typing import Any, Callable

from backend.fault_diagnoses_agent import (
    SkillCatalog,
    WORKDIR,
    _now_stamp,
    _resolve_model_profile,
    _run_turn_with_tools,
)
from backend.tool_runtime import ToolRegistry
from backend.tools.registry import LOG_TRANSFORM_TOOLING_CONFIG, build_tooling


class LogTransformAgentService:
    def __init__(self, skills_dir=None, *, enabled_checker: Callable[[str], bool] | None = None):
        self.skills_dir = skills_dir or (WORKDIR / "skills")
        self.skills = SkillCatalog(self.skills_dir)
        specs, handlers = build_tooling(
            skills=self.skills,
            config=LOG_TRANSFORM_TOOLING_CONFIG,
        )
        self.tool_registry = ToolRegistry(
            specs,
            handlers,
            enabled_checker=enabled_checker,
        )

    @property
    def system_prompt(self) -> str:
        return (
            f"你是一个故障排查专家.工作在{WORKDIR}目录下，现在的时间是{_now_stamp()}。\n"
            "你工作在跨平台环境中（macOS/Linux/Windows），请根据当前系统选择合适命令，并优先使用当前环境可用的 Python 解释器。\n"
            "读取 .csv/.txt/.md 等文件内容时，不要使用 bash 执行 head/cat/awk 等直接读取原始字节，优先使用 read_csv 或 read_file 工具。\n"
            "在处理你不熟悉的任务时使用你的skill技能来解决问题。你在调用函数工具时，会严格按照要求撰写。\n"
            f"可以采用的skill技能包括：\n{self.skills.descriptions()}\n"
        )

    def list_tools(self) -> list[dict[str, Any]]:
        return self.tool_registry.list_items()

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
            final_prompt="请不要再调用任何工具，基于已有上下文直接给出最终答复。需要包含：处理结论、关键步骤、输出文件路径（如果有）。",
            on_trace=on_trace,
            on_record=on_record,
            on_assistant_message=on_assistant_message,
        )
