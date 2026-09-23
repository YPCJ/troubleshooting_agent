from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping
import tool_boxes
from langgraph.checkpoint.sqlite import SqliteSaver

from backend.agents.sbc_network_troubleshooting.config import load_runtime_tree
from backend.agents.sbc_network_troubleshooting.graph import (
    SBCNetworkTroubleshootingAgent,
)
from backend.agents.sbc_network_troubleshooting.sqlite_handlers import (
    build_sqlite_handlers,
)
from backend.agents.sbc_network_troubleshooting.tools import (
    SBCDomainToolRegistry,
    build_domain_tool_specs,
)
from backend.fault_diagnoses_agent import (
    SkillCatalog,
    WORKDIR,
    _resolve_model_profile,
    _run_turn_with_tools,
)
from llm.call_tracking import format_model_call_progress
from backend.tool_runtime import ToolRegistry
from backend.tools.registry import FAULT_DIAGNOSES_TOOLING_CONFIG, build_tooling
from skills.sbc_troubleshooting_report.scripts.generate_report import (
    generate_report,
)


def _evidence_record(item: Mapping[str, Any]) -> dict[str, Any]:
    arguments = dict(item.get("query_args") or {})
    return {
        "type": "tool",
        "label": (
            f"{item.get('tool_name', 'unknown')}("
            f"{json.dumps(arguments, ensure_ascii=False, sort_keys=True)})"
        ),
        "result": item.get("result"),
    }


