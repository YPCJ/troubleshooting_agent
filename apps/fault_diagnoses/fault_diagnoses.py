from dotenv import load_dotenv
import argparse
import subprocess
from pathlib import Path
import sys
import os
import json
import re
import yaml
from datetime import datetime
# Ensure project root is importable when running this script directly
# so sibling modules like `tool_boxes.py` can be found.
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = next((p for p in [SCRIPT_DIR, *SCRIPT_DIR.parents] if (p / ".env").exists()), SCRIPT_DIR.parent)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import tool_boxes
import time
import requests
from typing import List, Dict, Any
import shlex

# 加载环境变量，设置时间
now=datetime.now()
# load .env from project root (use PROJECT_ROOT set earlier)
dotenv_path = PROJECT_ROOT/".env"
load_dotenv(override=True, dotenv_path=dotenv_path)

from llm import chat_reply, chat_reply_stream, profile_summary

#print(os.getenv("base_url"))

WORKDIR = PROJECT_ROOT  # 工作目录，始终以项目根目录为工作空间
MODEL_PROFILE = os.getenv("MODEL_PROFILE", "gemini_default")


def _active_model_profile() -> str:
    return os.getenv("MODEL_PROFILE", MODEL_PROFILE)


LLM_PROFILE_MAP = {
    "gemini": "gemini_default",
    "chatgpt": "chatgpt_default",
    "openai": "chatgpt_default",
}


def _resolve_profile_from_llm(llm_name: str | None, fallback_profile: str) -> str:
    if not llm_name:
        return fallback_profile
    profile = LLM_PROFILE_MAP.get(llm_name.strip().lower())
    if not profile:
        raise ValueError(f"Unsupported --llm value: {llm_name}")
    return profile


def _active_model_name_override() -> str | None:
    explicit = os.getenv("MODEL_NAME_OVERRIDE")
    if explicit:
        return explicit
    profile = _active_model_profile().lower()
    if profile.startswith("gemini"):
        return os.getenv("GEMINI_MODEL") or os.getenv("gemini_model")
    if profile.startswith("chatgpt") or profile.startswith("openai"):
        return os.getenv("OPENAI_MODEL")
    return os.getenv("model_name")
Skills_dir = tool_boxes.resolve_skills_dir(__file__, workdir=WORKDIR, project_root=PROJECT_ROOT)
# data_url can be overridden with an environment variable.
data_url = os.getenv("DATA_URL", "http://49.233.215.205:5000/api/external-query")

sample_query_1="请排查01号卫星在2025-10-28 15:00发生的蓄电池故障的原因，请排查01号卫星在2025-10-28 15:00发生的S/C相控阵天线故障的原因，并生成初步分析报告"
sample_query_2="请查询01号卫星在2025-10-26 15:00到2025-10-28 18:00时间段内的“蓄电池A测点1”的数据并且绘制图表"

class SkillLoader:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.skills = {}
        self._load_all()

    def _load_all(self):
        if not self.skills_dir.exists():
            return
        for f in sorted(self.skills_dir.rglob("SKILL.md")):
            text = f.read_text(encoding="utf-8")
            meta, body = self._parse_frontmatter(text)
            name = meta.get("name", f.parent.name)
            self.skills[name] = {"meta": meta, "body": body, "path": str(f)}



    def _parse_frontmatter(self, text: str) -> tuple:
        """Parse YAML frontmatter between --- delimiters."""
        match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not match:
            return {}, text
        try:
            meta = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            meta = {}
        return meta, match.group(2).strip()

    def get_descriptions(self) -> str:
        """Layer 1: short descriptions for the system prompt."""
        if not self.skills:
            return "(no skills available)"
        lines = []
        for name, skill in self.skills.items():
            desc = skill["meta"].get("description", "No description")
            tags = skill["meta"].get("tags", "")
            line = f"  - {name}: {desc}"
            if tags:
                line += f" [{tags}]"
            lines.append(line)
        #print("\n".join(lines))
        return "\n".join(lines)

    def get_content(self, name: str) -> str:
        """Layer 2: full skill body returned in tool_result."""
        skill = self.skills.get(name)
        if not skill:
            return f"Error: Unknown skill '{name}'. Available: {', '.join(self.skills.keys())}"
        #print(f"<skill name=\"{name}\">\n{skill['body']}\n</skill>")

        return f"<skill name=\"{name}\">\n{skill['body']}\n</skill>"

