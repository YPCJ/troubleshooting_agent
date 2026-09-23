from __future__ import annotations

import unittest

from skills.sbc_troubleshooting_report.scripts.generate_report import build_report


def _document(*, second_status: str = "valid") -> dict:
    return {
        "session_id": "report-test",
        "selected_event": {
            "event_id": "event-1",
            "interruption_start_bdt": "2026-08-25 15:00:00",
            "interruption_end_bdt": "2026-08-25 15:05:00",
            "duration_seconds": 300,
            "pattern": "single_pass",
        },
        "status": "completed" if second_status == "valid" else "incomplete",
        "fault_window": {
            "start": "2026-08-25 14:50:00",
            "end": "2026-08-25 15:10:00",
        },
        "affected_objects": ["A0101"],
        "fault_tree_branch": [
            {
                "tree_node_id": "A",
                "node_type": "classification",
                "decision": "selected_interruption_event",
                "evidence_ids": ["ev-root"],
                "next_node_id": "B",
            },
            {
                "tree_node_id": "B",
                "node_type": "classification",
                "decision": "single_pass",
                "evidence_ids": [],
                "next_node_id": "C1",
            },
            {
                "tree_node_id": "C1",
                "node_type": "classification",
                "decision": "single_pass",
                "evidence_ids": [],
                "next_node_id": "D1",
            },
            {
                "tree_node_id": "D1",
                "node_type": "classification",
                "decision": "定性为节点或链路问题",
                "evidence_ids": [],
                "next_node_id": "E1",
            },
            {
                "tree_node_id": "E1",
                "node_type": "breakpoint",
                "decision": "yes",
                "evidence_ids": ["ev-e1"],
                "next_node_id": "F1",
            },
            {
                "tree_node_id": "F1",
                "node_type": "breakpoint",
                "decision": "yes" if second_status == "valid" else "incomplete:missing_data",
                "evidence_ids": ["ev-f1-a", "ev-f1-b"],
                "next_node_id": "H1" if second_status == "valid" else None,
            },
        ],
        "evidence": [
            {
                "evidence_id": "ev-root",
                "tree_node_id": "A",
                "tool_name": "keep_alive_query",
                "query_args": {},
                "result": {"outcome": "single_pass", "data": [{"id": 1}]},
                "status": "valid",
            },
            {
                "evidence_id": "ev-e1",
                "tree_node_id": "E1",
                "tool_name": "topology_query",
                "query_args": {},
                "result": {"outcome": "yes", "data": [{"terminal": True}]},
                "status": "valid",
            },
            {
                "evidence_id": "ev-f1-a",
                "tree_node_id": "F1",
                "tool_name": "topology_query",
                "query_args": {},
                "result": {"outcome": "yes", "data": [{"connected": True}]},
                "status": "valid",
            },
            {
                "evidence_id": "ev-f1-b",
                "tree_node_id": "F1",
                "tool_name": "packetin_query",
                "query_args": {},
                "result": {"outcome": "yes", "data": []},
                "status": second_status,
            },
        ],
        "boundaries": [],
        "conclusions": [],
        "missing_inputs": [],
        "incomplete_reason": None,
        "generated_at": "2026-08-25T15:10:00+08:00",
    }


class SBCReportTests(unittest.TestCase):
    def test_renders_full_tree_highlights_path_and_links_judges(self) -> None:
        report = build_report(_document())

        self.assertIn("## 2. 完整故障树与实际故障树分支", report)
        self.assertIn("I17[\"定界承载网问题\"]", report)
        self.assertIn("Judge1<br/>破局点：是否为落地网络联通分支末端节点", report)
        self.assertIn("Judge2<br/>通过能落地的邻居卫星拓扑查询", report)
        self.assertIn("class E1,F1 judge;", report)
        self.assertIn("classDef traversed", report)
        self.assertIn("linkStyle", report)
        self.assertIn("实际路径：`A` → `B` → `C1` → `D1` → `E1/Judge1` → `F1/Judge2`", report)
        self.assertIn("### Judge1 · E1", report)
        self.assertIn("### Judge2 · F1", report)
        self.assertIn("#### 证据 `ev-f1-a`", report)
        self.assertIn("#### 证据 `ev-f1-b`", report)
        self.assertIn("逻辑接入源：卫星基础信息（`satellite_basic_info`）", report)
        self.assertIn("星地拓扑数据（`ground_link_topology`）", report)
        self.assertIn("PacketIn消息（`packetin_message`）", report)
        self.assertIn("辅助/增量数据源：onboard_routing_table_snapshot（仿真增量观测表）", report)
        self.assertIn("逻辑接入源：保活时间统计（`keepalive_statistics`）", report)
        self.assertNotIn("Judge3", report)

    def test_incomplete_or_missing_evidence_does_not_create_judge(self) -> None:
        report = build_report(_document(second_status="missing_data"))

        self.assertIn("### Judge1 · E1", report)
        self.assertNotIn("Judge2", report)
        self.assertIn("### ev-f1-a · F1", report)
        self.assertIn("### ev-f1-b · F1", report)
        self.assertIn("证据状态：`missing_data`", report)


if __name__ == "__main__":
    unittest.main()