def _latest_user_query(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content", "")).strip()
    return ""


DATE_LITERAL_PATTERN = re.compile(
    r"\d{4}-\d{1,2}-\d{1,2}|\d{4}年\d{1,2}月\d{1,2}日|\d{4}年\d{1,2}月|\d{1,2}:\d{2}"
)
NETWORK_DOMAIN_MARKERS = (
    "无连接",
    "保活",
    "承载网",
    "落地",
    "馈电",
    "星间",
    "packetin",
)


def _is_interruption_discovery_query(query: str) -> bool:
    lowered = query.lower()
    has_date = bool(
        re.search(r"(?:\d{4}-\d{1,2}-\d{1,2}|\d{4}年\d{1,2}月\d{1,2}日)", query)
    )
    # A concrete clock time means the user already knows the fault moment and
    # wants direct diagnosis, not a day-wide list to choose from.
    has_clock_time = bool(re.search(r"\d{1,2}:\d{2}", query)) or bool(
        re.search(r"\d{1,2}[时点]\d{1,2}分", query)
    )
    # Bare "中断" also covers 数传/放电/遥测 faults, so require a carrier-network
    # marker before hijacking the request into keep-alive discovery.
    in_domain = any(marker in lowered for marker in NETWORK_DOMAIN_MARKERS)
    mentions_interruption = "中断" in lowered
    wants_enumeration = any(
        marker in lowered
        for marker in ("哪些", "情况", "列出", "选择", "有没有", "排查")
    )
    return (
        has_date
        and not has_clock_time
        and in_domain
        and mentions_interruption
        and wants_enumeration
    )


def _resolve_event_choice(
    query: str,
    candidates: list[dict[str, Any]],
) -> str | None:
    """Map a chat reply onto exactly one candidate event, or None if ambiguous."""
    if not candidates:
        return None
    upper = query.upper()
    for item in candidates:
        event_id = str(item.get("event_id", ""))
        if event_id and event_id.upper() in upper:
            return event_id
    # Digits inside a date would otherwise be misread as an ordinal pick, so a
    # reply that still carries a date is never treated as a selection.
    if DATE_LITERAL_PATTERN.search(query):
        return None
    picked = {
        int(token)
        for token in re.findall(r"\d+", query)
        if 1 <= int(token) <= len(candidates)
    }
    if len(picked) == 1:
        return str(candidates[picked.pop() - 1].get("event_id", "")) or None
    return None


def _selection_markdown(selection: Mapping[str, Any]) -> str:
    candidates = list(selection.get("candidates") or [])
    lines = [
        f"发现 **{len(candidates)}** 个按完整起止时间合并的无连接中断事件。",
        "请选择一个事件继续执行故障树排查：",
    ]
    for index, event in enumerate(candidates, start=1):
        satellites = [str(item) for item in event.get("satellites", [])]
        preview = "、".join(satellites[:8])
        if len(satellites) > 8:
            preview += f" 等{len(satellites)}颗"
        lines.append(
            f"{index}. `{event.get('event_id', '')}`："
            f"{event.get('interruption_start_bdt', '')} 至 "
            f"{event.get('interruption_end_bdt', '')}；"
            f"{len(satellites)}颗卫星（{preview}）；"
            f"初步类型 `{event.get('pattern', '')}`"
        )
    return "\n".join(lines)


def _diagnosis_markdown(
    result: Mapping[str, Any],
    *,
    report_generated: bool = False,
) -> str:
    structured = dict(result.get("structured_result") or {})
    conclusions = list(structured.get("conclusions") or [])
    if conclusions:
        summaries = "\n".join(
            f"- **{item.get('node_id', '')}**：{item.get('summary', '')}"
            for item in conclusions
        )
        message = (
            f"已完成事件 `{structured.get('selected_event_id', '')}` 的故障树排查。\n\n"
            f"### 初步结论\n{summaries}\n\n"
            f"影响对象：{'、'.join(structured.get('affected_objects') or [])}"
        )
        if report_generated:
            message += "\n\n诊断JSON和排查报告已保存到本Session结果工件。"
        return message
    reason = structured.get("incomplete_reason") or "未形成结论"
    return f"故障树排查未完成：{reason}"


class SBCNetworkTroubleshootingAgentService:
    def __init__(
        self,
        handlers: Mapping[str, Callable[[Mapping[str, Any]], Any]] | None = None,
        *,
        enabled_checker: Callable[[str], bool] | None = None,
        checkpoint_path: str | None = None,
        report_output_root: Path | None = None,
    ) -> None:
        domain_handlers = build_sqlite_handlers()
        domain_handlers.update(dict(handlers or {}))
        self.tool_registry = SBCDomainToolRegistry(
            domain_handlers,
            enabled_checker=enabled_checker,
        )
        checkpoint_file = (
            checkpoint_path
            or os.getenv("SBC_CHECKPOINT_PATH")
            or str(WORKDIR / "data" / "sbc_langgraph_checkpoints.sqlite3")
        )
        self._checkpoint_connection = sqlite3.connect(
            checkpoint_file,
            check_same_thread=False,
        )
        self.checkpointer = SqliteSaver(self._checkpoint_connection)
        self.checkpointer.setup()
        self.agent = SBCNetworkTroubleshootingAgent(
            self.tool_registry,
            checkpointer=self.checkpointer,
        )
        self.report_output_root = (
            Path(report_output_root)
            if report_output_root
            else (WORKDIR / "outputs" / "sbc")
        )
        self.skills = SkillCatalog(WORKDIR / "skills")
        self.todo_manager = tool_boxes.TodoManager()
        general_specs, general_handlers = build_tooling(
            skills=self.skills,
            config=FAULT_DIAGNOSES_TOOLING_CONFIG,
            todo_manager=self.todo_manager,
        )
        self.general_registry = ToolRegistry(
            general_specs,
            general_handlers,
            enabled_checker=enabled_checker,
        )
        self.hybrid_registry = ToolRegistry(
            [*general_specs, *build_domain_tool_specs()],
            {**general_handlers, **domain_handlers},
            enabled_checker=enabled_checker,
        )

    @property
    def system_prompt(self) -> str:
        return (
            f"你是天基承载网与卫星系统故障诊断智能体，工作目录是 {WORKDIR}。\n"
            "你同时具备通用故障诊断能力和天基承载网领域查询工具。"
            "不要因为用户只提供月份、日期范围或模糊现象就拒绝任务；应先把范围规范化，再调用工具取证。\n"
            "复杂排查任务必须先调用 todo 建立待办，并在每个阶段更新状态。"
            "如果问题涉及天基承载网、保活、落地、馈电、星间链路、PacketIn 或无连接服务，"
            "第一个实质性诊断工具必须是 keep_alive_query，用于确认保活是否真的中断；"
            "确认后再根据证据调用拓扑、馈电、路由、激光、告警等工具。\n"
            "工具只提供现象证据。禁止从字段名称或告警标题直接臆断根因；"
            "结论必须列出证据、时间关系、排除项和置信度。用户要求报告时生成初步分析报告。\n"
            "用户确认具体保活中断后，用 connectionless_continuity_query 查询连续性和事件分组。"
            "只合并原始起止时间均一致的多星中断，长期覆盖短期不能合并，按组内邻居顺序取证。"
            "PacketIn边界匹配使用同一affected_link的LINK_DOWN/UP发生时间，容差4.5秒；"
            "地面接收时间不能替代发生时间。路由表每半小时采样，不得用未来快照倒推精确故障时刻。"
            "LAN/WAN分接口收发暂缺证据；末端节点指当前实际落地路由树中的叶子节点："
            "目标星有经下一跳到实际可用落地星的路由，且没有其他卫星经目标星落地。"
            "E1调用topology_query时提供check_terminal_node=true和observation_bdt，"
            "物理邻居数量不能替代实际路由父子关系。\n"
            "单星中断横跨多个落地星为长时间，只涉及一个落地星弧段为单圈次；"
            "两颗以上起止完全一致为一批。固定落地星按中断开始时刻判断。"
            "邻居取实时拓扑上下左右星，PacketIn优先；无PacketIn再查双端激光锁定。"
            "H2无延时遥测按否处理；I3必须注明邻居卫星扩散响应计数未获取。"
            "F6直接结论为需根据抓包结果具体排查，不用普通packet_log冒充分接口抓包。\n"
            "对于能源、热控、姿轨控等非承载网问题，使用通用工具和相关 skill，不强制查询保活。\n"
            f"可用 skill：\n{self.skills.descriptions()}\n"
        )

    def list_tools(self) -> list[dict[str, Any]]:
        domain_availability = {
            item["tool_name"]: item.get("available")
            for item in self.tool_registry.list_items()
        }
        items = self.hybrid_registry.list_items()
        for item in items:
            item["available"] = domain_availability.get(item["tool_name"], True)
        return items

    def set_tool_enabled_checker(
        self,
        checker: Callable[[str], bool] | None,
    ) -> None:
        self.tool_registry.set_enabled_checker(checker)
        self.general_registry.set_enabled_checker(checker)
        self.hybrid_registry.set_enabled_checker(checker)

    def run_turn(
        self,
        messages: list[dict[str, Any]],
        model_profile: str | None = None,
        on_trace: Callable[[str], None] | None = None,
        on_record: Callable[[dict[str, Any]], None] | None = None,
        on_assistant_message: Callable[[dict[str, Any]], None] | None = None,
        session_id: str | None = None,
        selected_event_id: str | None = None,
    ) -> dict[str, Any]:
        query = _latest_user_query(messages)
        if selected_event_id:
            if not session_id:
                raise ValueError("恢复SBC事件排查必须提供session_id")
            before = self.agent.pending_selection(thread_id=session_id)
            if before is None:
                raise ValueError("当前Session没有等待选择的SBC中断事件")
            valid_ids = {
                str(item.get("event_id", ""))
                for item in before.get("candidates", [])
            }
            if selected_event_id not in valid_ids:
                raise ValueError("所选中断事件不属于当前Session的候选事件")
            prior_evidence_count = len(
                self.agent.graph.get_state(
                    config={"configurable": {"thread_id": session_id}},
                ).values.get("evidence", [])
            )
            on_state, streamed = self._stream_records(
                prior_evidence_count=prior_evidence_count,
                on_record=on_record,
                on_trace=on_trace,
            )
            graph_result = self.agent.resume_event_selection(
                selected_event_id,
                thread_id=session_id,
                model_profile=_resolve_model_profile(model_profile),
                on_state=on_state,
            )
            return self._graph_result(
                graph_result,
                prior_evidence_count=prior_evidence_count,
                on_record=on_record,
                on_assistant_message=on_assistant_message,
                streamed_records=streamed,
            )

        pending = (
            self.agent.pending_selection(thread_id=session_id)
            if session_id
            else None
        )
        if pending is not None:
            resolved = _resolve_event_choice(query, pending.get("candidates", []))
            if resolved:
                return self.run_turn(
                    messages,
                    model_profile=model_profile,
                    on_trace=on_trace,
                    on_record=on_record,
                    on_assistant_message=on_assistant_message,
                    session_id=session_id,
                    selected_event_id=resolved,
                )
            if not _is_interruption_discovery_query(query):
                message = (
                    f"{_selection_markdown(pending)}\n\n"
                    "未能从你的回复中唯一确定事件。请回复事件编号（例如 `3`）或完整事件ID。"
                )
                if on_assistant_message:
                    on_assistant_message({"content": message, "tokens": 0})
                return {
                    "status": "awaiting_selection",
                    "selection_request": pending,
                    "assistant_messages": [{"content": message, "tokens": 0}],
                    "records": [],
                    "artifacts": [],
                    "model_calls": 0,
                    "usage": {"total_tokens": 0},
                }

        if session_id and _is_interruption_discovery_query(query):
            on_state, streamed = self._stream_records(
                prior_evidence_count=0,
                on_record=on_record,
                on_trace=on_trace,
            )
            graph_result = self.agent.start_event_selection(
                {
                    "session_id": session_id,
                    "user_query": query,
                    "report_requested": "报告" in query,
                    "model_profile": _resolve_model_profile(model_profile),
                },
                thread_id=session_id,
                on_state=on_state,
            )
            return self._graph_result(
                graph_result,
                prior_evidence_count=0,
                on_record=on_record,
                on_assistant_message=on_assistant_message,
                streamed_records=streamed,
            )

        required_tools: list[str] = []
        network_markers = (
            "天基承载网",
            "承载网",
            "保活",
            "落地",
            "馈电",
            "星间",
            "激光链路",
            "packetin",
            "无连接服务",
        )
        is_network_diagnosis = any(
            marker in query.lower() for marker in network_markers
        )
        if is_network_diagnosis:
            required_tools.append("todo")
            required_tools.append("keep_alive_query")
        active_registry = (
            self.hybrid_registry if is_network_diagnosis else self.general_registry
        )
        return _run_turn_with_tools(
            system_prompt=self.system_prompt,
            messages=messages,
            tools=active_registry.openai_tools(),
            dispatch_tool=active_registry.dispatch,
            runtime_profile=_resolve_model_profile(model_profile),
            max_rounds=30,
            final_prompt=(
                "请不要再调用工具，基于现有证据给出结论、关键数据、排除项、"
                "置信度和下一步建议；如果用户要求报告，请按初步分析报告格式输出。"
            ),
            on_trace=on_trace,
            on_record=on_record,
            on_assistant_message=on_assistant_message,
            required_tool_sequence=tuple(required_tools),
        )

    def pending_selection(self, session_id: str) -> dict[str, Any] | None:
        return self.agent.pending_selection(thread_id=session_id)

    def close(self) -> None:
        self._checkpoint_connection.close()

    def _stream_records(
        self,
        *,
        prior_evidence_count: int,
        on_record: Callable[[dict[str, Any]], None] | None,
        on_trace: Callable[[str], None] | None = None,
    ) -> tuple[Callable[[Mapping[str, Any]], None] | None, list[dict[str, Any]]]:
        """Build an ``on_state`` hook that pushes tool records as nodes finish.

        Without this the whole tree walk completes before any record reaches the
        UI, which makes a multi-step diagnosis look like it resolved instantly.
        ``emitted`` is shared with ``_graph_result`` so the final pass can skip
        records that were already streamed instead of duplicating them.
        """
        if on_record is None and on_trace is None:
            return None, []
        emitted: list[dict[str, Any]] = []
        emitted_model_calls = 0

        def on_state(state: Mapping[str, Any]) -> None:
            nonlocal emitted_model_calls
            evidence = list(state.get("evidence") or [])
            start = prior_evidence_count + len(emitted)
            for item in evidence[start:]:
                record = _evidence_record(item)
                emitted.append(record)
                if on_record:
                    on_record(record)
            current_model_calls = int(state.get("model_calls", 0) or 0)
            while emitted_model_calls < current_model_calls:
                emitted_model_calls += 1
                if on_trace:
                    on_trace(f"## {format_model_call_progress(emitted_model_calls)}")

        return on_state, emitted

    def _graph_result(
        self,
        graph_result: Mapping[str, Any],
        *,
        prior_evidence_count: int,
        on_record: Callable[[dict[str, Any]], None] | None,
        on_assistant_message: Callable[[dict[str, Any]], None] | None,
        streamed_records: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        evidence = list(graph_result.get("evidence") or [])
        already_streamed = len(streamed_records or [])
        records = list(streamed_records or [])
        for item in evidence[prior_evidence_count + already_streamed:]:
            record = _evidence_record(item)
            records.append(record)
            if on_record:
                on_record(record)

        selection = self.agent.pending_selection(
            thread_id=str(graph_result.get("session_id", "")),
        )
        artifacts: list[dict[str, Any]] = []
        if selection is not None:
            message = _selection_markdown(selection)
            status = "awaiting_selection"
        else:
            status = str(graph_result.get("status") or "completed")
            if graph_result.get("selected_event_id"):
                skill_record = {
                    "type": "skill",
                    "label": 'load_skills({"name":"sbc_troubleshooting_report"})',
                    "source_kind": "skill",
                    "source_name": "sbc_troubleshooting_report",
                    "source_path": str(
                        WORKDIR
                        / "skills"
                        / "sbc_troubleshooting_report"
                        / "SKILL.md"
                    ),
                }
                records.append(skill_record)
                if on_record:
                    on_record(skill_record)
                artifacts = self._write_diagnosis_artifacts(graph_result)
            message = _diagnosis_markdown(
                graph_result,
                report_generated=bool(artifacts),
            )
        explanation = str(graph_result.get("llm_explanation") or "").strip()
        llm_error = str(graph_result.get("llm_error") or "").strip()
        if explanation:
            message += f"\n\n### 模型辅助分析\n{explanation}"
        if llm_error:
            message += f"\n\n> 模型辅助调用存在异常：{llm_error}"
        total_tokens = int(
            ((graph_result.get("model_usage") or {}).get("total_tokens")) or 0
        )
        model_calls = int(graph_result.get("model_calls", 0) or 0)
        assistant = {
            "content": message,
            "model": (graph_result.get("model_profile") or None) if model_calls else None,
            "tokens": total_tokens,
        }
        if on_assistant_message:
            on_assistant_message(assistant)
        return {
            "status": status,
            "selection_request": selection,
            "structured_result": graph_result.get("structured_result"),
            "assistant_messages": [assistant],
            "records": records,
            "artifacts": artifacts,
            "model_calls": model_calls,
            "usage": {"total_tokens": total_tokens},
        }

    def _write_diagnosis_artifacts(
        self,
        graph_result: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        tree = load_runtime_tree()
        conclusion_labels = tree.conclusions()
        structured = dict(graph_result.get("structured_result") or {})
        event_id = str(graph_result.get("selected_event_id") or "unknown-event")
        selected_event = next(
            (
                dict(item)
                for item in graph_result.get("candidate_events", [])
                if str(item.get("event_id", "")) == event_id
            ),
            {},
        )
        branch = []
        for step in graph_result.get("traversal", []):
            node_id = str(step.get("tree_node_id", ""))
            node = tree.nodes.get(node_id)
            node_label = (
                tree.root.label
                if node_id == tree.root.node_id
                else node.label if node else conclusion_labels.get(node_id, "")
            )
            branch.append(
                {
                    **dict(step),
                    "label": node_label,
                }
            )
        boundaries = []
        for item in structured.get("boundaries") or []:
            node_id = str(item.get("node_id", ""))
            node = tree.nodes.get(node_id)
            boundaries.append(
                {
                    "node_id": node_id,
                    "label": (
                        node.label
                        if node
                        else conclusion_labels.get(node_id, "")
                    ),
                }
            )
        document = {
            "schema_version": "1.0",
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "session_id": str(graph_result.get("session_id", "")),
            "selected_event": selected_event,
            "status": structured.get("status", graph_result.get("status", "")),
            "fault_window": structured.get("fault_window", {}),
            "affected_objects": structured.get("affected_objects", []),
            "fault_tree_branch": branch,
            "evidence": list(graph_result.get("evidence") or []),
            "boundaries": boundaries,
            "conclusions": list(structured.get("conclusions") or []),
            "incomplete_reason": structured.get("incomplete_reason"),
            "missing_inputs": list(structured.get("missing_inputs") or []),
            "llm_judgements": list(graph_result.get("llm_judgements") or []),
            "llm_explanation": str(graph_result.get("llm_explanation") or ""),
            "llm_error": graph_result.get("llm_error"),
        }
        session_name = re.sub(
            r"[^A-Za-z0-9_.-]+",
            "_",
            str(graph_result.get("session_id") or "unknown-session"),
        )
        event_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", event_id)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        output_dir = self.report_output_root / session_name
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / f"{event_name}_{timestamp}_diagnosis.json"
        report_path = output_dir / f"{event_name}_{timestamp}_report.md"
        json_path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        generate_report(json_path, report_path)
        return [
            {
                "id": f"art_sbc_json_{timestamp}",
                "name": json_path.name,
                "path": str(json_path.resolve()),
                "artifact_type": "data",
                "session_id": "",
            },
            {
                "id": f"art_sbc_report_{timestamp}",
                "name": report_path.name,
                "path": str(report_path.resolve()),
                "artifact_type": "document",
                "session_id": "",
            },
        ]
