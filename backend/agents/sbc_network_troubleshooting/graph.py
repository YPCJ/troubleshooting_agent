from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from llm import chat_reply

from backend.agents.sbc_network_troubleshooting.config import load_runtime_tree
from backend.agents.sbc_network_troubleshooting.evidence import (
    build_evidence,
    resolve_outcome,
    validate_required_evidence,
)
from backend.agents.sbc_network_troubleshooting.state import (
    SBCTroubleshootingState,
    initial_state,
)
from backend.agents.sbc_network_troubleshooting.tools import SBCDomainToolRegistry


# LangGraph marks a paused run with this reserved key in the stream.
_INTERRUPT_KEY = "__interrupt__"

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
TIME_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?)")
DATE_PATTERN = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
CHINESE_DATE_PATTERN = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
SAT_PATTERN = re.compile(
    r"\b(?:SAT[-_]?[A-Za-z0-9]+|A(?:0[1-6])(?:0[1-9]|10))\b",
    re.IGNORECASE,
)


def _model_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "\n".join(
            str(item.get("text", "")) if isinstance(item, dict) else str(item)
            for item in content
        ).strip()
    return str(content or "").strip()


def _model_tokens(response: Mapping[str, Any], text: str) -> int:
    return int((response.get("usage") or {}).get("total_tokens") or max(1, len(text) // 4))


def _compact_evidence(state: SBCTroubleshootingState, *, limit: int = 3000) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in state.get("evidence", []):
        result_text = json.dumps(item.get("result"), ensure_ascii=False, default=str)
        if len(result_text) > limit:
            result_text = f"{result_text[:limit]}…(已截断，原始长度{len(result_text)})"
        compact.append(
            {
                "evidence_id": item.get("evidence_id"),
                "tree_node_id": item.get("tree_node_id"),
                "tool_name": item.get("tool_name"),
                "status": item.get("status"),
                "query_args": item.get("query_args"),
                "result": result_text,
            }
        )
    return compact


def _parse_json_object(text: str) -> dict[str, Any] | None:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", candidate, flags=re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _append_step(
    state: SBCTroubleshootingState,
    *,
    node_id: str,
    node_type: str,
    decision: str,
    evidence_ids: list[str],
    next_node_id: str | None,
) -> list[dict[str, Any]]:
    return [
        *state.get("traversal", []),
        {
            "tree_node_id": node_id,
            "node_type": node_type,
            "decision": decision,
            "evidence_ids": evidence_ids,
            "next_node_id": next_node_id,
        },
    ]


def _normalize_input(state: SBCTroubleshootingState) -> dict[str, Any]:
    query = state.get("user_query", "").strip()
    update: dict[str, Any] = {}
    if not state.get("fault_time"):
        match = TIME_PATTERN.search(query)
        if match:
            value = match.group(1).replace("T", " ")
            if len(value) == 16:
                value += ":00"
            update["fault_time"] = value
    if (
        state.get("workflow_mode") == "event_selection"
        and not state.get("start_time")
        and not state.get("end_time")
    ):
        date_match = DATE_PATTERN.search(query)
        chinese_date_match = CHINESE_DATE_PATTERN.search(query)
        if date_match or chinese_date_match:
            day_start = (
                datetime(
                    int(date_match.group(1)),
                    int(date_match.group(2)),
                    int(date_match.group(3)),
                )
                if date_match
                else datetime(
                    int(chinese_date_match.group(1)),
                    int(chinese_date_match.group(2)),
                    int(chinese_date_match.group(3)),
                )
            )
            update["start_time"] = day_start.strftime(TIME_FORMAT)
            update["end_time"] = (day_start + timedelta(days=1)).strftime(TIME_FORMAT)
    if not state.get("affected_objects"):
        update["affected_objects"] = list(dict.fromkeys(SAT_PATTERN.findall(query)))
    if not state.get("normalized_symptom"):
        update["normalized_symptom"] = query
    if not state.get("report_requested"):
        update["report_requested"] = any(
            word in query.lower() for word in ("报告", "markdown", ".md")
        )
    return update


def _validate_scope(state: SBCTroubleshootingState) -> dict[str, Any]:
    query = state.get("user_query", "")
    in_scope_markers = (
        "天基", "承载网", "卫星", "落地", "馈电", "激光链路", "无连接", "sbc",
    )
    if query and not any(marker in query.lower() for marker in in_scope_markers):
        return {
            "status": "out_of_scope",
            "incomplete_reason": "仅支持天基承载网故障排查",
        }
    missing = []
    if not state.get("fault_time") and not (
        state.get("start_time") and state.get("end_time")
    ):
        missing.append("fault_time")
    if missing:
        return {
            "status": "incomplete",
            "missing_inputs": missing,
            "incomplete_reason": "缺少故障时间，无法生成默认查询窗口",
        }
    return {"status": "running", "missing_inputs": []}


def _create_time_window(state: SBCTroubleshootingState) -> dict[str, Any]:
    if state.get("start_time") and state.get("end_time"):
        return {}
    fault_time = datetime.strptime(state["fault_time"], TIME_FORMAT)
    return {
        "start_time": (fault_time - timedelta(minutes=10)).strftime(TIME_FORMAT),
        "end_time": (fault_time + timedelta(minutes=10)).strftime(TIME_FORMAT),
    }


def _infer_pattern(state: SBCTroubleshootingState) -> str:
    explicit = state.get("pattern", "")
    if explicit:
        return explicit
    query = state.get("normalized_symptom", "")
    if "固定" in query and ("一批" in query or "批量" in query):
        return "fixed_sat_batch"
    if "固定" in query and ("落地星" in query or "落地卫星" in query):
        return "fixed_landing_sat"
    if len(state.get("affected_objects", [])) > 1:
        return "multiple_sat_network"
    if "多圈" in query or "长时间" in query:
        return "single_sat_long"
    return "single_pass"


class SBCNetworkTroubleshootingAgent:
    def __init__(
        self,
        tool_registry: SBCDomainToolRegistry | None = None,
        *,
        checkpointer: Any | None = None,
        model_caller: Callable[..., Mapping[str, Any]] | None = None,
    ) -> None:
        self.tool_registry = tool_registry or SBCDomainToolRegistry()
        self.checkpointer = checkpointer or InMemorySaver()
        self.model_caller = model_caller
        self.graph = build_sbc_graph(
            self.tool_registry,
            checkpointer=self.checkpointer,
            model_caller=self.model_caller,
        )

    def _run(
        self,
        graph_input: Any,
        *,
        thread_id: str,
        on_state: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Drive the graph node by node so callers can observe intermediate state.

        ``stream_mode="values"`` emits the full state after every node, which lets
        the service push tool evidence to the UI while the tree is still walking
        instead of dumping everything once the whole graph has finished.
        """
        config = {"configurable": {"thread_id": thread_id}}
        latest: dict[str, Any] = {}
        for chunk in self.graph.stream(
            graph_input,
            config=config,
            stream_mode="values",
        ):
            if not isinstance(chunk, Mapping):
                continue
            # An interrupt surfaces as a sentinel chunk rather than graph state;
            # it carries no node output, so it must not overwrite ``latest``.
            if _INTERRUPT_KEY in chunk:
                continue
            latest = dict(chunk)
            if on_state:
                on_state(latest)
        # The checkpointer holds the authoritative merged state, which also covers
        # the interrupted case where the last streamed chunk predates the pause.
        snapshot = self.graph.get_state(config=config)
        if snapshot.values:
            return dict(snapshot.values)
        return latest

    def invoke(
        self,
        payload: dict[str, Any],
        *,
        thread_id: str | None = None,
        on_state: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> SBCTroubleshootingState:
        state = initial_state(payload)
        runtime_thread_id = thread_id or state.get("session_id") or "sbc-default"
        # Reload SKILL.md for every turn so a running service never executes a
        # stale in-memory copy after operators update the fault tree.
        self.graph = build_sbc_graph(
            self.tool_registry,
            checkpointer=self.checkpointer,
            model_caller=self.model_caller,
        )
        return self._run(state, thread_id=runtime_thread_id, on_state=on_state)

    def start_event_selection(
        self,
        payload: dict[str, Any],
        *,
        thread_id: str,
        on_state: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        state = initial_state({**payload, "workflow_mode": "event_selection"})
        self.graph = build_sbc_graph(
            self.tool_registry,
            checkpointer=self.checkpointer,
            model_caller=self.model_caller,
        )
        return self._run(state, thread_id=thread_id, on_state=on_state)

    def resume_event_selection(
        self,
        event_id: str,
        *,
        thread_id: str,
        model_profile: str = "",
        on_state: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        return self._run(
            Command(resume={"event_id": event_id, "model_profile": model_profile}),
            thread_id=thread_id,
            on_state=on_state,
        )

    def pending_selection(self, *, thread_id: str) -> dict[str, Any] | None:
        snapshot = self.graph.get_state(
            config={"configurable": {"thread_id": thread_id}},
        )
        values = dict(snapshot.values or {})
        if "select_event" not in set(snapshot.next or ()):
            return None
        candidates = list(values.get("candidate_events") or [])
        if not candidates:
            return None
        return {
            "type": "event_selection",
            "prompt": "请选择需要继续排查的无连接中断事件",
            "candidates": candidates,
        }


def build_sbc_graph(
    tool_registry: SBCDomainToolRegistry,
    *,
    checkpointer: Any | None = None,
    model_caller: Callable[..., Mapping[str, Any]] | None = None,
):
    call_model = model_caller or chat_reply
    tree_definition = load_runtime_tree()
    tree_nodes = tree_definition.nodes
    conclusions = tree_definition.conclusions()

    def detect_anomaly(state: SBCTroubleshootingState) -> dict[str, Any]:
        arguments = {
            "start_time": state["start_time"],
            "end_time": state["end_time"],
            "observation_bdt": state.get("fault_time", ""),
            "source_sat": state.get("source_sat", ""),
            "affected_objects": state.get("affected_objects", []),
            **state.get("tool_arguments", {}).get("keep_alive_query", {}),
        }
        root_tool = tree_definition.root.tool
        result = tool_registry.dispatch(root_tool, arguments)
        evidence = build_evidence(
            sequence=len(state.get("evidence", [])) + 1,
            node_id=tree_definition.root.node_id,
            tool_name=root_tool,
            arguments=arguments,
            result=result,
        )
        update: dict[str, Any] = {"evidence": [*state.get("evidence", []), evidence]}
        if evidence["status"] != "valid":
            update.update(
                status="incomplete",
                incomplete_reason=(
                    f"{root_tool} 工具不可用"
                    if evidence["status"] == "tool_unavailable"
                    else f"{root_tool} 未返回有效异常数据"
                ),
            )
            return update
        normalized = evidence["result"]
        if normalized.get("anomaly") is False:
            update.update(status="no_anomaly", incomplete_reason=None)
            return update
        affected = normalized.get("affected_objects")
        if isinstance(affected, list) and affected:
            update["affected_objects"] = [str(item) for item in affected]
        classification = normalized.get("classification")
        if isinstance(classification, dict):
            update["interruption_start_bdt"] = str(
                classification.get("interruption_start_bdt") or ""
            )
            update["interruption_end_bdt"] = str(
                classification.get("interruption_end_bdt") or ""
            )
        update["pattern"] = str(normalized.get("pattern") or _infer_pattern({**state, **update}))
        update["current_tree_node_id"] = tree_definition.root.next
        update["traversal"] = _append_step(
            state,
            node_id=tree_definition.root.node_id,
            node_type="classification",
            decision="anomaly_detected",
            evidence_ids=[evidence["evidence_id"]],
            next_node_id=update["current_tree_node_id"],
        )
        return update

    def discover_interruptions(state: SBCTroubleshootingState) -> dict[str, Any]:
        arguments = {
            "start_time": state["start_time"],
            "end_time": state["end_time"],
            "limit": 1000,
        }
        root_tool = tree_definition.root.tool
        result = tool_registry.dispatch(root_tool, arguments)
        evidence = build_evidence(
            sequence=len(state.get("evidence", [])) + 1,
            node_id=tree_definition.root.node_id,
            tool_name=root_tool,
            arguments=arguments,
            result=result,
        )
        update: dict[str, Any] = {
            "evidence": [*state.get("evidence", []), evidence],
        }
        if evidence["status"] != "valid":
            return {
                **update,
                "status": "incomplete",
                "incomplete_reason": f"{root_tool} 未返回有效异常数据",
            }
        normalized = evidence["result"]
        if normalized.get("truncated") or normalized.get("groups_complete") is False:
            return {
                **update,
                "status": "incomplete",
                "incomplete_reason": "保活中断查询结果被截断，不能生成完整候选事件",
            }
        candidates = list(normalized.get("candidate_events") or [])
        if not candidates:
            return {
                **update,
                "status": "no_anomaly",
                "incomplete_reason": None,
            }
        return {
            **update,
            "candidate_events": candidates,
            "status": "awaiting_selection",
        }

    def select_event(state: SBCTroubleshootingState) -> dict[str, Any]:
        selection = interrupt(
            {
                "type": "event_selection",
                "prompt": "请选择需要继续排查的无连接中断事件",
                "candidates": state.get("candidate_events", []),
            }
        )
        event_id = (
            str(selection.get("event_id", "")).strip()
            if isinstance(selection, dict)
            else str(selection).strip()
        )
        selected = next(
            (
                item for item in state.get("candidate_events", [])
                if str(item.get("event_id", "")) == event_id
            ),
            None,
        )
        if selected is None:
            raise ValueError("所选中断事件不属于当前Session的候选事件")
        event_start = str(selected["interruption_start_bdt"])
        event_end = str(selected["interruption_end_bdt"])
        root_evidence = state.get("evidence", [])
        root_evidence_ids = (
            [root_evidence[-1]["evidence_id"]] if root_evidence else []
        )
        return {
            "selected_event_id": event_id,
            "start_time": event_start,
            "end_time": event_end,
            "fault_time": event_start,
            "interruption_start_bdt": event_start,
            "interruption_end_bdt": event_end,
            "affected_objects": list(selected.get("satellites") or []),
            "pattern": str(selected.get("pattern") or ""),
            "current_tree_node_id": tree_definition.root.next,
            "status": "running",
            "model_profile": (
                str(selection.get("model_profile", ""))
                if isinstance(selection, dict)
                else state.get("model_profile", "")
            ),
            "traversal": _append_step(
                state,
                node_id=tree_definition.root.node_id,
                node_type="classification",
                decision="selected_interruption_event",
                evidence_ids=root_evidence_ids,
                next_node_id=tree_definition.root.next,
            ),
        }

    def execute_tree_node(state: SBCTroubleshootingState) -> dict[str, Any]:
        node_id = state.get("current_tree_node_id", "")
        if node_id in conclusions:
            return {
                "conclusion_nodes": [*state.get("conclusion_nodes", []), node_id],
                "traversal": _append_step(
                    state,
                    node_id=node_id,
                    node_type="conclusion",
                    decision=conclusions[node_id],
                    evidence_ids=[],
                    next_node_id=None,
                ),
                "status": "completed",
            }
        node = tree_nodes.get(node_id)
        if node is None:
            return {
                "status": "incomplete",
                "incomplete_reason": f"故障树节点未配置：{node_id}",
            }
        if node.node_type in {"routing", "boundary"}:
            if node.direct_next:
                next_node_id = node.direct_next
                decision = node.label
            else:
                selector = node.selector or ""
                selector_value = str(state.get(selector, ""))
                next_node_id = node.routes.get(selector_value)
                decision = selector_value
                if not next_node_id:
                    return {
                        "status": "incomplete",
                        "incomplete_reason": (
                            f"{node_id} 的路由值 {selector_value!r} 未配置"
                        ),
                    }
            node_type = "boundary" if node.node_type == "boundary" else "classification"
            update: dict[str, Any] = {
                "current_tree_node_id": next_node_id,
                "traversal": _append_step(
                    state,
                    node_id=node_id,
                    node_type=node_type,
                    decision=decision,
                    evidence_ids=[],
                    next_node_id=next_node_id,
                ),
            }
            if node.node_type == "boundary":
                update["boundary_nodes"] = [
                    *state.get("boundary_nodes", []),
                    node_id,
                ]
            return update

        evidence = list(state.get("evidence", []))
        new_evidence_ids: list[str] = []
        common_arguments = {
            "tree_node_id": node_id,
            "start_time": state["start_time"],
            "end_time": state["end_time"],
            "source_sat": state.get("source_sat", ""),
            "target_station": state.get("target_station", ""),
            "observation_bdt": state.get("fault_time", ""),
            "interruption_start_bdt": state.get("interruption_start_bdt", ""),
            "interruption_end_bdt": state.get("interruption_end_bdt", ""),
            "affected_objects": state.get("affected_objects", []),
            "selected_event_id": state.get("selected_event_id", ""),
        }
        for tool_name in node.allowed_tools:
            arguments = {
                **common_arguments,
                **state.get("tool_arguments", {}).get(tool_name, {}),
            }
            result = tool_registry.dispatch(tool_name, arguments)
            item = build_evidence(
                sequence=len(evidence) + 1,
                node_id=node_id,
                tool_name=tool_name,
                arguments=arguments,
                result=result,
            )
            evidence.append(item)
            new_evidence_ids.append(item["evidence_id"])
            if item["status"] != "valid":
                return {
                    "evidence": evidence,
                    "traversal": _append_step(
                        state,
                        node_id=node_id,
                        node_type="breakpoint",
                        decision=f"incomplete:{item['status']}",
                        evidence_ids=new_evidence_ids,
                        next_node_id=None,
                    ),
                    "status": "incomplete",
                    "incomplete_reason": (
                        f"{node_id} 的 {tool_name} 工具不可用"
                        if item["status"] == "tool_unavailable"
                        else f"{node_id} 的 {tool_name} 未返回有效数据"
                    ),
                }

        valid, reason = validate_required_evidence(node, evidence)
        if not valid:
            return {
                "evidence": evidence,
                "traversal": _append_step(
                    state,
                    node_id=node_id,
                    node_type="breakpoint",
                    decision="incomplete:required_evidence",
                    evidence_ids=new_evidence_ids,
                    next_node_id=None,
                ),
                "status": "incomplete",
                "incomplete_reason": reason,
            }
        outcome = resolve_outcome(node, evidence)
        if outcome is None:
            return {
                "evidence": evidence,
                "pending_llm_judgement": {
                    "tree_node_id": node_id,
                    "label": node.label,
                    "allowed_outcomes": list((node.outcomes or {}).keys()),
                    "evidence_ids": new_evidence_ids,
                    "reason": "工具证据缺少一致且有效的 outcome",
                },
            }
        next_node_id = (node.outcomes or {})[outcome]
        return {
            "evidence": evidence,
            "current_tree_node_id": next_node_id,
            "traversal": _append_step(
                state,
                node_id=node_id,
                node_type="breakpoint",
                decision=outcome,
                evidence_ids=new_evidence_ids,
                next_node_id=next_node_id,
            ),
        }

    def llm_judge(state: SBCTroubleshootingState) -> dict[str, Any]:
        pending = dict(state.get("pending_llm_judgement") or {})
        node_id = str(pending.get("tree_node_id", ""))
        allowed = [str(item) for item in pending.get("allowed_outcomes", [])]
        evidence_ids = [str(item) for item in pending.get("evidence_ids", [])]
        node_evidence = [
            item for item in _compact_evidence(state)
            if str(item.get("evidence_id")) in evidence_ids
        ]
        prompt_payload = {
            "tree_node_id": node_id,
            "question": pending.get("label", ""),
            "allowed_outcomes": allowed,
            "evidence": node_evidence,
        }
        prompt = (
            "你是天基承载网故障树的受约束证据判定器。只能依据给定证据判断，"
            "不得补造数据。outcome必须来自allowed_outcomes；证据不足时将"
            "insufficient_evidence设为true且outcome设为空字符串。只输出JSON对象，字段为"
            "outcome、confidence、evidence_ids、reason、insufficient_evidence。\n"
            + json.dumps(prompt_payload, ensure_ascii=False, default=str)
        )
        calls = int(state.get("model_calls", 0)) + 1
        usage = int((state.get("model_usage") or {}).get("total_tokens", 0))
        try:
            response = call_model(
                [{"role": "user", "content": prompt}],
                profile_name=state.get("model_profile") or None,
                temperature=0,
            )
            text = _model_text(response.get("content"))
            usage += _model_tokens(response, text)
            parsed = _parse_json_object(text)
            outcome = str((parsed or {}).get("outcome", ""))
            insufficient = bool((parsed or {}).get("insufficient_evidence"))
            cited = [str(item) for item in (parsed or {}).get("evidence_ids", [])]
            valid_citations = bool(cited) and set(cited).issubset(set(evidence_ids))
            if insufficient or outcome not in allowed or not valid_citations:
                raise ValueError("模型未返回合法且有证据引用的故障树 outcome")
            node = tree_nodes[node_id]
            judgement = {
                **(parsed or {}),
                "tree_node_id": node_id,
                "model_profile": state.get("model_profile", ""),
            }
            return {
                "model_calls": calls,
                "model_usage": {"total_tokens": usage},
                "llm_judgements": [*state.get("llm_judgements", []), judgement],
                "pending_llm_judgement": {},
                "current_tree_node_id": (node.outcomes or {})[outcome],
                "traversal": _append_step(
                    state,
                    node_id=node_id,
                    node_type="breakpoint",
                    decision=outcome,
                    evidence_ids=cited,
                    next_node_id=(node.outcomes or {})[outcome],
                ),
            }
        except Exception as exc:
            return {
                "model_calls": calls,
                "model_usage": {"total_tokens": usage},
                "pending_llm_judgement": {},
                "traversal": _append_step(
                    state,
                    node_id=node_id,
                    node_type="breakpoint",
                    decision="incomplete:llm_judge",
                    evidence_ids=evidence_ids,
                    next_node_id=None,
                ),
                "status": "incomplete",
                "incomplete_reason": f"{node_id} 的模型辅助判据失败：{exc}",
                "llm_error": str(exc),
            }

    def build_result(state: SBCTroubleshootingState) -> dict[str, Any]:
        conclusion_items = [
            {
                "node_id": node_id,
                "summary": conclusions[node_id],
                "evidence_ids": [
                    item["evidence_id"]
                    for item in state.get("evidence", [])
                    if item["status"] == "valid"
                ],
            }
            for node_id in state.get("conclusion_nodes", [])
        ]
        return {
            "structured_result": {
                "status": state["status"],
                "fault_window": {
                    "start": state.get("start_time", ""),
                    "end": state.get("end_time", ""),
                },
                "affected_objects": state.get("affected_objects", []),
                "selected_event_id": state.get("selected_event_id", ""),
                "breakpoints": [
                    step
                    for step in state.get("traversal", [])
                    if step["node_type"] == "breakpoint"
                ],
                "boundaries": [
                    {"node_id": node_id} for node_id in state.get("boundary_nodes", [])
                ],
                "conclusions": conclusion_items,
                "current_tree_node_id": state.get("current_tree_node_id", ""),
                "incomplete_reason": state.get("incomplete_reason"),
                "missing_inputs": state.get("missing_inputs", []),
            }
        }

    def llm_explain_result(state: SBCTroubleshootingState) -> dict[str, Any]:
        payload = {
            "structured_result": state.get("structured_result"),
            "traversal": state.get("traversal", []),
            "evidence": _compact_evidence(state),
            "llm_judgements": state.get("llm_judgements", []),
        }
        prompt = (
            "你是天基承载网故障排查结果解释器。请严格依据给定的故障树遍历和证据，"
            "用简洁中文说明结论、实际分支、关键证据、排除项、置信度和下一步建议。"
            "不得改变structured_result中的状态或结论，不得生成不存在的证据；证据不足必须明确说明。\n"
            + json.dumps(payload, ensure_ascii=False, default=str)
        )
        calls = int(state.get("model_calls", 0)) + 1
        usage = int((state.get("model_usage") or {}).get("total_tokens", 0))
        try:
            response = call_model(
                [{"role": "user", "content": prompt}],
                profile_name=state.get("model_profile") or None,
                temperature=0,
            )
            text = _model_text(response.get("content"))
            if not text:
                raise ValueError("模型未返回解释文本")
            usage += _model_tokens(response, text)
            return {
                "model_calls": calls,
                "model_usage": {"total_tokens": usage},
                "llm_explanation": text,
            }
        except Exception as exc:
            return {
                "model_calls": calls,
                "model_usage": {"total_tokens": usage},
                "llm_error": str(exc),
            }

    graph = StateGraph(SBCTroubleshootingState)
    graph.add_node("normalize_input", _normalize_input)
    graph.add_node("validate_scope", _validate_scope)
    graph.add_node("create_time_window", _create_time_window)
    graph.add_node("detect_anomaly", detect_anomaly)
    graph.add_node("discover_interruptions", discover_interruptions)
    graph.add_node("select_event", select_event)
    graph.add_node("execute_tree_node", execute_tree_node)
    graph.add_node("llm_judge", llm_judge)
    graph.add_node("build_result", build_result)
    graph.add_node("llm_explain_result", llm_explain_result)

    graph.add_edge(START, "normalize_input")
    graph.add_edge("normalize_input", "validate_scope")
    graph.add_conditional_edges(
        "validate_scope",
        lambda state: "continue" if state["status"] == "running" else "finish",
        {"continue": "create_time_window", "finish": "build_result"},
    )
    graph.add_conditional_edges(
        "create_time_window",
        lambda state: (
            "discover"
            if state.get("workflow_mode") == "event_selection"
            else "diagnose"
        ),
        {"discover": "discover_interruptions", "diagnose": "detect_anomaly"},
    )
    graph.add_conditional_edges(
        "discover_interruptions",
        lambda state: (
            "select"
            if state["status"] == "awaiting_selection"
            else "finish"
        ),
        {"select": "select_event", "finish": "build_result"},
    )
    graph.add_edge("select_event", "execute_tree_node")
    graph.add_conditional_edges(
        "detect_anomaly",
        lambda state: "continue" if state["status"] == "running" else "finish",
        {"continue": "execute_tree_node", "finish": "build_result"},
    )
    graph.add_conditional_edges(
        "execute_tree_node",
        lambda state: (
            "finish"
            if state["status"] != "running"
            else "llm_judge"
            if state.get("pending_llm_judgement")
            else "continue"
        ),
        {
            "continue": "execute_tree_node",
            "llm_judge": "llm_judge",
            "finish": "build_result",
        },
    )
    graph.add_conditional_edges(
        "llm_judge",
        lambda state: "continue" if state["status"] == "running" else "finish",
        {"continue": "execute_tree_node", "finish": "build_result"},
    )
    graph.add_conditional_edges(
        "build_result",
        lambda state: (
            "explain"
            if state.get("model_profile")
            and (
                state.get("workflow_mode") != "event_selection"
                or state.get("selected_event_id")
            )
            else "finish"
        ),
        {"explain": "llm_explain_result", "finish": END},
    )
    graph.add_edge("llm_explain_result", END)
    return graph.compile(checkpointer=checkpointer)