def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def _sanitize_filename(text: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_-]+", "_", text or "")
    return sanitized.strip("_")[:140] or "data"


def _save_data_query_result(result: list, sat_id: str, para_name: list, start_time: str, end_time: str) -> Path:
    target_dir = Skills_dir / "figure-plot" / "assets"
    target_dir.mkdir(parents=True, exist_ok=True)
    param_slug = _sanitize_filename("_".join(para_name) if isinstance(para_name, list) else str(para_name))
    time_slug = _sanitize_filename(f"{start_time}_{end_time}")
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"data_query_{sat_id}_{param_slug}_{time_slug}_{timestamp}.json"
    file_path = target_dir / filename
    file_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return file_path


Skill_loader = SkillLoader(Skills_dir)
TODO = tool_boxes.TodoManager()
SYSTEM = f"""你是一个故障排查专家.工作在{WORKDIR}目录下，现在的时间是{now}.
在处理你不熟悉的任务时使用你的skill技能来解决问题。你在调用函数工具时，会严格按照要求撰写。
可以采用的skill技能包括：
{Skill_loader.get_descriptions()}
"""
print(f"智能体首次运行，其初始提示词为：\n{SYSTEM}\n--------------------")
# Note: Gemini credentials are configured in `ai_gemini.py` via env vars.


def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    shell_operators = ["|", "&&", "||", ";", ">", "<", "`", "$"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    if any(op in command for op in shell_operators):
        return "Error: Shell operators are not allowed in bash tool"
    try:
        if os.name == "nt":
            # Use cmd to support built-in commands on Windows (e.g. dir, copy).
            if not command.strip():
                return "Error: Empty command"
            if command.lstrip().startswith("python "):
                command = "py " + command.lstrip()[7:]
            r = subprocess.run(["cmd", "/c", command], shell=False, cwd=str(WORKDIR),
                               capture_output=True, text=True, timeout=120, encoding="utf-8", errors="ignore")
        else:
            args = shlex.split(command)
            if not args:
                return "Error: Empty command"
            r = subprocess.run(args, shell=False, cwd=str(WORKDIR),
                               capture_output=True, text=True, timeout=120,encoding="utf-8",errors="ignore")
        out = (r.stdout + r.stderr).strip()
        if out:
            if r.returncode != 0:
                return f"Error: Command exited with code {r.returncode}\n{out[:50000]}"
            return out[:50000]
        if r.returncode != 0:
            return f"Error: Command exited with code {r.returncode} and produced no output"
        return "(no output, exit_code=0)"
    except ValueError as e:
        return f"Error: Invalid command syntax: {e}"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"

def run_read(path: str, limit: int = None) -> str:
    try:
        text = safe_path(path).read_text(encoding="utf-8")
        lines = text.splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"

def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content,encoding="utf-8")
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"

def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        content = fp.read_text(encoding="utf-8")
        if old_text not in content:
            return f"Error: Text not found in {path}"
        fp.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"

def run_data_query(sat_id: str, para_name: list, start_time: str, end_time: str) -> dict:
    try:
        print("调用卫星遥测参数查询工具：")
        request_body = {
            "sat_id": sat_id,
            "para_name": para_name,
            "start_time": start_time,
            "end_time": end_time,
        }
        print(request_body)
        response = requests.post(data_url, json=request_body, timeout=60)
        response.raise_for_status()
        result = response.json()

        if not isinstance(result, list):
            return {
                "error": "Unexpected response format",
                "status_code": response.status_code,
                "body": result,
            }

        total_points = 0
        preview = []
        for item in result:
            if not isinstance(item, dict):
                continue
            para_name_str = item.get("para_name")
            print(f"参数: {para_name_str}")
            values = item.get("value", [])
            total_points += len(values)
            for point in values[:10]:
                preview.append({"time": point.get("time"), "point_value": point.get("point_value")})
                print(f"  {point.get('time')}: {point.get('point_value')}")
            if len(values) > 10:
                print(f"  ... ({len(values) - 10} more points)")

        saved_path = _save_data_query_result(result, sat_id, para_name, start_time, end_time)
        print(f"已将完整查询结果保存到: {saved_path}")

        return {
            "saved_to": str(saved_path),
            "sat_id": sat_id,
            "para_name": para_name,
            "start_time": start_time,
            "end_time": end_time,
            "data_points": total_points,
            "preview": preview,
            "message": (
                "完整数据已保存到文件。请使用该JSON文件进行后续绘图或分析。"
            ),
        }

    except requests.RequestException as exc:
        return {"error": f"request failed ({exc})"}
    except ValueError as exc:
        return {"error": f"failed to parse JSON response ({exc})"}
    except Exception as exc:
        return {"error": str(exc)}


