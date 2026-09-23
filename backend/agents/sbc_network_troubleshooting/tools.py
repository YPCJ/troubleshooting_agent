from __future__ import annotations

from typing import Any, Callable, Mapping

from backend.agents.sbc_network_troubleshooting.config import DOMAIN_TOOL_DESCRIPTIONS
from backend.tool_runtime import ToolRegistry, ToolSpec


def _tool_spec(name: str, description: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        category="sbc",
        parameters={
            "type": "object",
            "properties": {
                "start_time": {"type": "string"},
                "end_time": {"type": "string"},
                "source_sat": {"type": "string"},
                "satellite_id": {"type": "string"},
                "landing_satellite_id": {"type": "string", "description": "落地表上注和响应观测的直连卫星。"},
                "destination_satellite_id": {"type": "string", "description": "筛选星上路由快照中的目的卫星；不等同于查询源星。"},
                "target_station": {"type": "string"},
                "affected_link": {
                    "type": "string",
                    "description": "PacketIn中的affected_link原值；指定链路精确匹配时使用。H17未指定时会在边界附近自动寻找DOWN/UP同链路配对。",
                },
                "interruption_start_bdt": {"type": "string"},
                "interruption_end_bdt": {"type": "string"},
                "observation_bdt": {"type": "string", "description": "实际落地路由末端判断的精确BDT时刻，须在查询窗口内。"},
                "check_terminal_node": {"type": "boolean", "description": "判断目标星是否有实际落地路径，且没有其他卫星经目标星落地；仅限单颗卫星。"},
                "affected_objects": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "parameter_code": {"type": "string"},
                "parameter_name": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
            },
        },
    )


def build_domain_tool_specs() -> list[ToolSpec]:
    return [
        _tool_spec(name, description)
        for name, description in DOMAIN_TOOL_DESCRIPTIONS.items()
    ]


class SBCDomainToolRegistry:
    def __init__(
        self,
        handlers: Mapping[str, Callable[[Mapping[str, Any]], Any]] | None = None,
        *,
        enabled_checker: Callable[[str], bool] | None = None,
    ) -> None:
        self._handlers = dict(handlers or {})
        specs = build_domain_tool_specs()
        self._registry = ToolRegistry(
            specs,
            self._handlers,
            enabled_checker=enabled_checker,
        )

    def dispatch(self, tool_name: str, arguments: Mapping[str, Any]) -> Any:
        return self._registry.dispatch(tool_name, arguments)

    def list_items(self) -> list[dict[str, Any]]:
        items = self._registry.list_items()
        for item in items:
            item["available"] = item["tool_name"] in self._handlers
        return items

    def available(self, tool_name: str) -> bool:
        return tool_name in self._handlers

    def set_enabled_checker(self, checker: Callable[[str], bool] | None) -> None:
        self._registry.set_enabled_checker(checker)
