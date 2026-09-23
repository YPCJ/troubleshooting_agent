"""SDK compatibility for older standalone agents.

New application code should call :func:`llm.chat_reply` instead. The older
agents still consume the OpenAI SDK response object directly, so this helper
keeps their client construction in the LLM package without changing their
agent loops.
"""

from __future__ import annotations

import os
from typing import Any

from openai import OpenAI


def legacy_openai_client(*, http_client: object | None = None) -> OpenAI:
    options = {"http_client": http_client} if http_client is not None else {}
    return OpenAI(api_key=os.getenv("api_key"), base_url=os.getenv("base_url"), **options)


def legacy_chat_completion(client: OpenAI, **request: Any) -> Any:
    """Return the raw SDK response expected by older standalone agents."""
    return client.chat.completions.create(**request)