def web_search(query: str) -> str:
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
            )
        }
        search_url = os.getenv("WEB_SEARCH_URL", "https://www.baidu.com/s")
        params = {"wd": query}
        response = requests.get(search_url, params=params, headers=headers, timeout=15)
        response.raise_for_status()
        text = response.text
        cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", text)
        cleaned = re.sub(r"(?is)<[^>]+>", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        snippet = cleaned[:1500]
        return f"Web search results for '{query}':\n{snippet}"
    except requests.RequestException as exc:
        return f"Error: web search request failed ({exc})"
    except Exception as exc:
        return f"Error: {exc}"


def run_task(prompt: str, description: str = "") -> str:
    return (
        "Task tool invoked. "
        "Subtask execution is not supported in this runtime environment. "
        "Received prompt: "
        f"{prompt}. "
        f"Description: {description}"
    )

#建立工具的函数
TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "todo": lambda **kw: TODO.update(kw["items"]),
    "data_query": lambda **kw: run_data_query(kw["sat_id"], kw["para_name"], kw["start_time"], kw["end_time"]),
    "load_skills": lambda **kw: Skill_loader.get_content(kw["name"]),
    "web_search": lambda **kw: web_search(kw["query"]),
    "task": lambda **kw: run_task(kw["prompt"], kw.get("description", ""))
}
Tools=[
    {"type":"function",
     "function":{
         "name":"bash","description":"运行一个shell command。",
         "parameters":{"type":"object","properties":{
             "command":{"type":"string","description":"要运行的命令"}
         }}
     }},
    {"type": "function",
     "function": {
         "name": "read_file", "description": "读取一个文本文件。",
         "parameters": {"type": "object", "properties": {
             "path": {"type": "string", "description": "文件存储的路径"},
             "limit": {"type": "integer", "description": "要读取的行数限制"}
         }}
     }},
    {"type": "function",
     "function": {
         "name": "write_file", "description": "将指定的内容写入到文件中。",
         "parameters": {"type": "object", "properties": {
             "path": {"type": "string", "description": "要写入的文件名称和地址"},
             "content": {"type": "string", "description": "要写入的文件内容"}
         }}
     }},
    {"type": "function",
         "function": {
             "name": "edit_file", "description": "修改文件中的指定内容。",
             "parameters": {"type": "object", "properties": {
                 "path": {"type": "string", "description": "要修改的文件的路径"},
                 "old_text":{"type":"string","description":"要替换的旧内容"},
                 "new_text":{"type":"string","description":"替换写入的新内容"}
             }}
         }},
    {"type": "function",
         "function": {
             "name": "todo", "description": "更新任务列表，在多步任务中标记任务状态",
             "parameters": {"type": "object", "properties": {
                 "items": {"type": "array", "description": "任务清单列表","items":{
                     "type":"object",
                     "properties":{
                         "id":{"type":"string","description":"任务ID"},
                         "text":{"type":"string","description":"任务内容"},
                         "status":{"type":"string","description":"任务状态","enum":["pending","in_progress","completed"]}
                     },
                     "required":["id","text","status"]
                 }},
             },"required":["items"]}
         }},
    {"type": "function",
             "function": {
                 "name": "task", "description": "启动一个具有纯净上下文的子任务智能体，他与父任务智能体共享文件系统，但是不继承历史上下文",
                 "parameters": {"type": "object", "properties": {
                     "prompt": {"type": "string", "description": "子任务的大模型提示词"},
                     "description":{"type":"string","description":"子任务的描述"}
                 },"required":["prompt"]}
             }},
    {"type": "function",
         "function": {
             "name": "data_query", "description": "查询命令，获取指定卫星遥测参数在某个时间段内的值，在要求查询的任务中优先使用",
             "parameters": {"type": "object", "properties": {
                 "sat_id": {"type": "string", "description": "要查询的卫星编号，目前只有编号'01'"},
                 "para_name": {
                     "type": "array",
                     "description": "要查询的遥测参数名称列表,必须从指定的参数列表中选择",
                     "items": {"type": "string"}
                 },
                 "start_time": {"type": "string", "description": "查询开始时间，格式为'YYYY-MM-DD hh:mm'"},
                 "end_time": {"type": "string", "description": "查询结束时间，格式为'YYYY-MM-DD hh:mm'"}
             },"required":["sat_id","para_name","start_time","end_time"]}
         }},
    {"type": "function",
             "function": {
                 "name": "load_skills", "description": "根据skill技能的名称来加载技能的全部内容。",
                 "parameters": {"type": "object", "properties": {
                     "name": {"type": "string", "description": "技能的名称"}
                 },"required":["name"]}
             }},
    {"type": "function",
         "function": {
             "name": "web_search", "description": "当你感觉到自己的知识不足以回答用户问题时，使用百度搜索搜索网络上相关的内容。",
             "parameters": {"type": "object", "properties": {
                 "query": {"type": "string", "description": "在百度搜索中要搜索的内容"}
             }, "required": ["query"]}
         }}
]

