import json
import os
import ssl
import time
from typing import Any, Iterable, List, Mapping


def _resolve_env_reference(value: str) -> str | None:
    raw = value.strip()
    if not raw:
        return None
    if raw.startswith("${") and raw.endswith("}") and len(raw) > 3:
        return os.getenv(raw[2:-1].strip())
    if raw.startswith("env:") and len(raw) > 4:
        return os.getenv(raw[4:].strip())
    return raw


def _first_env_value(names: Iterable[Any]) -> str | None:
    for name in names:
        value = os.getenv(str(name))
        if value:
            return value
    return None


def _resolve_gemini_base_url(profile: Mapping[str, Any] | None = None) -> str | None:
    profile = profile or {}
    profile_base_url = profile.get("base_url")
    if isinstance(profile_base_url, str):
        resolved = _resolve_env_reference(profile_base_url)
        if resolved:
            return resolved
    env_names = profile.get("base_url_envs")
    if isinstance(env_names, list):
        resolved = _first_env_value(env_names)
        if resolved:
            return resolved
    return os.getenv("GOOGLE_GEMINI_BASE_URL") or os.getenv("GEMINI_BASE_URL")


def _resolve_api_key(profile: Mapping[str, Any] | None = None) -> str:
    profile = profile or {}
    env_names = profile.get("api_key_envs")
    api_key = _first_env_value(env_names) if isinstance(env_names, list) else None
    api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Gemini API key not found. Set GEMINI_API_KEY (recommended) "
            "or GOOGLE_API_KEY in your environment/.env."
        )
    return api_key


def _resolve_model_name(
    model_name: str | None = None,
    profile: Mapping[str, Any] | None = None,
) -> str:
    profile = profile or {}
    return (
        model_name
        or str(profile.get("model") or "").strip()
        or os.getenv("GEMINI_MODEL")
        or os.getenv("gemini_model")
        or os.getenv("model_name")
        or "gemini-1.5-flash"
    )


