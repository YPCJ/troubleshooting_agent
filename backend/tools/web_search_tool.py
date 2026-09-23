from __future__ import annotations

import os
import re

import requests

from backend.tool_runtime import ToolSpec


WEB_SEARCH_URL = os.getenv("WEB_SEARCH_URL", "https://www.baidu.com/s")


def spec(description: str) -> ToolSpec:
    return ToolSpec(
        name="web_search",
        description=description,
        parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        category="data",
    )


def run(query: str) -> str:
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
            )
        }
        response = requests.get(WEB_SEARCH_URL, params={"wd": query}, headers=headers, timeout=15)
        response.raise_for_status()
        text = response.text
        cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", text)
        cleaned = re.sub(r"(?is)<[^>]+>", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return f"Web search results for '{query}':\n{cleaned[:1500]}"
    except requests.RequestException as exc:
        return f"Error: web search request failed ({exc})"
    except Exception as exc:
        return f"Error: {exc}"

