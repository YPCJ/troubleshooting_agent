from __future__ import annotations

import unittest
import json
import re
import tempfile
import threading
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch

from llm.providers.gemini_impl import _convert_openai_tools_to_gemini
import tool_boxes
from backend.agents.sbc_network_troubleshooting import (
    SBCNetworkTroubleshootingAgent,
)
from backend.agents.sbc_network_troubleshooting.config import (
    DOMAIN_TOOL_DESCRIPTIONS,
    load_runtime_tree,
)
from backend.agents.sbc_network_troubleshooting.mermaid_renderer import render_mermaid
from backend.agents.sbc_network_troubleshooting.service import (
    SBCNetworkTroubleshootingAgentService,
)
from backend.agents.sbc_network_troubleshooting.tools import SBCDomainToolRegistry
from backend.fault_diagnoses_agent import ServiceCatalog


class RecordingHandlers:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def handler(self, name: str, outcomes: dict[str, str] | None = None):
        def run(arguments: Mapping[str, Any]) -> dict[str, Any]:
            copied = dict(arguments)
            self.calls.append((name, copied))
            node_id = str(copied.get("tree_node_id", ""))
            outcome = (outcomes or {}).get(node_id)
            result: dict[str, Any] = {"status": "ok", "data": [{"value": 1}]}
            if outcome:
                result["outcome"] = outcome
            if name == "keep_alive_query":
                result.update(
                    anomaly=True,
                    affected_objects=["SAT-A"],
                    pattern=outcome or "single_pass",
                )
            return result

        return run


class SBCNetworkTroubleshootingAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.graph_model = patch(
            "backend.agents.sbc_network_troubleshooting.graph.chat_reply",
            return_value={
                "content": "模型仅依据故障树路径和查询证据给出辅助说明。",
                "usage": {"total_tokens": 32},
            },
        )
        self.graph_model_mock = self.graph_model.start()
        self.addCleanup(self.graph_model.stop)

    def test_event_discovery_interrupts_and_resumes_selected_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_path = str(Path(temp_dir) / "checkpoints.sqlite3")
            service = SBCNetworkTroubleshootingAgentService(
                checkpoint_path=checkpoint_path,
                report_output_root=Path(temp_dir) / "outputs",
            )
            self.addCleanup(service.close)

            discovered = service.run_turn(
                [
                    {
                        "role": "user",
                        "content": "查一下2026年8月8日的无连接中断情况，并排查",
                    }
                ],
                session_id="event-selection",
            )

            self.assertEqual("awaiting_selection", discovered["status"])
            candidates = discovered["selection_request"]["candidates"]
            self.assertEqual(6, len(candidates))
            self.assertEqual(
                len(candidates),
                len({item["event_id"] for item in candidates}),
            )
            self.assertEqual(
                1,
                len(
                    [
                        item for item in candidates
                        if item["interruption_start_bdt"].startswith(
                            "2026-08-08 17:20:00"
                        )
                    ]
                ),
            )
            self.assertEqual(
                1,
                len(
                    [
                        item for item in candidates
                        if item["interruption_start_bdt"].startswith(
                            "2026-08-08 18:00:00"
                        )
                    ]
                ),
            )
            selected_id = candidates[0]["event_id"]
            traces: list[str] = []
            resumed = service.run_turn(
                [{"role": "user", "content": selected_id}],
                session_id="event-selection",
                selected_event_id=selected_id,
                on_trace=traces.append,
            )

            self.assertEqual("completed", resumed["status"])
            self.assertEqual(1, resumed["model_calls"])
            self.assertEqual(32, resumed["usage"]["total_tokens"])
            self.assertIn("当前对话轮次内第 1 次模型调用", "\n".join(traces))
            self.assertIn(
                "模型辅助分析",
                resumed["assistant_messages"][0]["content"],
            )
            self.assertEqual(
                selected_id,
                resumed["structured_result"]["selected_event_id"],
            )
            self.assertIsNone(service.pending_selection("event-selection"))
            self.assertEqual(2, len(resumed["artifacts"]))
            diagnosis_path = Path(resumed["artifacts"][0]["path"])
            report_path = Path(resumed["artifacts"][1]["path"])
            diagnosis = json.loads(diagnosis_path.read_text(encoding="utf-8"))
            report = report_path.read_text(encoding="utf-8")
            self.assertEqual(selected_id, diagnosis["selected_event"]["event_id"])
            self.assertTrue(diagnosis["llm_explanation"])
            branch_ids = [
                step["tree_node_id"]
                for step in diagnosis["fault_tree_branch"]
            ]
            self.assertEqual("A", branch_ids[0])
            self.assertEqual(
                resumed["structured_result"]["conclusions"][0]["node_id"],
                branch_ids[-1],
            )
            self.assertTrue(
                all(step["label"] for step in diagnosis["fault_tree_branch"]),
            )
            self.assertIn("实际故障树分支", report)
            self.assertIn("keep_alive_query", report)
            self.assertIn("初步结论", report)
            self.assertIn("模型辅助分析", report)
            self.assertEqual(
                "sbc_troubleshooting_report",
                resumed["records"][-1]["source_name"],
            )

    def test_llm_judge_is_used_only_when_valid_evidence_has_no_unique_outcome(self) -> None:
        handlers = RecordingHandlers()
        registry = SBCDomainToolRegistry(
            {
                "keep_alive_query": handlers.handler(
                    "keep_alive_query", {"A": "single_pass"}
                ),
                "topology_query": handlers.handler("topology_query"),
            }
        )
        responses = iter(
            [
                {
                    "content": json.dumps(
                        {
                            "outcome": "no",
                            "confidence": 0.8,
                            "evidence_ids": ["ev-0002"],
                            "reason": "查询结果显示目标不是落地路由树末端节点",
                            "insufficient_evidence": False,
                        },
                        ensure_ascii=False,
                    ),
                    "usage": {"total_tokens": 20},
                },
                {
                    "content": "故障树已依据 ev-0002 定界到承载网问题。",
                    "usage": {"total_tokens": 10},
                },
            ]
        )
        model_caller = lambda *_args, **_kwargs: next(responses)
        result = SBCNetworkTroubleshootingAgent(
            registry,
            model_caller=model_caller,
        ).invoke(
            {
                "session_id": "llm-judge",
                "user_query": "排查 SAT-A 在2026-08-08 18:00:00的无连接中断",
                "model_profile": "test-model",
            }
        )

        self.assertEqual("completed", result["status"])
        self.assertEqual(2, result["model_calls"])
        self.assertEqual(30, result["model_usage"]["total_tokens"])
        self.assertEqual("no", result["llm_judgements"][0]["outcome"])
        self.assertEqual("H3", result["conclusion_nodes"][0])

    def test_event_selection_checkpoint_survives_service_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_path = str(Path(temp_dir) / "checkpoints.sqlite3")
            first = SBCNetworkTroubleshootingAgentService(
                checkpoint_path=checkpoint_path,
                report_output_root=Path(temp_dir) / "outputs",
            )
            discovered = first.run_turn(
                [{"role": "user", "content": "排查2026-08-08无连接中断情况"}],
                session_id="persistent-selection",
            )
            selected_id = discovered["selection_request"]["candidates"][0][
                "event_id"
            ]
            first.close()

            second = SBCNetworkTroubleshootingAgentService(
                checkpoint_path=checkpoint_path,
                report_output_root=Path(temp_dir) / "outputs",
            )
            self.addCleanup(second.close)
            self.assertIsNotNone(
                second.pending_selection("persistent-selection"),
            )
            resumed = second.run_turn(
                [{"role": "user", "content": selected_id}],
                session_id="persistent-selection",
                selected_event_id=selected_id,
            )
            self.assertEqual("completed", resumed["status"])

    def test_keepalive_wording_routes_to_deterministic_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = SBCNetworkTroubleshootingAgentService(
                checkpoint_path=str(Path(temp_dir) / "checkpoints.sqlite3"),
                report_output_root=Path(temp_dir) / "outputs",
            )
            self.addCleanup(service.close)

            with patch(
                "backend.fault_diagnoses_agent.chat_reply",
                side_effect=AssertionError("discovery must not call the model"),
            ):
                discovered = service.run_turn(
                    [
                        {
                            "role": "user",
                            "content": (
                                "请查一下天基承载网在2026年8月8日期间的保活中断有哪些，"
                                "让我选择一个具体排查"
                            ),
                        }
                    ],
                    session_id="keepalive-wording",
                )

            self.assertEqual("awaiting_selection", discovered["status"])
            self.assertEqual(0, discovered["model_calls"])
            self.assertEqual(6, len(discovered["selection_request"]["candidates"]))

    def test_chat_reply_ordinal_selects_matching_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = SBCNetworkTroubleshootingAgentService(
                checkpoint_path=str(Path(temp_dir) / "checkpoints.sqlite3"),
                report_output_root=Path(temp_dir) / "outputs",
            )
            self.addCleanup(service.close)
            discovered = service.run_turn(
                [{"role": "user", "content": "排查2026-08-08无连接中断情况"}],
                session_id="ordinal-selection",
            )
            expected_id = discovered["selection_request"]["candidates"][4]["event_id"]

            with patch(
                "backend.fault_diagnoses_agent.chat_reply",
                side_effect=AssertionError("selection must not call the model"),
            ):
                resumed = service.run_turn(
                    [{"role": "user", "content": "排查一下5. 多星批量中断"}],
                    session_id="ordinal-selection",
                )

            self.assertEqual("completed", resumed["status"])
            self.assertEqual(
                expected_id,
                resumed["structured_result"]["selected_event_id"],
            )
            self.assertIsNone(service.pending_selection("ordinal-selection"))

    def test_non_network_interruption_query_stays_on_general_path(self) -> None:
        from backend.agents.sbc_network_troubleshooting.service import (
            _is_interruption_discovery_query,
        )

        for query in (
            "排查2026-08-08蓄电池放电中断问题",
            "2026-08-08 姿控数据中断，请排查原因",
            "2026-08-08 卫星01 载荷数传中断情况说明",
        ):
            self.assertFalse(
                _is_interruption_discovery_query(query),
                f"{query} 不应触发承载网保活中断发现流程",
            )

        for query in (
            "请查一下天基承载网在2026年8月8日期间的保活中断有哪些，让我选择一个具体排查",
            "排查2026-08-08无连接中断情况",
        ):
            self.assertTrue(
                _is_interruption_discovery_query(query),
                f"{query} 应触发承载网保活中断发现流程",
            )

    def test_reply_containing_a_date_is_never_read_as_an_ordinal(self) -> None:
        from backend.agents.sbc_network_troubleshooting.service import (
            _resolve_event_choice,
        )

        candidates = [{"event_id": f"E{index}"} for index in range(1, 7)]
        for query in (
            "帮我看看2026-08-05那天的中断",
            "再看看2026-08-05的无连接中断",
            "分析2026年8月5日的保活中断原因",
            "换成2026-09-05再查一下中断",
        ):
            self.assertIsNone(
                _resolve_event_choice(query, candidates),
                f"{query} 中的日期数字不能当作事件序号",
            )

        self.assertEqual("E5", _resolve_event_choice("排查一下5. 多星批量中断", candidates))
        self.assertEqual("E2", _resolve_event_choice("选第2个", candidates))
        self.assertEqual("E4", _resolve_event_choice("E4", candidates))
        self.assertIsNone(_resolve_event_choice("这个看起来有点复杂", candidates))

    def test_ambiguous_reply_keeps_waiting_for_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = SBCNetworkTroubleshootingAgentService(
                checkpoint_path=str(Path(temp_dir) / "checkpoints.sqlite3"),
                report_output_root=Path(temp_dir) / "outputs",
            )
            self.addCleanup(service.close)
            service.run_turn(
                [{"role": "user", "content": "排查2026-08-08无连接中断情况"}],
                session_id="ambiguous-selection",
            )

            replied = service.run_turn(
                [{"role": "user", "content": "这个看起来有点复杂"}],
                session_id="ambiguous-selection",
            )

            self.assertEqual("awaiting_selection", replied["status"])
            self.assertIn("未能从你的回复中唯一确定事件", replied["assistant_messages"][0]["content"])
            self.assertIsNotNone(service.pending_selection("ambiguous-selection"))

    def test_event_selection_is_isolated_by_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = SBCNetworkTroubleshootingAgentService(
                checkpoint_path=str(Path(temp_dir) / "checkpoints.sqlite3"),
                report_output_root=Path(temp_dir) / "outputs",
            )
            self.addCleanup(service.close)
            first = service.run_turn(
                [{"role": "user", "content": "排查2026-8-8无连接中断情况"}],
                session_id="selection-a",
            )
            service.run_turn(
                [{"role": "user", "content": "排查2026-08-08无连接中断情况"}],
                session_id="selection-b",
            )
            selected_id = first["selection_request"]["candidates"][0]["event_id"]

            service.run_turn(
                [{"role": "user", "content": selected_id}],
                session_id="selection-a",
                selected_event_id=selected_id,
            )

            self.assertIsNone(service.pending_selection("selection-a"))
            self.assertIsNotNone(service.pending_selection("selection-b"))

    def test_invalid_event_selection_does_not_resume_graph(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = SBCNetworkTroubleshootingAgentService(
                checkpoint_path=str(Path(temp_dir) / "checkpoints.sqlite3"),
                report_output_root=Path(temp_dir) / "outputs",
            )
            self.addCleanup(service.close)
            service.run_turn(
                [{"role": "user", "content": "排查2026-08-08无连接中断情况"}],
                session_id="invalid-selection",
            )

            with self.assertRaisesRegex(ValueError, "不属于当前Session"):
                service.run_turn(
                    [{"role": "user", "content": "INT-INVALID"}],
                    session_id="invalid-selection",
                    selected_event_id="INT-INVALID",
                )

            self.assertIsNotNone(service.pending_selection("invalid-selection"))

    def test_gemini_tool_conversion_removes_unsupported_additional_properties(
        self,
    ) -> None:
        declarations = _convert_openai_tools_to_gemini(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "query",
                        "description": "Query data",
                        "parameters": {
                            "type": "object",
                            "additionalProperties": True,
                            "properties": {
                                "filters": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {"name": {"type": "string"}},
                                }
                            },
                        },
                    },
                }
            ]
        )

        parameters = declarations[0]["parameters"]
        self.assertNotIn("additionalProperties", parameters)
        self.assertNotIn(
            "additionalProperties",
            parameters["properties"]["filters"],
        )
        self.assertEqual(
            {"type": "string"},
            parameters["properties"]["filters"]["properties"]["name"],
        )

    def test_rejects_out_of_scope_request_without_calling_tools(self) -> None:
        recorder = RecordingHandlers()
        registry = SBCDomainToolRegistry(
            {"keep_alive_query": recorder.handler("keep_alive_query")}
        )

        result = SBCNetworkTroubleshootingAgent(registry).invoke(
            {
                "session_id": "out-of-scope",
                "user_query": "排查数据库在2026-08-25 15:00的慢查询",
            }
        )

        self.assertEqual("out_of_scope", result["status"])
        self.assertEqual([], recorder.calls)
        self.assertEqual("out_of_scope", result["structured_result"]["status"])

    def test_builds_default_twenty_minute_window_and_surfaces_missing_tool(self) -> None:
        result = SBCNetworkTroubleshootingAgent().invoke(
            {
                "session_id": "missing-tool",
                "user_query": "排查卫星 A0504 在2026-08-25 15:00的天基承载网中断",
            }
        )

        self.assertEqual("2026-08-25 14:50:00", result["start_time"])
        self.assertEqual("2026-08-25 15:10:00", result["end_time"])
        self.assertEqual("incomplete", result["status"])
        self.assertIn("keep_alive_query 工具不可用", result["incomplete_reason"])
        self.assertEqual("tool_unavailable", result["evidence"][0]["status"])
        self.assertEqual(["A0504"], result["affected_objects"])

    def test_executes_a_complete_constrained_tree_path(self) -> None:
        recorder = RecordingHandlers()
        registry = SBCDomainToolRegistry(
            {
                "keep_alive_query": recorder.handler(
                    "keep_alive_query", {"": "single_pass"}
                ),
                "topology_query": recorder.handler(
                    "topology_query", {"E1": "yes", "F1": "yes"}
                ),
                "packetin_query": recorder.handler(
                    "packetin_query", {"F1": "yes"}
                ),
                "SBC_telemetry_query": recorder.handler(
                    "SBC_telemetry_query", {"I1": "locked"}
                ),
                "laser_link_query": recorder.handler(
                    "laser_link_query", {"I1": "locked"}
                ),
            }
        )

        result = SBCNetworkTroubleshootingAgent(registry).invoke(
            {
                "session_id": "complete-path",
                "user_query": "排查卫星 SAT-A 在2026-08-25 15:00的天基承载网中断",
            }
        )

        self.assertEqual("completed", result["status"])
        self.assertEqual(["K1"], result["conclusion_nodes"])
        self.assertEqual(
            ["A", "B", "C1", "D1", "E1", "F1", "H1", "I1", "J1", "K1"],
            [step["tree_node_id"] for step in result["traversal"]],
        )
        self.assertEqual(
            "星内承载网载荷异常（例如咬狗、复位、重启等）",
            result["structured_result"]["conclusions"][0]["summary"],
        )

    def test_requires_landing_table_and_feeder_link_pair(self) -> None:
        recorder = RecordingHandlers()
        registry = SBCDomainToolRegistry(
            {
                "keep_alive_query": recorder.handler(
                    "keep_alive_query", {"": "fixed_landing_sat"}
                ),
                "landing_table_query": recorder.handler(
                    "landing_table_query", {"E3": "responded"}
                ),
            }
        )

        result = SBCNetworkTroubleshootingAgent(registry).invoke(
            {
                "session_id": "paired-evidence",
                "user_query": "固定落地卫星 SAT-A 在2026-08-25 15:00无法落地",
            }
        )

        self.assertEqual("incomplete", result["status"])
        self.assertIn("feeder_link_query 工具不可用", result["incomplete_reason"])
        self.assertEqual(
            ["landing_table_query", "feeder_link_query"],
            [
                item["tool_name"]
                for item in result["evidence"]
                if item["tree_node_id"] == "E3"
            ],
        )
        self.assertEqual("E3", result["traversal"][-1]["tree_node_id"])
        self.assertTrue(
            result["traversal"][-1]["decision"].startswith("incomplete:"),
        )

    def test_tree_configuration_has_no_dangling_edges_or_unknown_tools(self) -> None:
        definition = load_runtime_tree()
        known_nodes = set(definition.nodes)
        for node_id, node in definition.nodes.items():
            targets = definition.targets(node)
            self.assertTrue(targets <= known_nodes, f"{node_id} has dangling edge")
            self.assertTrue(
                set(node.allowed_tools) <= set(DOMAIN_TOOL_DESCRIPTIONS),
                f"{node_id} allows an unknown tool",
            )

    def test_generated_mermaid_preserves_original_tree_nodes_and_edges(self) -> None:
        skill_dir = (
            Path(__file__).resolve().parents[2]
            / "skills"
            / "sbc_network_troubleshooting"
        )
        backup = (skill_dir / "skill_backup.md").read_text(encoding="utf-8")
        rendered = render_mermaid(load_runtime_tree())

        def mermaid_block(markdown: str) -> str:
            return re.search(
                r"```mermaid\n(.*?)\n```",
                markdown,
                re.DOTALL,
            ).group(1)

        def nodes(source: str) -> dict[str, str]:
            result: dict[str, str] = {}
            for node_id, _open, label, _close in re.findall(
                r"\b([A-Z]\d*)\s*(\[|\{)\"?(.+?)\"?(\]|\})",
                source,
            ):
                result[node_id] = label.rstrip('"')
            return result

        def edges(source: str) -> set[tuple[str, str, str]]:
            result: set[tuple[str, str, str]] = set()
            for line in source.splitlines():
                match = re.match(
                    r"\s*([A-Z]\d*)(?:\[.*\]|\{.*\})?\s*-->"
                    r"(?:\s*\|([^|]+)\|\s*)?([A-Z]\d*)",
                    line,
                )
                if match:
                    result.add(
                        (
                            match.group(1),
                            match.group(3),
                            (match.group(2) or "").strip(),
                        )
                    )
            return result

        original_graph = mermaid_block(backup)
        expected_nodes = nodes(original_graph)
        expected_nodes["A"] = "通过保活时间统计识别XX时间内存在中断异常"
        for removed in ("H9", "H10", "H11", "I8", "I9", "I10"):
            expected_nodes.pop(removed)
        expected_nodes["F6"] = "结论：需根据抓包结果具体排查"
        expected_nodes["H2"] = "倒排：通过延时遥测判断落地卫星表是否收到（无延时遥测按否处理）"
        expected_nodes["I3"] = "记录邻居卫星扩散响应计数未获取并继续定界"
        self.assertEqual(expected_nodes, nodes(rendered))
        removed = {"H9", "H10", "H11", "I8", "I9", "I10"}
        expected_edges = {
            edge for edge in edges(original_graph)
            if edge[0] != "F6" and edge[0] not in removed and edge[1] not in removed
        }
        self.assertEqual(expected_edges, edges(rendered))

    def test_agent_reloads_skill_tree_before_each_turn(self) -> None:
        from backend.agents.sbc_network_troubleshooting import graph as graph_module

        with patch.object(
            graph_module,
            "load_runtime_tree",
            wraps=graph_module.load_runtime_tree,
        ) as loader:
            agent = SBCNetworkTroubleshootingAgent()
            agent.invoke(
                {
                    "session_id": "runtime-reload",
                    "user_query": "排查卫星 SAT-A 在2026-08-25 15:00的承载网中断",
                }
            )

        self.assertEqual(2, loader.call_count)

    def test_service_enforces_todo_then_keepalive_for_network_diagnosis(self) -> None:
        service = SBCNetworkTroubleshootingAgentService()
        self.addCleanup(service.close)
        exposed_tools: list[list[str]] = []
        responses = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "todo-1",
                        "function": {
                            "name": "todo",
                            "arguments": (
                                '{"items":[{"id":"confirm","text":"确认保活中断",'
                                '"status":"in_progress"}]}'
                            ),
                        },
                    }
                ],
            },
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "keepalive-1",
                        "function": {
                            "name": "keep_alive_query",
                            "arguments": (
                                '{"start_time":"2026-08-08 17:50:00",'
                                '"end_time":"2026-08-08 18:10:00",'
                                '"source_sat":"A0504"}'
                            ),
                        },
                    }
                ],
            },
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "todo-2",
                        "function": {
                            "name": "todo",
                            "arguments": (
                                '{"items":[{"id":"confirm","text":"确认保活中断",'
                                '"status":"completed"},{"id":"trace","text":"继续定位链路",'
                                '"status":"in_progress"}]}'
                            ),
                        },
                    }
                ],
            },
            {"content": "已确认保活中断，继续按证据排查。", "tool_calls": []},
        ]

        def fake_chat_reply(_messages, *, tools=None, **_kwargs):
            exposed_tools.append(
                [item["function"]["name"] for item in (tools or [])]
            )
            return responses.pop(0)

        with patch(
            "backend.fault_diagnoses_agent.chat_reply",
            side_effect=fake_chat_reply,
        ):
            result = service.run_turn(
                [
                    {
                        "role": "user",
                        "content": "排查卫星 A0504 在2026-08-08 18:00:00的承载网保活中断并生成报告",
                    }
                ],
                model_profile="test-profile",
            )

        self.assertEqual(["todo"], exposed_tools[0])
        self.assertEqual(["keep_alive_query"], exposed_tools[1])
        self.assertEqual(["todo"], exposed_tools[2])
        self.assertIn("topology_query", exposed_tools[3])
        self.assertEqual("test-profile", result["model_profile"])
        self.assertEqual(
            ["todo", "keep_alive_query", "todo"],
            [record["label"].split("(", 1)[0] for record in result["records"]],
        )
        self.assertIn("已确认保活中断", result["reply_text"])

    def test_service_accepts_broad_non_network_date_range(self) -> None:
        service = SBCNetworkTroubleshootingAgentService()
        self.addCleanup(service.close)
        exposed_tools: list[list[str]] = []
        responses = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "todo-1",
                        "function": {
                            "name": "todo",
                            "arguments": (
                                '{"items":[{"id":"energy","text":"查询能源系统故障",'
                                '"status":"in_progress"}]}'
                            ),
                        },
                    }
                ],
            },
            {"content": "已接受月度范围，将按能源系统证据排查。", "tool_calls": []},
        ]

        def fake_chat_reply(_messages, *, tools=None, **_kwargs):
            exposed_tools.append(
                [item["function"]["name"] for item in (tools or [])]
            )
            return responses.pop(0)

        with patch(
            "backend.fault_diagnoses_agent.chat_reply",
            side_effect=fake_chat_reply,
        ):
            result = service.run_turn(
                [
                    {
                        "role": "user",
                        "content": (
                            "看看01号卫星在2025年10月期间有没有发生能源系统相关的故障，"
                            "如果有，排查原因并生成初步分析报告"
                        ),
                    }
                ]
            )

        self.assertIn("todo", exposed_tools[0])
        self.assertIn("data_query", exposed_tools[0])
        self.assertNotIn("keep_alive_query", exposed_tools[0])
        self.assertNotIn("topology_query", exposed_tools[0])
        self.assertIn("已接受月度范围", result["reply_text"])

    def test_todo_state_is_isolated_between_concurrent_sessions(self) -> None:
        manager = tool_boxes.TodoManager()
        barrier = threading.Barrier(2)
        results: dict[str, str] = {}

        def update_and_render(session_id: str) -> None:
            manager.update(
                [
                    {
                        "id": session_id,
                        "text": f"{session_id} task",
                        "status": "in_progress",
                    }
                ]
            )
            barrier.wait()
            results[session_id] = manager.render()

        threads = [
            threading.Thread(target=update_and_render, args=(session_id,))
            for session_id in ("session-a", "session-b")
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertIn("session-a task", results["session-a"])
        self.assertNotIn("session-b task", results["session-a"])
        self.assertIn("session-b task", results["session-b"])
        self.assertNotIn("session-a task", results["session-b"])

    def test_service_propagates_model_errors_instead_of_returning_simulation(
        self,
    ) -> None:
        service = SBCNetworkTroubleshootingAgentService()
        self.addCleanup(service.close)
        traces: list[str] = []

        with patch(
            "backend.fault_diagnoses_agent.chat_reply",
            side_effect=ValueError("400 INVALID_ARGUMENT"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                r"基座模型调用失败（第 1 次调用）：400 INVALID_ARGUMENT",
            ):
                service.run_turn(
                    [{"role": "user", "content": "排查 A0504 的承载网故障"}],
                    on_trace=traces.append,
                )

        self.assertTrue(
            any("基座模型调用失败" in trace for trace in traces),
        )
        self.assertFalse(
            any("本地模拟" in trace for trace in traces),
        )

    def test_mid_run_model_failure_preserves_completed_tool_work(self) -> None:
        service = SBCNetworkTroubleshootingAgentService()
        self.addCleanup(service.close)
        responses = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "todo-1",
                        "function": {
                            "name": "todo",
                            "arguments": (
                                '{"items":[{"id":"confirm","text":"确认保活中断",'
                                '"status":"in_progress"}]}'
                            ),
                        },
                    }
                ],
            },
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "keepalive-1",
                        "function": {
                            "name": "keep_alive_query",
                            "arguments": (
                                '{"start_time":"2026-08-08 17:50:00",'
                                '"end_time":"2026-08-08 18:10:00",'
                                '"source_sat":"A0504"}'
                            ),
                        },
                    }
                ],
            },
        ]

        def fake_chat_reply(_messages, **_kwargs):
            if responses:
                return responses.pop(0)
            raise RuntimeError(
                "LLM transient failure after 6 attempts: [SSL: UNEXPECTED_EOF_WHILE_READING]"
            )

        with patch(
            "backend.fault_diagnoses_agent.chat_reply",
            side_effect=fake_chat_reply,
        ):
            result = service.run_turn(
                [
                    {
                        "role": "user",
                        "content": (
                            "排查卫星 A0504 在2026-08-08 18:00:00的承载网保活中断"
                        ),
                    }
                ],
            )

        self.assertEqual(
            ["todo", "keep_alive_query"],
            [record["label"].split("(", 1)[0] for record in result["records"]],
        )
        self.assertIn("UNEXPECTED_EOF_WHILE_READING", result["reply_text"])
        self.assertIn("已完成 2 次工具调用", result["reply_text"])

    def test_invalid_todo_update_is_returned_to_model_for_correction(self) -> None:
        service = SBCNetworkTroubleshootingAgentService()
        self.addCleanup(service.close)
        exposed_tools: list[list[str]] = []
        traces: list[str] = []
        responses = [
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "todo-invalid",
                        "function": {
                            "name": "todo",
                            "arguments": (
                                '{"items":['
                                '{"id":"1","text":"查询遥测","status":"in_progress"},'
                                '{"id":"2","text":"分析原因","status":"in_progress"}'
                                "]}"
                            ),
                        },
                    }
                ],
            },
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "todo-corrected",
                        "function": {
                            "name": "todo",
                            "arguments": (
                                '{"items":['
                                '{"id":"1","text":"查询遥测","status":"completed"},'
                                '{"id":"2","text":"分析原因","status":"in_progress"}'
                                "]}"
                            ),
                        },
                    }
                ],
            },
            {"content": "已修正待办状态并继续排查。", "tool_calls": []},
        ]

        def fake_chat_reply(_messages, *, tools=None, **_kwargs):
            exposed_tools.append(
                [item["function"]["name"] for item in (tools or [])]
            )
            return responses.pop(0)

        with patch(
            "backend.fault_diagnoses_agent.chat_reply",
            side_effect=fake_chat_reply,
        ):
            result = service.run_turn(
                [
                    {
                        "role": "user",
                        "content": (
                            "看看01号卫星在2025年10月期间有没有发生能源系统相关的故障，"
                            "如果有，排查原因并生成初步分析报告"
                        ),
                    }
                ],
                on_trace=traces.append,
            )

        self.assertIn("todo", exposed_tools[0])
        self.assertIn("data_query", exposed_tools[0])
        self.assertEqual(["todo"], exposed_tools[1])
        self.assertIn("data_query", exposed_tools[2])
        self.assertEqual(
            ["todo", "todo"],
            [record["label"].split("(", 1)[0] for record in result["records"]],
        )
        self.assertTrue(
            any(
                "Only one task can be in_progress at a time" in trace
                for trace in traces
            )
        )
        self.assertIn("已修正待办状态", result["reply_text"])

    def test_default_domain_handlers_query_simulation_database(self) -> None:
        service = SBCNetworkTroubleshootingAgentService()
        self.addCleanup(service.close)
        result = service.hybrid_registry.dispatch(
            "keep_alive_query",
            {
                "start_time": "2026-08-08 17:50:00",
                "end_time": "2026-08-08 18:10:00",
                "source_sat": "A0504",
            },
        )

        self.assertEqual("ok", result["status"])
        self.assertTrue(result["anomaly"])
        self.assertIn("A0504", result["affected_objects"])

    def test_sbc_telemetry_name_does_not_replace_general_telemetry_skill(self) -> None:
        service = SBCNetworkTroubleshootingAgentService()
        self.addCleanup(service.close)
        names = {item["tool_name"] for item in service.list_tools()}
        self.assertIn("SBC_telemetry_query", names)
        self.assertNotIn("telemetry_query", names)
        self.assertIn("telemetry_query", service.skills.skills)
        self.assertIn(
            "data_query",
            {item["tool_name"] for item in service.general_registry.list_items()},
        )
        result = service.hybrid_registry.dispatch(
            "SBC_telemetry_query",
            {
                "start_time": "2026-08-08 00:00:00",
                "end_time": "2026-08-09 00:00:00",
                "parameter_code": "RTR-CPU",
                "limit": 1,
            },
        )
        self.assertEqual("ok", result["status"])
        self.assertTrue(result["data"])
        self.assertEqual("RTR-CPU", result["data"][0]["parameter_code"])

    def test_domain_handler_returns_visible_error_for_missing_window(self) -> None:
        service = SBCNetworkTroubleshootingAgentService()
        self.addCleanup(service.close)

        result = service.hybrid_registry.dispatch(
            "keep_alive_query",
            {"source_sat": "A0504"},
        )

        self.assertEqual("error", result["status"])
        self.assertIn("start_time and end_time are required", result["error"])

    def test_disabled_required_keepalive_tool_fails_gracefully(self) -> None:
        service = SBCNetworkTroubleshootingAgentService(
            enabled_checker=lambda name: name != "keep_alive_query"
        )
        self.addCleanup(service.close)
        todo_response = {
            "content": "",
            "tool_calls": [
                {
                    "id": "todo-1",
                    "function": {
                        "name": "todo",
                        "arguments": (
                            '{"items":[{"id":"confirm","text":"确认保活中断",'
                            '"status":"in_progress"}]}'
                        ),
                    },
                }
            ],
        }
        with patch(
            "backend.fault_diagnoses_agent.chat_reply",
            return_value=todo_response,
        ):
            result = service.run_turn(
                [
                    {
                        "role": "user",
                        "content": "排查 A0504 的天基承载网保活中断",
                    }
                ]
            )

        self.assertIn("keep_alive_query", result["reply_text"])
        self.assertIn("未注册或已禁用", result["reply_text"])
        self.assertEqual(2, result["model_calls"])

    def test_service_catalog_exposes_sbc_agent_and_domain_tools(self) -> None:
        catalog = ServiceCatalog()
        self.addCleanup(catalog.close)

        self.assertIn(
            "sbc_network_troubleshooting",
            {item["app_id"] for item in catalog.list_apps()},
        )
        sbc_tools = {
            item["tool_name"]
            for item in catalog.list_tools()
            if "sbc_network_troubleshooting" in item["apps"]
        }
        self.assertIn("keep_alive_query", sbc_tools)
        self.assertIn("landing_table_query", sbc_tools)
        self.assertIn("feeder_link_query", sbc_tools)


if __name__ == "__main__":
    unittest.main()