def get_gemini_model_capabilities(
    model_name: str,
    profile: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Return model-specific generation controls, falling back safely offline."""
    model_id = _resolve_model_name(model_name, profile)
    parameters: dict[str, dict[str, Any]] = {
        "temperature": {"supported": True, "min": 0, "max": 2, "step": 0.1, "default": None},
        "top_p": {"supported": True, "min": 0, "max": 1, "step": 0.05, "default": None},
        "top_k": {"supported": True, "min": 1, "max": None, "step": 1, "default": None},
        "max_output_tokens": {"supported": True, "min": 1, "max": None, "step": 1, "default": None},
    }
    source = "provider"
    thinking_supported = model_id.lower().startswith(("gemini-2.5", "gemini-3"))
    try:
        from google import genai as google_genai
        from google.genai import types as genai_types

        base_url = _resolve_gemini_base_url(profile)
        client = google_genai.Client(
            api_key=_resolve_api_key(profile),
            **({"http_options": genai_types.HttpOptions(base_url=base_url)} if base_url else {}),
        )
        metadata = client.models.get(model=model_id)
        temperature = getattr(metadata, "temperature", None)
        max_temperature = getattr(metadata, "max_temperature", None)
        top_p = getattr(metadata, "top_p", None)
        top_k = getattr(metadata, "top_k", None)
        output_limit = getattr(metadata, "output_token_limit", None)
        thinking_supported = bool(getattr(metadata, "thinking", False)) or thinking_supported
        parameters["temperature"].update(default=temperature, max=max_temperature or 2)
        parameters["top_p"].update(default=top_p)
        if top_k is None:
            parameters["top_k"] = {"supported": False, "default": None}
        else:
            parameters["top_k"].update(default=top_k)
        parameters["max_output_tokens"].update(max=output_limit)
        source = "model_metadata"
    except Exception:
        # Capability discovery must not make the configuration page unusable.
        pass
    return {
        "provider": "gemini",
        "model": model_id,
        "parameters": parameters,
        "exclusive_groups": [["temperature", "top_p"]],
        "defaults_source": source,
        "recommend_provider_defaults": model_id.lower().startswith("gemini-3"),
        "sampling_presets": [] if model_id.lower().startswith("gemini-3") else [
            {"id": "stable", "temperature": 0.2},
            {"id": "flexible", "temperature": 0.8},
        ],
        "verbosity": {"supported": False, "choices": [], "default": None},
        "output": {
            "omission_supported": True,
            "counts_reasoning_tokens": thinking_supported,
            "recommended": None,
        },
    }


def _flatten_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, Mapping):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif "text" in item:
                    parts.append(str(item["text"]))
                else:
                    parts.append(str(item))
            else:
                parts.append(str(item))
        return "\n".join([p for p in parts if p])
    return str(content)


def _messages_to_prompt(messages: Iterable[Mapping[str, Any]]) -> str:
    lines: List[str] = []
    for msg in messages:
        role = str(msg.get("role", "user")).upper()
        content = _flatten_content(msg.get("content"))
        if not content:
            continue
        lines.append(f"[{role}]\n{content}")
    return "\n\n".join(lines).strip()


def _messages_to_gemini_contents(
    messages: List[Mapping[str, Any]],
) -> tuple[str, List[Mapping[str, Any]]]:
    system_parts: List[str] = []
    contents: List[Mapping[str, Any]] = []
    call_names: dict[str, str] = {}

    for message in messages:
        role = str(message.get("role", "user"))
        if role == "system":
            text = _flatten_content(message.get("content"))
            if text:
                system_parts.append(text)
            continue

        if role == "assistant":
            parts: List[Mapping[str, Any]] = []
            text = _flatten_content(message.get("content"))
            if text:
                parts.append({"text": text})
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                name = function.get("name")
                if not name:
                    continue
                try:
                    args = json.loads(function.get("arguments") or "{}")
                except (TypeError, json.JSONDecodeError):
                    args = {}
                call_id = str(call.get("id") or f"call_{len(call_names) + 1}")
                call_names[call_id] = str(name)
                function_call: dict[str, Any] = {
                    "name": str(name),
                    "args": args,
                }
                if call_id:
                    function_call["id"] = call_id
                function_part: dict[str, Any] = {"function_call": function_call}
                if call.get("thought_signature") is not None:
                    function_part["thought_signature"] = call["thought_signature"]
                parts.append(function_part)
            if parts:
                contents.append({"role": "model", "parts": parts})
            continue

        if role == "tool":
            call_id = str(message.get("tool_call_id") or "")
            name = call_names.get(call_id, call_id or "tool")
            raw_result = message.get("content")
            try:
                result = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
            except json.JSONDecodeError:
                result = raw_result
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "function_response": {
                                "name": name,
                                "response": {"result": result},
                            }
                        }
                    ],
                }
            )
            continue

        text = _flatten_content(message.get("content"))
        if text:
            contents.append({"role": "user", "parts": [{"text": text}]})

    return "\n\n".join(system_parts), contents


def _to_sdk_contents(
    contents: List[Mapping[str, Any]], genai_types: Any
) -> List[Any]:
    return [
        genai_types.Content(
            role=str(content["role"]),
            parts=[genai_types.Part(**part) for part in content["parts"]],
        )
        for content in contents
    ]


def _extract_text_from_response(response: Any) -> str:
    candidates = getattr(response, "candidates", None)
    if candidates:
        chunks: List[str] = []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) if content else None
            if not parts:
                continue
            for part in parts:
                p_text = getattr(part, "text", None)
                if p_text:
                    chunks.append(str(p_text))
        if chunks:
            return "\n".join(chunks).strip()

    return ""


def _generate_content_with_retry(client: Any, **kwargs: Any) -> Any:
    try:
        import httpx
    except ImportError:
        httpx = None

    retryable = tuple(
        error
        for error in (
            getattr(httpx, "ConnectError", None) if httpx else None,
            getattr(httpx, "ReadError", None) if httpx else None,
            getattr(httpx, "ReadTimeout", None) if httpx else None,
            getattr(httpx, "RemoteProtocolError", None) if httpx else None,
            getattr(httpx, "WriteError", None) if httpx else None,
            ssl.SSLError,
        )
        if error is not None
    )

    for attempt in range(3):
        try:
            return client.models.generate_content(**kwargs)
        except retryable as exc:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
        except Exception as exc:
            message = str(exc)
            if attempt == 2 or ("EOF" not in message and "UNEXPECTED_EOF_WHILE_READING" not in message):
                raise
            time.sleep(2 ** attempt)


def _extract_tool_calls_from_response(response: Any) -> List[Mapping[str, Any]]:
    tool_calls: List[Mapping[str, Any]] = []

    candidates = getattr(response, "candidates", None)
    if not candidates:
        return tool_calls

    call_idx = 1
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) if content else None
        if not parts:
            continue
        for part in parts:
            fn_call = getattr(part, "function_call", None)
            if not fn_call:
                continue
            name = getattr(fn_call, "name", None)
            args = getattr(fn_call, "args", None)
            if name:
                call_id = getattr(fn_call, "id", None) or f"call_{call_idx}"
                thought_signature = getattr(part, "thought_signature", None)
                call = {
                    "id": str(call_id),
                    "type": "function",
                    "function": {
                        "name": str(name),
                        "arguments": json.dumps(args or {}, ensure_ascii=False),
                    },
                }
                if thought_signature is not None:
                    call["thought_signature"] = thought_signature
                tool_calls.append(call)
                call_idx += 1
    return tool_calls


def _extract_usage_from_response(response: Any) -> dict[str, Any] | None:
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        usage = getattr(response, "usage", None)
    if usage is None:
        return None
    return {
        "prompt_tokens": getattr(usage, "prompt_token_count", None),
        "completion_tokens": getattr(usage, "candidates_token_count", None),
        "total_tokens": getattr(usage, "total_token_count", None),
    }


def _flatten_chunk_text(chunk: Any) -> str:
    if chunk is None:
        return ""
    if isinstance(chunk, str):
        return chunk
    if isinstance(chunk, Mapping):
        return _flatten_content(chunk)
    text = getattr(chunk, "text", None)
    if isinstance(text, str):
        return text
    parts = getattr(chunk, "parts", None)
    if parts:
        texts: List[str] = []
        for part in parts:
            if isinstance(part, Mapping):
                p_text = part.get("text")
            else:
                p_text = getattr(part, "text", None)
            if p_text:
                texts.append(str(p_text))
        if texts:
            return "".join(texts)
    candidates = getattr(chunk, "candidates", None)
    if candidates is not None:
        texts: List[str] = []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            if content is None:
                continue
            parts = getattr(content, "parts", None)
            if parts:
                for part in parts:
                    if isinstance(part, Mapping):
                        p_text = part.get("text")
                    else:
                        p_text = getattr(part, "text", None)
                    if p_text:
                        texts.append(str(p_text))
        if texts:
            return "".join(texts)
    return ""


def _extract_tool_calls_from_chunk(chunk: Any) -> List[Mapping[str, Any]]:
    tool_calls: List[Mapping[str, Any]] = []
    if chunk is None:
        return tool_calls

    def _append_call(fn_call: Any, part_obj: Any = None, call_idx: int = 1):
        name = getattr(fn_call, "name", None)
        if not name:
            return None
        args = getattr(fn_call, "args", None)
        call_id = getattr(fn_call, "id", None) or f"chunk_call_{call_idx}"
        thought_signature = getattr(part_obj, "thought_signature", None) if part_obj is not None else None
        call = {
            "id": str(call_id),
            "type": "function",
            "function": {
                "name": str(name),
                "arguments": json.dumps(args or {}, ensure_ascii=False),
            },
        }
        if thought_signature is not None:
            call["thought_signature"] = thought_signature
        return call

    call_idx = 1
    # Handle top-level function_call or function_calls
    fn_call = getattr(chunk, "function_call", None)
    if fn_call is not None:
        call = _append_call(fn_call, chunk, call_idx)
        if call is not None:
            tool_calls.append(call)
            call_idx += 1
    fn_calls = getattr(chunk, "function_calls", None)
    if fn_calls is not None:
        for fn in fn_calls:
            call = _append_call(fn, chunk, call_idx)
            if call is not None:
                tool_calls.append(call)
                call_idx += 1

    parts = getattr(chunk, "parts", None)
    if parts is not None:
        for part in parts:
            fn_call = getattr(part, "function_call", None)
            if fn_call is None:
                continue
            call = _append_call(fn_call, part, call_idx)
            if call is not None:
                tool_calls.append(call)
                call_idx += 1

    candidates = getattr(chunk, "candidates", None)
    if candidates is not None:
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) if content is not None else None
            if not parts:
                continue
            for part in parts:
                fn_call = getattr(part, "function_call", None)
                if fn_call is None:
                    continue
                call = _append_call(fn_call, part, call_idx)
                if call is not None:
                    tool_calls.append(call)
                    call_idx += 1
    return tool_calls


def _sanitize_gemini_schema(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _sanitize_gemini_schema(item)
            for key, item in value.items()
            if key != "additionalProperties"
        }
    if isinstance(value, list):
        return [_sanitize_gemini_schema(item) for item in value]
    return value


def _convert_openai_tools_to_gemini(tools: Any) -> List[Mapping[str, Any]]:
    """
    Convert OpenAI-style tools to Gemini function_declarations payload.
    """
    if not isinstance(tools, list):
        return []
    declarations: List[Mapping[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, Mapping):
            continue
        if tool.get("type") != "function":
            continue
        fn = tool.get("function")
        if not isinstance(fn, Mapping):
            continue
        name = fn.get("name")
        if not name:
            continue
        declarations.append(
            {
                "name": str(name),
                "description": str(fn.get("description", "")),
                "parameters": _sanitize_gemini_schema(
                    fn.get("parameters") or {"type": "object", "properties": {}}
                ),
            }
        )
    return declarations


def _generate_content_stream_with_retry(client: Any, **kwargs: Any) -> Any:
    try:
        import httpx
    except ImportError:
        httpx = None

    retryable = tuple(
        error
        for error in (
            getattr(httpx, "ConnectError", None) if httpx else None,
            getattr(httpx, "ReadError", None) if httpx else None,
            getattr(httpx, "ReadTimeout", None) if httpx else None,
            getattr(httpx, "RemoteProtocolError", None) if httpx else None,
            getattr(httpx, "WriteError", None) if httpx else None,
            ssl.SSLError,
        )
        if error is not None
    )

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            stream = client.models.generate_content_stream(**kwargs)
            for chunk in stream:
                yield chunk
            return
        except retryable as exc:
            last_error = exc
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
        except Exception as exc:
            last_error = exc
            message = str(exc)
            if attempt == 2 or ("EOF" not in message and "UNEXPECTED_EOF_WHILE_READING" not in message):
                raise
            time.sleep(2 ** attempt)
    if last_error is not None:
        raise last_error


def chat_reply_stream(
    messages: List[Mapping[str, Any]],
    tools: Any = None,
    model_name: str | None = None,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
    profile: Mapping[str, Any] | None = None,
):
    """Stream Gemini output as a sequence of chunk events."""
    prompt = _messages_to_prompt(messages)
    system_instruction, gemini_contents = _messages_to_gemini_contents(messages)
    if not prompt or not gemini_contents:
        yield {"type": "chunk", "content": "", "tool_calls": []}
        yield {"type": "done", "content": "", "tool_calls": []}
        return

    api_key = _resolve_api_key(profile)
    model = _resolve_model_name(model_name, profile)
    declarations = _convert_openai_tools_to_gemini(tools)

    from google import genai as google_genai
    from google.genai import types as genai_types

    config: Mapping[str, Any] = {}
    if temperature is not None:
        config = {**config, "temperature": temperature}
    if max_output_tokens is not None:
        config = {**config, "max_output_tokens": max_output_tokens}
    if top_p is not None:
        config = {**config, "top_p": top_p}
    if top_k is not None:
        config = {**config, "top_k": top_k}
    if system_instruction:
        config = {**config, "system_instruction": system_instruction}
    if declarations:
        config = {
            **config,
            "tools": [{"function_declarations": declarations}],
            "tool_config": {"function_calling_config": {"mode": "AUTO"}},
        }
    base_url = _resolve_gemini_base_url(profile)
    if base_url:
        client = google_genai.Client(
            api_key=api_key,
            http_options=genai_types.HttpOptions(base_url=base_url),
        )
    else:
        client = google_genai.Client(api_key=api_key)
    stream = _generate_content_stream_with_retry(
        client,
        model=model,
        contents=_to_sdk_contents(gemini_contents, genai_types),
        config=config,
    )
    content_buffer = ""
    tool_calls_by_id: dict[str, Mapping[str, Any]] = {}
    for chunk in stream:
        chunk_text = _flatten_chunk_text(chunk)
        if chunk_text:
            content_buffer += chunk_text
        chunk_tool_calls = _extract_tool_calls_from_chunk(chunk)
        for call in chunk_tool_calls:
            tool_calls_by_id[call["id"]] = call
        yield {"type": "chunk", "content": chunk_text, "tool_calls": chunk_tool_calls}
    yield {"type": "done", "content": content_buffer, "tool_calls": list(tool_calls_by_id.values())}


def chat_reply(
    messages: List[Mapping[str, Any]],
    tools: Any = None,
    model_name: str | None = None,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
    profile: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """
    Return OpenAI-style assistant payload:
    {"content": "...", "tool_calls": [...]}
    """
    prompt = _messages_to_prompt(messages)
    system_instruction, gemini_contents = _messages_to_gemini_contents(messages)
    if not prompt or not gemini_contents:
        return {"content": "", "tool_calls": []}

    api_key = _resolve_api_key(profile)
    model = _resolve_model_name(model_name, profile)
    declarations = _convert_openai_tools_to_gemini(tools)

    from google import genai as google_genai
    from google.genai import types as genai_types

    config: Mapping[str, Any] = {}
    if temperature is not None:
        config = {**config, "temperature": temperature}
    if max_output_tokens is not None:
        config = {**config, "max_output_tokens": max_output_tokens}
    if top_p is not None:
        config = {**config, "top_p": top_p}
    if top_k is not None:
        config = {**config, "top_k": top_k}
    if system_instruction:
        config = {**config, "system_instruction": system_instruction}
    if declarations:
        config = {
            **config,
            "tools": [{"function_declarations": declarations}],
            "tool_config": {"function_calling_config": {"mode": "AUTO"}},
        }
    base_url = _resolve_gemini_base_url(profile)
    if base_url:
        client = google_genai.Client(
            api_key=api_key,
            http_options=genai_types.HttpOptions(base_url=base_url),
        )
    else:
        client = google_genai.Client(api_key=api_key)
    response = _generate_content_with_retry(
        client,
        model=model,
        contents=_to_sdk_contents(gemini_contents, genai_types),
        config=config,
    )
    text = _extract_text_from_response(response)
    tool_calls = _extract_tool_calls_from_response(response)
    payload = {"content": text, "tool_calls": tool_calls}
    usage = _extract_usage_from_response(response)
    if usage is not None:
        payload["usage"] = usage
    return payload


def list_gemini_models(profile: Mapping[str, Any] | None = None) -> List[str]:
    api_key = _resolve_api_key(profile)
    base_url = _resolve_gemini_base_url(profile)
    from google import genai as google_genai
    from google.genai import types as genai_types

    if base_url:
        client = google_genai.Client(
            api_key=api_key,
            http_options=genai_types.HttpOptions(base_url=base_url),
        )
    else:
        client = google_genai.Client(api_key=api_key)

    model_ids: List[str] = []
    for item in client.models.list():
        raw_name = getattr(item, "name", None) or getattr(item, "model", None)
        if not isinstance(raw_name, str):
            continue
        name = raw_name.split("/")[-1].strip()
        if name:
            model_ids.append(name)
    return sorted(set(model_ids))
