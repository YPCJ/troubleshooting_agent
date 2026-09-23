from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


NodeType = Literal["routing", "breakpoint", "boundary", "conclusion"]
NodeShape = Literal["process", "decision"]


class RootDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    label: str
    tool: str
    next: str


class TreeNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(default="", exclude=True)
    label: str
    type: NodeType
    shape: NodeShape = "process"
    selector: str | None = None
    routes: dict[str, str] = Field(default_factory=dict)
    next: str | None = None
    tools: list[str] = Field(default_factory=list)
    required_evidence_groups: list[list[str]] = Field(default_factory=list)
    outcomes: dict[str, str] = Field(default_factory=dict)
    edge_labels: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_node_contract(self) -> "TreeNode":
        if self.type == "routing":
            has_routes = bool(self.selector and self.routes)
            if not has_routes and not self.next:
                raise ValueError("routing node requires next or selector + routes")
        elif self.type == "breakpoint":
            if not self.tools:
                raise ValueError("breakpoint node requires tools")
            if not self.outcomes:
                raise ValueError("breakpoint node requires outcomes")
        elif self.type == "boundary" and not self.next:
            raise ValueError("boundary node requires next")
        elif self.type == "conclusion":
            if self.next or self.routes or self.outcomes or self.tools:
                raise ValueError("conclusion node cannot have outgoing edges or tools")

        route_keys = set(self.routes or self.outcomes)
        unknown_labels = set(self.edge_labels) - route_keys
        if unknown_labels:
            raise ValueError(
                f"edge_labels contains unknown keys: {sorted(unknown_labels)}"
            )
        allowed_tools = set(self.tools)
        for group in self.required_evidence_groups:
            missing = set(group) - allowed_tools
            if missing:
                raise ValueError(
                    f"required evidence tools are not allowed: {sorted(missing)}"
                )
        return self

    @property
    def node_type(self) -> str:
        return self.type

    @property
    def allowed_tools(self) -> tuple[str, ...]:
        return tuple(self.tools)

    @property
    def direct_next(self) -> str | None:
        return self.next


class FaultTreeDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    root: RootDefinition
    nodes: dict[str, TreeNode]

    @model_validator(mode="after")
    def bind_node_ids(self) -> "FaultTreeDefinition":
        for node_id, node in self.nodes.items():
            node.node_id = node_id
        return self

    def targets(self, node: TreeNode) -> set[str]:
        result = set(node.routes.values()) | set(node.outcomes.values())
        if node.next:
            result.add(node.next)
        return result

    def conclusions(self) -> dict[str, str]:
        return {
            node_id: node.label
            for node_id, node in self.nodes.items()
            if node.type == "conclusion"
        }

    def validate_graph(self, known_tools: set[str]) -> None:
        if self.version != 1:
            raise ValueError(f"unsupported sbc-tree version: {self.version}")
        if self.root.next not in self.nodes:
            raise ValueError(f"root points to unknown node: {self.root.next}")
        if self.root.tool not in known_tools:
            raise ValueError(f"root uses unknown tool: {self.root.tool}")

        node_ids = set(self.nodes)
        for node_id, node in self.nodes.items():
            unknown_targets = self.targets(node) - node_ids
            if unknown_targets:
                raise ValueError(
                    f"{node_id} points to unknown nodes: {sorted(unknown_targets)}"
                )
            unknown_tools = set(node.tools) - known_tools
            if unknown_tools:
                raise ValueError(
                    f"{node_id} uses unknown tools: {sorted(unknown_tools)}"
                )

        reachable: set[str] = set()
        pending = [self.root.next]
        while pending:
            node_id = pending.pop()
            if node_id in reachable:
                continue
            reachable.add(node_id)
            pending.extend(self.targets(self.nodes[node_id]) - reachable)
        unreachable = node_ids - reachable
        if unreachable:
            raise ValueError(f"unreachable nodes: {sorted(unreachable)}")

        can_reach_conclusion = {
            node_id
            for node_id, node in self.nodes.items()
            if node.type == "conclusion"
        }
        changed = True
        while changed:
            changed = False
            for node_id, node in self.nodes.items():
                if node_id in can_reach_conclusion:
                    continue
                if self.targets(node) & can_reach_conclusion:
                    can_reach_conclusion.add(node_id)
                    changed = True
        dead_ends = reachable - can_reach_conclusion
        if dead_ends:
            raise ValueError(
                f"nodes cannot reach a conclusion: {sorted(dead_ends)}"
            )
