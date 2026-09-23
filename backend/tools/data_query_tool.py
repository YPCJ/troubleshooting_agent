from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any

import requests

from backend.tool_runtime import ToolSpec
from backend.tools._common import WORKDIR


DATA_URL = os.getenv("DATA_URL", "http://49.233.215.205:5000/api/external-query")


def spec(description: str) -> ToolSpec:
    return ToolSpec(
        name="data_query",
        description=description,
        parameters={
            "type": "object",
            "properties": {
                "sat_id": {"type": "string"},
                "para_name": {"type": "array", "items": {"type": "string"}},
                "start_time": {"type": "string"},
                "end_time": {"type": "string"},
            },
        },
        category="data",
    )


def run(sat_id: str, para_name: list[str], start_time: str, end_time: str) -> dict[str, Any]:
    request_body = {
        "sat_id": sat_id,
        "para_name": para_name,
        "start_time": start_time,
        "end_time": end_time,
    }
    try:
        response = requests.post(DATA_URL, json=request_body, timeout=60)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, list):
            return {"error": "Unexpected response format", "body": result}
        total_points = 0
        preview = []
        for item in result:
            if not isinstance(item, dict):
                continue
            values = item.get("value", [])
            total_points += len(values)
            for point in values[:10]:
                preview.append({"time": point.get("time"), "point_value": point.get("point_value")})
        target_dir = WORKDIR / "skills" / "figure-plot" / "assets"
        target_dir.mkdir(parents=True, exist_ok=True)
        param_slug = _sanitize_filename("_".join(para_name))
        time_slug = _sanitize_filename(f"{start_time}_{end_time}")
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"data_query_{sat_id}_{param_slug}_{time_slug}_{timestamp}.json"
        file_path = target_dir / filename
        file_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "saved_to": str(file_path),
            "sat_id": sat_id,
            "para_name": para_name,
            "start_time": start_time,
            "end_time": end_time,
            "data_points": total_points,
            "preview": preview,
        }
    except Exception as exc:
        return {"error": str(exc)}


def run_raw(sat_id: str, para_name: list[str], start_time: str, end_time: str) -> Any:
    request_body = {
        "sat_id": sat_id,
        "para_name": para_name,
        "start_time": start_time,
        "end_time": end_time,
    }
    try:
        response = requests.post(DATA_URL, json=request_body, timeout=60)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        return {"error": str(exc)}


def _sanitize_filename(text: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_-]+", "_", text or "")
    return sanitized.strip("_")[:140] or "data"

