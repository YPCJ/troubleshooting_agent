from __future__ import annotations

from backend.agents.sbc_network_troubleshooting.tree_schema import (
    FaultTreeDefinition,
    TreeNode,
)


MERMAID_START = "<!-- SBC_TREE_MERMAID_START -->"
MERMAID_END = "<!-- SBC_TREE_MERMAID_END -->"


def _escape_label(label: str) -> str:
    return label.replace('"', "&quot;")


def _render_node(node_id: str, node: TreeNode) -> str:
    display_label = (
        f"结论：{node.label}"
        if node.type == "conclusion" and not node.label.startswith("结论：")
        else node.label
    )
    label = _escape_label(display_label)
    if node.shape == "decision":
        return f'{node_id}{{"{label}"}}'
    return f'{node_id}["{label}"]'


def _render_edge(source: str, target: str, label: str | None = None) -> str:
    if label:
        return f"    {source} -->|{label}| {target}"
    return f"    {source} --> {target}"


def render_mermaid(definition: FaultTreeDefinition) -> str:
    lines = ["```mermaid", "flowchart TD"]
    root = definition.root
    lines.append(f'    {root.node_id}["{_escape_label(root.label)}"]')
    for node_id, node in definition.nodes.items():
        lines.append(f"    {_render_node(node_id, node)}")
    lines.append("")
    lines.append(_render_edge(root.node_id, root.next))
    rendered_edges: set[tuple[str, str, str]] = set()
    for node_id, node in definition.nodes.items():
        if node.next:
            lines.append(_render_edge(node_id, node.next))
        branch_map = node.routes if node.type == "routing" else node.outcomes
        for outcome, target in branch_map.items():
            label = node.edge_labels.get(outcome, outcome)
            edge_key = (node_id, target, label)
            if edge_key in rendered_edges:
                continue
            rendered_edges.add(edge_key)
            lines.append(_render_edge(node_id, target, label))
    lines.append("```")
    return "\n".join(lines)


def replace_mermaid(markdown: str, rendered: str) -> str:
    start = markdown.find(MERMAID_START)
    end = markdown.find(MERMAID_END)
    if start < 0 or end < 0 or end <= start:
        raise ValueError("SKILL.md is missing Mermaid synchronization markers")
    content_start = start + len(MERMAID_START)
    return (
        markdown[:content_start]
        + "\n\n"
        + rendered
        + "\n\n"
        + markdown[end:]
    )
