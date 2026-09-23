from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.fault_diagnoses_agent import FaultDiagnosesAgentService


class LoadSkillsSelfCheck(unittest.TestCase):
    def test_load_skills_dispatch_returns_sbc_skill_content(self) -> None:
        service = FaultDiagnosesAgentService()

        output = service.tool_registry.dispatch(
            "load_skills",
            {"name": "sbc_network_troubleshooting"},
        )

        self.assertIn("天基承载网故障排查", str(output))

    def test_run_turn_can_follow_instruction_to_load_skill(self) -> None:
        service = FaultDiagnosesAgentService()
        call_count = {"value": 0}

        def fake_chat_reply(messages, tools=None, profile_name=None):  # type: ignore[no-untyped-def]
            call_count["value"] += 1
            if call_count["value"] == 1:
                tool_names = sorted(
                    tool.get("function", {}).get("name", "")
                    for tool in (tools or [])
                )
                self.assertIn("load_skills", tool_names)
                return {
                    "content": "我先加载相关技能。",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "load_skills",
                                "arguments": '{"name":"sbc_network_troubleshooting"}',
                            },
                        }
                    ],
                    "usage": {"total_tokens": 50},
                }
            return {
                "content": "已加载天基承载网故障排查技能，并可继续处理。",
                "tool_calls": [],
                "usage": {"total_tokens": 30},
            }

        with patch("backend.fault_diagnoses_agent.chat_reply", side_effect=fake_chat_reply):
            result = service.run_turn(
                [{"role": "user", "content": "请加载天基承载网故障排查这个skill并继续"}],
                max_rounds=4,
            )

        labels = [str(item.get("label", "")) for item in (result.get("records") or [])]
        self.assertTrue(any("load_skills" in label for label in labels))
        self.assertIn("已加载天基承载网故障排查技能", str(result.get("reply_text", "")))
        self.assertEqual(2, result["model_calls"])
        self.assertEqual(
            [
                "## 当前对话轮次内第 1 次模型调用",
                "## 当前对话轮次内第 2 次模型调用",
            ],
            [
                line
                for line in result["trace_messages"]
                if line.startswith("## 当前对话轮次内第")
            ],
        )

    def test_run_turn_excludes_trace_messages_from_model_history(self) -> None:
        service = FaultDiagnosesAgentService()
        captured_messages: list[dict[str, str]] = []

        def fake_chat_reply(messages, tools=None, profile_name=None):  # type: ignore[no-untyped-def]
            captured_messages.extend(messages)
            return {
                "content": "继续执行上轮建议。",
                "tool_calls": [],
                "usage": {"total_tokens": 20},
            }

        history = [
            {"role": "user", "kind": "text", "content": "先分析目录结构"},
            {
                "role": "assistant",
                "kind": "log",
                "content": "## 这是本次任务中大模型的第8次调用",
            },
            {
                "role": "assistant",
                "kind": "log",
                "content": "### 模型返回 content length=1220, tool_calls count=0",
            },
            {
                "role": "assistant",
                "kind": "text",
                "content": "建议将脚本放入 skill 的 scripts 目录。",
            },
            {"role": "user", "kind": "text", "content": "可以，这样做吧"},
            {
                "role": "assistant",
                "kind": "text",
                "content": "## 这是本次任务中大模型的第1次调用",
            },
            {
                "role": "assistant",
                "kind": "text",
                "content": "## 当前对话轮次内第 1 次模型调用",
            },
        ]

        with patch("backend.fault_diagnoses_agent.chat_reply", side_effect=fake_chat_reply):
            result = service.run_turn(history, max_rounds=1)

        model_contents = [item["content"] for item in captured_messages]
        self.assertIn("建议将脚本放入 skill 的 scripts 目录。", model_contents)
        self.assertIn("可以，这样做吧", model_contents)
        self.assertFalse(
            any("这是本次任务中大模型的第" in content for content in model_contents)
        )
        self.assertFalse(
            any("模型返回 content length" in content for content in model_contents)
        )
        self.assertEqual(1, model_contents.count("可以，这样做吧"))
        self.assertEqual("继续执行上轮建议。", result["reply_text"])

    def test_model_call_count_restarts_for_each_user_turn(self) -> None:
        service = FaultDiagnosesAgentService()

        def fake_chat_reply(messages, tools=None, profile_name=None):  # type: ignore[no-untyped-def]
            return {
                "content": "本轮完成。",
                "tool_calls": [],
                "usage": {"total_tokens": 10},
            }

        with patch("backend.fault_diagnoses_agent.chat_reply", side_effect=fake_chat_reply):
            first = service.run_turn(
                [{"role": "user", "content": "第一轮"}],
                max_rounds=2,
            )
            second = service.run_turn(
                [
                    {"role": "user", "content": "第一轮"},
                    {"role": "assistant", "content": "本轮完成。"},
                    {"role": "user", "content": "第二轮"},
                ],
                max_rounds=2,
            )

        self.assertEqual(1, first["model_calls"])
        self.assertEqual(1, second["model_calls"])
        self.assertEqual(
            "## 当前对话轮次内第 1 次模型调用",
            first["trace_messages"][0],
        )
        self.assertEqual(
            "## 当前对话轮次内第 1 次模型调用",
            second["trace_messages"][0],
        )


if __name__ == "__main__":
    unittest.main()