def agent_loop(messages: list):
    rounds_since_todo = 0
    llm_count=0
    max_rounds = 30
    while llm_count < max_rounds:
        # use Gemini streaming API for more real-time output
        full_content=""
        final_tool_calls = []
        printed_tool_call_ids = set()
        llm_count+=1
        print(f"______________________这是本次任务中大模型的第{llm_count}次调用_________________________")
        # Start Gemini streaming in a background consumer thread and relay chunks via a queue
        import threading, queue
        stream = chat_reply_stream(
            messages,
            tools=Tools,
            model_name=_active_model_name_override(),
            profile_name=_active_model_profile(),
        )
        chunk_q = queue.Queue()
        STREAM_FINISHED_MARKER = {"type": "__STREAM_FINISHED__"}

        def _stream_consumer():
            try:
                for c in stream:
                    chunk_q.put(c)
            except Exception as e:
                # propagate exception to main thread via a special dict
                chunk_q.put({"type": "__STREAM_ERROR__", "error": str(e)})
            finally:
                chunk_q.put(STREAM_FINISHED_MARKER)

        t = threading.Thread(target=_stream_consumer, daemon=True)
        t.start()

        watchdog = int(os.getenv("GEMINI_STREAM_TIMEOUT", "120"))
        stream_failed = False
        while True:
            try:
                chunk = chunk_q.get(timeout=watchdog)
            except queue.Empty:
                print(f"[stream watchdog] no chunks received for {watchdog}s, aborting this LLM call", flush=True)
                stream_failed = True
                break

            if not isinstance(chunk, dict):
                print(f"Warning: received non-dict stream chunk: {chunk}")
                continue

            if chunk.get("type") == "__STREAM_ERROR__":
                print(f"[stream error] {chunk.get('error')}", flush=True)
                stream_failed = True
                break

            if chunk.get("type") == "__STREAM_FINISHED__":
                # normal end of stream
                break

            if chunk.get("type") == "chunk":
                content_text = str(chunk.get("content") or "")
                chunk_tool_calls = chunk.get("tool_calls") or []
                if chunk_tool_calls and not content_text:
                    for call in chunk_tool_calls:
                        call_id = call.get("id")
                        name = call.get("function", {}).get("name")
                        if call_id and call_id not in printed_tool_call_ids:
                            printed_tool_call_ids.add(call_id)
                            print(f"[tool call] {name}() requested", flush=True)
                if content_text:
                    print(content_text, end="", flush=True)
                    full_content += content_text
                if chunk_tool_calls:
                    for call in chunk_tool_calls:
                        if call not in final_tool_calls:
                            final_tool_calls.append(call)
            elif chunk.get("type") == "done":
                content_text = str(chunk.get("content") or "")
                if content_text and content_text != full_content:
                    # If done contains final aggregate text not already emitted
                    print(content_text, end="", flush=True)
                    full_content = content_text
                final_tool_calls = chunk.get("tool_calls") or final_tool_calls
            else:
                # unknown stream event, print for debugging
                print(f"[stream event] {chunk}")

        if stream_failed and not full_content and not final_tool_calls:
            print("[stream fallback] stream failed to return data, retrying with sync Gemini request", flush=True)
            try:
                sync_response = chat_reply(
                    messages,
                    tools=Tools,
                    model_name=_active_model_name_override(),
                    profile_name=_active_model_profile(),
                )
                full_content = sync_response.get("content", "") or ""
                final_tool_calls = sync_response.get("tool_calls", []) or final_tool_calls
                if full_content:
                    print(full_content, end="", flush=True)
            except Exception as e:
                print(f"[stream fallback] sync Gemini request failed: {e}", flush=True)
        print("\n________________________________本次大模型输出结束_____________________________________")
        if not full_content and not final_tool_calls:
            print("[stream note] Gemini did not return direct assistant text in this round.", flush=True)
        print(f"模型返回 content length={len(full_content)}, tool_calls count={len(final_tool_calls)}")
        assistant_message={"role":"assistant","content":full_content if full_content else None}
        if final_tool_calls:
            assistant_message["tool_calls"] = final_tool_calls
        messages.append(assistant_message)
        if not assistant_message.get("tool_calls"):
            return
        results = []
        used_todo = False
        for block in assistant_message.get("tool_calls"):
            if block.get("type") == "function":
                #print(f"{block.get('function')}")
                tool_name=block.get("function").get("name")
                handler = TOOL_HANDLERS.get(block.get("function").get("name"))
                try:
                    argument_json = json.loads(block.get("function").get("arguments") or "{}")
                except (TypeError, json.JSONDecodeError) as e:
                    argument_json = {}
                    print(f"工具参数解析失败: {e}")
                try:
                    output = handler(**argument_json) if handler else f"Unknown tool: {tool_name}"
                except Exception as e:
                    output = f"Error:{e}"
                print(f">>>>>>>本次工具调用：{tool_name}")
                print(f">>>>>>>本次工具调用的参数：{argument_json}")
                print(f">>>>>>>本次工具调用的结果为：")
                output_text = str(output)
                print(output_text[:500] if output_text else "(empty string)")
                if tool_name == "todo":
                    used_todo = True
                if tool_name == "load_skills":
                    print(f"\n本次运行中，加载了技能文件，内容为{output}\n")
                messages.append({"role": "tool", "tool_call_id": block.get("id"), "content": json.dumps(output, ensure_ascii=False, default=str)})
        rounds_since_todo = 0 if used_todo else rounds_since_todo + 1
        if rounds_since_todo >= 3:
            messages.append({"role":"user","content":"<reminder>请注意更新你的todo清单.</reminder>"})
    print(f"达到最大智能体轮次（{max_rounds}），停止继续调用。")

def run_cli(default_profile: str = "gemini_default", llm: str | None = None):
    target_profile = _resolve_profile_from_llm(llm, default_profile)
    os.environ["MODEL_PROFILE"] = target_profile
    print(f"当前模型配置：{profile_summary(_active_model_profile())}")
    print(f"[llm] active profile: {target_profile}")
    history = [{"role": "system", "content": SYSTEM}]
    while True:
        try:
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)


if __name__=="__main__":
    parser = argparse.ArgumentParser(description="Fault diagnosis agent runner")
    parser.add_argument(
        "--llm",
        default="gemini",
        choices=["gemini", "chatgpt", "openai"],
        help="Base LLM provider/profile selector (default: gemini)",
    )
    args = parser.parse_args()
    run_cli(default_profile="gemini_default", llm=args.llm)
