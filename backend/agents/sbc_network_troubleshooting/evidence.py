from __future__ import annotations

from typing import Any

from backend.agents.sbc_network_troubleshooting.state import Evidence
from backend.agents.sbc_network_troubleshooting.tree_schema import TreeNode


def evidence_status(result: Any) -> str:
    if not isinstance(result, dict):
        return "missing_data"
    error = str(result.get("error", ""))
    if error.startswith("Unknown tool:") or error.startswith("Tool disabled:"):
        return "tool_unavailable"
    if error or result.get("status") in {"missing_data", "error"}:
        return "missing_data"
    if not result or (result.get("data") == [] and not result.get("interruptions")):
        return "missing_data"
    return "valid"


def build_evidence(
    *,
    sequence: int,
    node_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    result: Any,
) -> Evidence:
    normalized_result = result if isinstance(result, dict) else {"data": result}
    return {
        "evidence_id": f"ev-{sequence:04d}",
        "tree_node_id": node_id,
        "tool_name": tool_name,
        "query_args": arguments,
        "result": normalized_result,
        "status": evidence_status(normalized_result),
    }


def validate_required_evidence(
    node: TreeNode,
    evidence: list[Evidence],
) -> tuple[bool, str | None]:
    node_evidence = [item for item in evidence if item["tree_node_id"] == node.node_id]
    valid_tools = {
        item["tool_name"] for item in node_evidence if item["status"] == "valid"
    }
    for group in node.required_evidence_groups:
        missing = [tool_name for tool_name in group if tool_name not in valid_tools]
        if missing:
            return False, f"{node.node_id} 缺少配对证据：{', '.join(missing)}"
    return True, None


def resolve_outcome(node: TreeNode, evidence: list[Evidence]) -> str | None:
    node_evidence = [
        item for item in evidence
        if item["tree_node_id"] == node.node_id and item["status"] == "valid"
    ]
    reported = {
        str(item["result"].get("outcome", "")).strip()
        for item in node_evidence
        if item["result"].get("outcome")
    }
    if len(reported) != 1:
        return None
    outcome = next(iter(reported))
    if not node.outcomes or outcome not in node.outcomes:
        return None
    return outcome
