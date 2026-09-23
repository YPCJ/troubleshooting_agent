"""Shared progress labels for base-model calls."""

from __future__ import annotations

import re


MODEL_CALL_PROGRESS_PATTERN = re.compile(
    r"^(?:##\s*)?(?:这是本次任务中大模型的第\s*|当前对话轮次内第\s*)"
    r"\d+\s*次(?:模型)?调用$"
)


def format_model_call_progress(call_index: int) -> str:
    if call_index < 1:
        raise ValueError("call_index must be at least 1")
    return f"当前对话轮次内第 {call_index} 次模型调用"


def is_model_call_progress(content: str) -> bool:
    return bool(MODEL_CALL_PROGRESS_PATTERN.fullmatch(content.strip()))
