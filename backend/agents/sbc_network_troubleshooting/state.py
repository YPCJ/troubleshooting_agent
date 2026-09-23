from __future__ import annotations

from typing import Any, Literal, TypedDict


EvidenceStatus = Literal[
    "valid",
    "missing_data",
    "tool_unavailable",
    "conflict",
    "policy_violation",
]
RunStatus = Literal[
    "running",
    "awaiting_selection",
    "completed",
    "incomplete",
    "no_anomaly",
    "out_of_scope",
]


class Evidence(TypedDict):
    evidence_id: str
    tree_node_id: str
    tool_name: str
    query_args: dict[str, Any]
    result: dict[str, Any]
    status: EvidenceStatus


class TraversalStep(TypedDict):
    tree_node_id: str
    node_type: Literal["classification", "breakpoint", "boundary", "conclusion"]
    decision: str
    evidence_ids: list[str]
    next_node_id: str | None


class SBCTroubleshootingState(TypedDict, total=False):
    session_id: str
    workflow_mode: str
    user_query: str
    fault_time: str
    start_time: str
    end_time: str
    source_sat: str
    target_station: str
    affected_objects: list[str]
    candidate_events: list[dict[str, Any]]
    selected_event_id: str
    interruption_start_bdt: str
    interruption_end_bdt: str
    normalized_symptom: str
    pattern: str
    current_tree_node_id: str
    traversal: list[TraversalStep]
    evidence: list[Evidence]
    boundary_nodes: list[str]
    conclusion_nodes: list[str]
    status: RunStatus
    missing_inputs: list[str]
    incomplete_reason: str | None
    report_requested: bool
    structured_result: dict[str, Any] | None
    tool_arguments: dict[str, dict[str, Any]]
    model_profile: str
    model_calls: int
    model_usage: dict[str, int]
    pending_llm_judgement: dict[str, Any]
    llm_judgements: list[dict[str, Any]]
    llm_explanation: str
    llm_error: str | None


def initial_state(payload: dict[str, Any]) -> SBCTroubleshootingState:
    return {
        "session_id": str(payload.get("session_id", "")),
        "workflow_mode": str(payload.get("workflow_mode", "diagnose")),
        "user_query": str(payload.get("user_query", "")),
        "fault_time": str(payload.get("fault_time", "")),
        "start_time": str(payload.get("start_time", "")),
        "end_time": str(payload.get("end_time", "")),
        "source_sat": str(payload.get("source_sat", "")),
        "target_station": str(payload.get("target_station", "")),
        "affected_objects": [
            str(item) for item in payload.get("affected_objects", []) if str(item).strip()
        ],
        "candidate_events": list(payload.get("candidate_events") or []),
        "selected_event_id": str(payload.get("selected_event_id", "")),
        "interruption_start_bdt": str(payload.get("interruption_start_bdt", "")),
        "interruption_end_bdt": str(payload.get("interruption_end_bdt", "")),
        "normalized_symptom": str(payload.get("normalized_symptom", "")),
        "pattern": str(payload.get("pattern", "")),
        "current_tree_node_id": "",
        "traversal": [],
        "evidence": [],
        "boundary_nodes": [],
        "conclusion_nodes": [],
        "status": "running",
        "missing_inputs": [],
        "incomplete_reason": None,
        "report_requested": bool(payload.get("report_requested", False)),
        "structured_result": None,
        "tool_arguments": dict(payload.get("tool_arguments") or {}),
        "model_profile": str(payload.get("model_profile", "")),
        "model_calls": 0,
        "model_usage": {"total_tokens": 0},
        "pending_llm_judgement": {},
        "llm_judgements": [],
        "llm_explanation": "",
        "llm_error": None,
    }
