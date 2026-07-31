"""
Compatibility facade for legacy imports.

Prefer importing from `llm` directly:
    from llm import chat_reply, chat_reply_stream, resolve_model_runtime, profile_summary
"""

from llm.factory import chat_reply, chat_reply_stream, profile_summary
from llm.config import resolve_model_runtime

__all__ = [
    "chat_reply",
    "chat_reply_stream",
    "profile_summary",
    "resolve_model_runtime",
]
