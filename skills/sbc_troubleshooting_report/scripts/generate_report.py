#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TREE_SKILL_PATH = PROJECT_ROOT / "skills" / "sbc_network_troubleshooting" / "SKILL.md"
TREE_BLOCK_PATTERN = re.compile(
    r"```yaml\s+sbc-tree\s*\n(?P<yaml>.*?)\n```",
    re.DOTALL,
)

# Business-facing names follow data/仿真数据库说明.md. Supplemental tables and
# views are named separately so they are never misrepresented as one of the 18
# Excel logical access sources.
LOGICAL_SOURCE_BY_TABLE = {
    "ground_link_topology": "星地拓扑数据",
    "planned_topology": "星间规划拓扑",
    "satellite_basic_info": "卫星基础信息",
    "realtime_topology": "星间实时拓扑",
    "keepalive_statistics": "保活时间统计",
    "packetin_message": "PacketIn消息",
    "network_alarm": "网络告警信息（全量告警）",
    "connectionless_continuity_statistics": "无连接服务连续性统计数据",
    "measurement_query": "测量结果查询接口",
    "packet_log": "报文日志信息查询接口（全量）",
    "station_selection_route": "选站路由信息",
    "router_telemetry": "星载路由器遥测参数",
    "laser_telemetry": "激光遥测参数",
    "laser_link_event": "激光链路通断信息",
    "satellite_historical_alarm": "卫星历史告警信息",
    "measurement_anomaly_alarm": "测量异常告警",
}


