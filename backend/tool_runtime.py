from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


ToolHandler = Callable[[Mapping[str, Any]], Any]
EnabledChecker = Callable[[str], bool]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    category: str = "other"

    def to_openai_function(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(
        self,
        tool_specs: list[ToolSpec],
        handlers: Mapping[str, ToolHandler],
        *,
        enabled_checker: EnabledChecker | None = None,
    ) -> None:
        self._specs: dict[str, ToolSpec] = {item.name: item for item in tool_specs}
        self._handlers: dict[str, ToolHandler] = dict(handlers)
        self._enabled_checker = enabled_checker or (lambda _name: True)

    def set_enabled_checker(self, checker: EnabledChecker | None) -> None:
        self._enabled_checker = checker or (lambda _name: True)

    def list_specs(self) -> list[ToolSpec]:
        return [self._specs[name] for name in sorted(self._specs.keys())]

    def list_items(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for spec in self.list_specs():
            items.append(
                {
                    "tool_name": spec.name,
                    "description": spec.description,
                    "category": spec.category,
                    "enabled": bool(self._enabled_checker(spec.name)),
                    "parameters": spec.parameters,
                }
            )
        return items

    def openai_tools(self) -> list[dict[str, Any]]:
        return [
            spec.to_openai_function()
            for spec in self.list_specs()
            if bool(self._enabled_checker(spec.name))
        ]

    def dispatch(self, tool_name: str, arguments: Mapping[str, Any]) -> Any:
        if tool_name not in self._handlers:
            return {"error": f"Unknown tool: {tool_name}"}
        if not bool(self._enabled_checker(tool_name)):
            return {"error": f"Tool disabled: {tool_name}"}
        handler = self._handlers[tool_name]
        return handler(arguments)