def _source_tables(evidence: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    tool = str(evidence.get("tool_name", "")).split(" (")[0]
    node_id = str(evidence.get("tree_node_id", ""))
    logical: list[str]
    supplemental: list[str] = []
    if tool == "keep_alive_query":
        logical = ["keepalive_statistics", "ground_link_topology"]
        supplemental = ["v_keepalive_interruptions（查询视图）"]
    elif tool == "connectionless_continuity_query":
        logical = [
            "connectionless_continuity_statistics",
            "keepalive_statistics",
            "planned_topology",
        ]
        supplemental = ["v_keepalive_interruptions（查询视图）", "topology_edge（拓扑明细表）"]
    elif tool == "topology_query":
        if node_id == "E1":
            logical = ["satellite_basic_info", "ground_link_topology"]
            supplemental = [
                "onboard_routing_table_snapshot（仿真增量观测表）",
                "keepalive_landing_candidate（落地关联表）",
            ]
        elif node_id in {"D4", "E2"}:
            logical = ["ground_link_topology"]
            supplemental = [
                "onboard_routing_table_snapshot（仿真增量观测表）",
                "keepalive_landing_candidate（落地关联表）",
            ]
        elif node_id in {"E6", "F1"}:
            logical = ["ground_link_topology", "realtime_topology"]
            supplemental = [
                "onboard_routing_table_snapshot（仿真增量观测表）",
                "keepalive_landing_candidate（落地关联表）",
                "topology_edge（拓扑明细表）",
            ]
            if node_id == "F1":
                logical.append("packetin_message")
        else:
            logical = ["realtime_topology"]
            supplemental = ["topology_edge（拓扑明细表）"]
    elif tool == "packetin_query":
        logical = ["packetin_message"]
    elif tool in {"landing_table_query", "landing_query"}:
        logical = ["ground_link_topology"]
        supplemental = ["landing_table_update_observation（仿真增量观测表）"]
    elif tool in {"feeder_link_query", "feed_link_query"}:
        logical = ["ground_link_topology"]
    elif tool == "SBC_telemetry_query":
        logical = ["router_telemetry", "laser_telemetry"]
    elif tool in {"route_table_query", "routing_query"}:
        logical = ["measurement_query"]
        supplemental = ["onboard_routing_table_snapshot（仿真增量观测表）"]
    elif tool == "route_path_diagnosis":
        logical = ["measurement_query", "ground_link_topology", "realtime_topology"]
        supplemental = [
            "onboard_routing_table_snapshot（仿真增量观测表）",
            "keepalive_landing_candidate（落地关联表）",
            "topology_edge（拓扑明细表）",
        ]
    elif tool == "laser_link_query":
        logical = ["laser_link_event", "laser_telemetry", "realtime_topology"]
        supplemental = ["topology_edge（拓扑明细表）"]
        if node_id == "F7":
            logical.append("packetin_message")
    elif tool == "packet_capture":
        logical = []
        supplemental = ["未接入LAN/WAN分接口抓包源；报文日志信息查询接口（全量）不可替代"]
    elif tool in {"alarm_event_query", "alarm_query"}:
        logical = [
            "network_alarm",
            "satellite_historical_alarm",
            "measurement_anomaly_alarm",
        ]
    else:
        logical = []
        supplemental = ["未识别工具来源，请核对 data/仿真数据库说明.md"]
    return list(dict.fromkeys(logical)), list(dict.fromkeys(supplemental))


def _source_summary(evidence: Mapping[str, Any]) -> list[str]:
    logical_tables, supplemental = _source_tables(evidence)
    lines = []
    if logical_tables:
        labels = [
            f"{LOGICAL_SOURCE_BY_TABLE[table]}（`{table}`）"
            for table in logical_tables
        ]
        lines.append(f"- 逻辑接入源：{'、'.join(labels)}")
    else:
        lines.append("- 逻辑接入源：无原18个逻辑接入源直接对应")
    if supplemental:
        lines.append(f"- 辅助/增量数据源：{'、'.join(supplemental)}")
    return lines


@dataclass(frozen=True)
class ReportRoot:
    node_id: str
    label: str
    next: str


@dataclass(frozen=True)
class ReportNode:
    label: str
    type: str
    shape: str = "process"
    routes: dict[str, str] = field(default_factory=dict)
    next: str | None = None
    outcomes: dict[str, str] = field(default_factory=dict)
    edge_labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ReportTree:
    root: ReportRoot
    nodes: dict[str, ReportNode]


def _load_report_tree(path: Path = TREE_SKILL_PATH) -> ReportTree:
    markdown = path.read_text(encoding="utf-8")
    matches = list(TREE_BLOCK_PATTERN.finditer(markdown))
    if len(matches) != 1:
        raise ValueError(
            f"故障树Skill必须且只能包含一个 `yaml sbc-tree` 块，实际为 {len(matches)} 个"
        )
    raw = yaml.safe_load(matches[0].group("yaml"))
    if not isinstance(raw, dict) or not isinstance(raw.get("root"), dict):
        raise ValueError("sbc-tree YAML缺少root")
    root_raw = raw["root"]
    nodes_raw = raw.get("nodes")
    if not isinstance(nodes_raw, dict):
        raise ValueError("sbc-tree YAML缺少nodes")
    root = ReportRoot(
        node_id=str(root_raw["node_id"]),
        label=str(root_raw["label"]),
        next=str(root_raw["next"]),
    )
    nodes = {
        str(node_id): ReportNode(
            label=str(value.get("label", "")),
            type=str(value.get("type", "")),
            shape=str(value.get("shape", "process")),
            routes={str(key): str(target) for key, target in (value.get("routes") or {}).items()},
            next=str(value["next"]) if value.get("next") is not None else None,
            outcomes={str(key): str(target) for key, target in (value.get("outcomes") or {}).items()},
            edge_labels={str(key): str(label) for key, label in (value.get("edge_labels") or {}).items()},
        )
        for node_id, value in nodes_raw.items()
        if isinstance(value, dict)
    }
    return ReportTree(root=root, nodes=nodes)


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _escape_mermaid_label(label: str) -> str:
    return label.replace('"', "&quot;").replace("\n", "<br/>")


def _render_node(node_id: str, node: ReportNode, judge_id: str | None) -> str:
    display = (
        f"结论：{node.label}"
        if node.type == "conclusion" and not node.label.startswith("结论：")
        else node.label
    )
    if judge_id:
        display = f"{judge_id}<br/>{display}"
    label = _escape_mermaid_label(display)
    if node.shape == "decision":
        return f'{node_id}{{"{label}"}}'
    return f'{node_id}["{label}"]'


def _tree_edges(tree: ReportTree) -> list[tuple[str, str, str]]:
    edges = [(tree.root.node_id, tree.root.next, "")]
    seen = set(edges)
    for node_id, node in tree.nodes.items():
        if node.next:
            edge = (node_id, node.next, "")
            if edge not in seen:
                edges.append(edge)
                seen.add(edge)
        branch_map = node.routes if node.type == "routing" else node.outcomes
        for outcome, target in branch_map.items():
            edge = (node_id, target, node.edge_labels.get(outcome, outcome))
            if edge not in seen:
                edges.append(edge)
                seen.add(edge)
    return edges


def _judge_map(
    branch: list[Mapping[str, Any]],
    evidence: list[Mapping[str, Any]],
    tree: ReportTree,
) -> dict[str, str]:
    evidence_by_id = {
        str(item.get("evidence_id", "")): item
        for item in evidence
        if item.get("evidence_id")
    }
    evidence_by_node: dict[str, list[Mapping[str, Any]]] = {}
    for item in evidence:
        evidence_by_node.setdefault(str(item.get("tree_node_id", "")), []).append(item)

    judges: dict[str, str] = {}
    for step in branch:
        node_id = str(step.get("tree_node_id", ""))
        node = tree.nodes.get(node_id)
        if not node or node.type != "breakpoint":
            continue
        if str(step.get("decision", "")).startswith("incomplete:"):
            continue
        referenced_ids = [str(item) for item in step.get("evidence_ids") or []]
        node_evidence = (
            [evidence_by_id[item] for item in referenced_ids if item in evidence_by_id]
            if referenced_ids
            else evidence_by_node.get(node_id, [])
        )
        if node_evidence and all(
            str(item.get("status", "")).strip().lower() == "valid"
            for item in node_evidence
        ):
            judges[node_id] = f"Judge{len(judges) + 1}"
    return judges


def _render_diagnostic_tree(
    tree: ReportTree,
    branch: list[Mapping[str, Any]],
    judges: Mapping[str, str],
) -> str:
    path_nodes = [str(step.get("tree_node_id", "")) for step in branch]
    path_pairs = {
        (str(step.get("tree_node_id", "")), str(step.get("next_node_id", "")))
        for step in branch
        if step.get("next_node_id")
    }
    lines = ["```mermaid", "flowchart TD"]
    root = tree.root
    lines.append(f'    {root.node_id}["{_escape_mermaid_label(root.label)}"]')
    for node_id, node in tree.nodes.items():
        lines.append(f"    {_render_node(node_id, node, judges.get(node_id))}")

    lines.append("")
    highlighted_edges: list[int] = []
    for index, (source, target, label) in enumerate(_tree_edges(tree)):
        lines.append(
            f"    {source} -->|{label}| {target}"
            if label
            else f"    {source} --> {target}"
        )
        if (source, target) in path_pairs:
            highlighted_edges.append(index)

    lines.extend(
        [
            "",
            "    classDef traversed fill:#DBEAFE,stroke:#2563EB,stroke-width:3px,color:#111827;",
            "    classDef judge fill:#FEF3C7,stroke:#D97706,stroke-width:4px,color:#111827;",
        ]
    )
    traversed_only = [node_id for node_id in path_nodes if node_id not in judges]
    if traversed_only:
        lines.append(f"    class {','.join(dict.fromkeys(traversed_only))} traversed;")
    if judges:
        lines.append(f"    class {','.join(judges)} judge;")
    if highlighted_edges:
        lines.append(
            f"    linkStyle {','.join(str(item) for item in highlighted_edges)} "
            "stroke:#2563EB,stroke-width:4px;"
        )
    lines.append("```")
    return "\n".join(lines)


def _evidence_summary(evidence: Mapping[str, Any]) -> list[str]:
    result = dict(evidence.get("result") or {})
    lines = [
        f"- 证据ID：`{evidence.get('evidence_id', '')}`",
        f"- 工具：`{evidence.get('tool_name', '')}`",
        f"- 证据状态：`{evidence.get('status', '')}`",
        *_source_summary(evidence),
        f"- 查询参数：`{_json_text(evidence.get('query_args') or {})}`",
    ]
    if result.get("database"):
        lines.append(f"- 数据库：`{result['database']}`")
    for key in (
        "outcome",
        "decision_basis",
        "observation_bdt",
        "route_snapshot_bdt",
        "anomaly",
        "pattern",
    ):
        if key in result:
            lines.append(f"- {key}：`{_json_text(result[key])}`")
    for key in ("data", "interruptions", "candidate_events"):
        value = result.get(key)
        if isinstance(value, list):
            lines.append(f"- {key}记录数：{len(value)}")
            if value:
                lines.append(f"- {key}代表记录：`{_json_text(value[:5])}`")
    if result.get("reason"):
        lines.append(f"- 原因：{result['reason']}")
    return lines


def _path_summary(branch: list[Mapping[str, Any]], judges: Mapping[str, str]) -> str:
    parts = []
    for step in branch:
        node_id = str(step.get("tree_node_id", ""))
        marker = f"/{judges[node_id]}" if node_id in judges else ""
        parts.append(f"`{node_id}{marker}`")
    return " → ".join(parts) if parts else "未形成可展示路径"


def build_report(
    document: Mapping[str, Any],
    *,
    tree: ReportTree | None = None,
) -> str:
    required = (
        "session_id",
        "selected_event",
        "status",
        "fault_window",
        "fault_tree_branch",
        "evidence",
        "conclusions",
    )
    missing = [key for key in required if key not in document]
    if missing:
        raise ValueError(f"诊断JSON缺少字段: {', '.join(missing)}")

    tree = tree or _load_report_tree()
    event = dict(document.get("selected_event") or {})
    branch = list(document.get("fault_tree_branch") or [])
    evidence = list(document.get("evidence") or [])
    conclusions = list(document.get("conclusions") or [])
    boundaries = list(document.get("boundaries") or [])
    affected = [str(item) for item in document.get("affected_objects") or []]
    missing_inputs = [str(item) for item in document.get("missing_inputs") or []]
    judges = _judge_map(branch, evidence, tree)

    evidence_by_node: dict[str, list[Mapping[str, Any]]] = {}
    for item in evidence:
        evidence_by_node.setdefault(str(item.get("tree_node_id", "")), []).append(item)

    judge_sections: list[str] = []
    for node_id, judge_id in judges.items():
        step = next(
            (item for item in branch if str(item.get("tree_node_id", "")) == node_id),
            {},
        )
        node = tree.nodes[node_id]
        judge_sections.extend(
            [
                f"### {judge_id} · {node_id} · {node.label}",
                "",
                f"- 判定结果：`{step.get('decision', '')}`",
                f"- 后续节点：`{step.get('next_node_id') or '结束'}`",
                "",
            ]
        )
        for item in evidence_by_node.get(node_id, []):
            judge_sections.extend(
                [
                    f"#### 证据 `{item.get('evidence_id', '')}`",
                    "",
                    *_evidence_summary(item),
                    "",
                ]
            )

    supporting_sections: list[str] = []
    for item in evidence:
        node_id = str(item.get("tree_node_id", ""))
        if node_id in judges:
            continue
        supporting_sections.extend(
            [
                f"### {item.get('evidence_id', '')} · {node_id} · `{item.get('tool_name', '')}`",
                "",
                *_evidence_summary(item),
                "",
            ]
        )

    conclusion_lines = (
        [f"- **{item.get('node_id', '')}**：{item.get('summary', '')}" for item in conclusions]
        or ["- 未形成结论"]
    )
    llm_explanation = str(document.get("llm_explanation") or "").strip()
    llm_error = str(document.get("llm_error") or "").strip()
    llm_lines: list[str] = []
    if llm_explanation:
        llm_lines = ["", "### 模型辅助分析", "", llm_explanation]
    if llm_error:
        llm_lines.extend(["", f"> 模型辅助分析存在异常：{llm_error}"])
    boundary_lines = (
        [
            f"- `{item.get('node_id', '')}`"
            + (f"：{item.get('label', '')}" if item.get("label") else "")
            for item in boundaries
        ]
        or ["- 无"]
    )
    limitation_lines = []
    if document.get("incomplete_reason"):
        limitation_lines.append(f"- {document['incomplete_reason']}")
    limitation_lines.extend(f"- 缺少输入：`{item}`" for item in missing_inputs)
    if not limitation_lines:
        limitation_lines.append("- 未发现阻断本次判断的数据缺失。")

    return "\n".join(
        [
            "# 天基承载网故障排查报告",
            "",
            "## 1. 事件概览",
            "",
            f"- Session：`{document['session_id']}`",
            f"- 事件ID：`{event.get('event_id', '')}`",
            f"- 中断时间：{event.get('interruption_start_bdt', '')} 至 {event.get('interruption_end_bdt', '')}",
            f"- 持续时间：{event.get('duration_seconds', 0)} 秒",
            f"- 影响卫星：{'、'.join(affected) if affected else '未获取'}",
            f"- 初步类型：`{event.get('pattern', '')}`",
            f"- 分析状态：`{document['status']}`",
            f"- 报告生成时间：{document.get('generated_at', '')}",
            "",
            "## 2. 完整故障树与实际故障树分支",
            "",
            "> 图例：蓝色节点和连线表示本次实际经过的分支；橙色节点表示已查询到有效数据并形成判据的关键判断节点（Judge）。未高亮部分为原故障树中本次未经过的分支。",
            "",
            _render_diagnostic_tree(tree, branch, judges),
            "",
            f"实际路径：{_path_summary(branch, judges)}",
            "",
            "## 3. 关键证据（按 Judge 关联）",
            "",
            *(judge_sections or ["- 本次没有查询到足以形成 Judge 的有效判据。", ""]),
            "## 4. 其他证据与缺失证据",
            "",
            *(supporting_sections or ["- 无。", ""]),
            "## 5. 定界节点",
            "",
            *boundary_lines,
            "",
            "## 6. 初步结论",
            "",
            *conclusion_lines,
            *llm_lines,
            "",
            "## 7. 缺失数据与分析限制",
            "",
            *limitation_lines,
            "",
            "## 8. 数据来源",
            "",
            "- 故障树来自 `sbc_network_troubleshooting` Skill 中的当前权威 `yaml sbc-tree`。",
            "- 实际路径、Judge 和证据关联来自SBC LangGraph结构化诊断JSON。",
            "- 报告未重新查询数据库，也未修改故障树判断。",
            "- 完整工具参数及原始查询结果请查看配套JSON工件。",
            "",
        ]
    )


def generate_report(input_path: Path, output_path: Path | None = None) -> Path:
    document = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("诊断JSON根节点必须是对象")
    destination = output_path or input_path.with_name(f"{input_path.stem}_report.md")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(build_report(document), encoding="utf-8")
    return destination.resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description="生成SBC故障排查报告")
    parser.add_argument("input", type=Path, help="SBC结构化诊断JSON")
    parser.add_argument("--output", type=Path, help="Markdown报告输出路径")
    args = parser.parse_args()
    print(generate_report(args.input, args.output))


if __name__ == "__main__":
    main()
