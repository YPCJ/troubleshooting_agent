from dotenv import load_dotenv
import subprocess
from pathlib import Path
import os
import json
import re
import yaml
from datetime import datetime
import sys
# Ensure project root is importable when running this script directly
# so sibling modules like `tool_boxes.py` can be found.
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = next((p for p in [SCRIPT_DIR, *SCRIPT_DIR.parents] if (p / ".env").exists()), SCRIPT_DIR.parent)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
import tool_boxes
import time
import requests
from typing import List, Dict,Any
import shlex
import pandas as pd
import chardet
from tabulate import tabulate
from ai_gemini import chat_reply, chat_reply_stream

# 加载环境变量，设置时间
now=datetime.now()

PROJECT_ROOT = tool_boxes.find_project_root(Path(__file__).resolve().parent)
dotenv_path = PROJECT_ROOT / ".env"
load_dotenv(override=True, dotenv_path=dotenv_path)
#print(os.getenv("base_url"))

WORKDIR = PROJECT_ROOT  # 工作目录固定为项目根目录，避免相对路径受启动位置影响
_legacy_model_name = os.getenv("model_name")
model_name = (
    os.getenv("GEMINI_MODEL")
    or os.getenv("gemini_model")
    or (_legacy_model_name if _legacy_model_name and "gemini" in _legacy_model_name.lower() else None)
    or "gemini-1.5-flash"
)
Skills_dir=tool_boxes.resolve_skills_dir(__file__, workdir=WORKDIR, project_root=PROJECT_ROOT)
#data_url='http://localhost:5000/api/external-query'
data_url=os.getenv("DATA_URL", 'http://49.233.215.205:5000/api/external-query')

sample_query="请排查01号卫星在2025-10-28 15:00发生的蓄电池故障的原因，请排查01号卫星在2025-10-28 15:00发生的太阳能电池故障的原因"
sample_query="请查询01号卫星在2025-10-28 15:00到2025-10-28 18:00时间段内的“蓄电池A测点1”的数据并且绘制图表"
sample_query="请读取demo文件夹下面的PACK_3_00E6_ss_20251028_889258497.csv文件，并且解析其表头标题的含义"
sample_query="请使用卫星遥测参数日志格式转换技能，针对skills/format_transform/target/PACK_3_0056_ss_20251024_84017411.csv文件进行日志格式转换"
sample_query="请读取skills/format_transform/reference/standard_log2.csv文件，并且解析其表头标题的含义"
sample_query="请使用卫星遥测参数日志格式转换技能，针对skills/format_transform/target文件夹下的文件进行日志格式转换"

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

Skill_loader = SkillLoader(Skills_dir)
SYSTEM = f"""你是一个故障排查专家.工作在{WORKDIR}目录下，现在的时间是{now}.
你工作在跨平台环境中（macOS/Linux/Windows），请根据当前系统选择合适命令（如 macOS/Linux 使用 ls、Windows 使用 dir），并优先使用当前环境可用的 Python 解释器。
读取 .csv/.txt/.md 等文件内容时，不要使用 bash 执行 head/cat/awk 等直接读取原始字节，优先使用 read_csv 或 read_file 工具，避免因文件为 GBK/GB18030 等编码而出现乱码。
在处理你不熟悉的任务时使用你的skill技能来解决问题。你在调用函数工具时，会严格按照要求撰写。
可以采用的skill技能包括：
{Skill_loader.get_descriptions()}
"""
print(f"智能体首次运行，其初始提示词为：\n{SYSTEM}\n--------------------")

def _maybe_preview_file_via_bash(command: str) -> str | None:
    try:
        args = shlex.split(command)
    except ValueError:
        return None
    if not args:
        return None

    file_arg = None
    line_limit = None
    if args[0] == "head":
        if len(args) >= 4 and args[1] == "-n":
            line_limit = int(args[2])
            file_arg = args[3]
        elif len(args) >= 2:
            file_arg = args[-1]
    elif args[0] == "cat" and len(args) == 2:
        file_arg = args[1]

    if not file_arg:
        return None

    suffix = Path(file_arg).suffix.lower()
    if suffix == ".csv":
        return run_read_csv(file_arg, line_limit)
    if suffix in {".txt", ".md", ".log", ".json", ".yaml", ".yml"}:
        return run_read(file_arg, line_limit)
    return None

def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    shell_operators = ["|", "&&", "||", ";", ">", "<", "`", "$"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    if any(op in command for op in shell_operators):
        return "Error: Shell operators are not allowed in bash tool"
    preview_result = _maybe_preview_file_via_bash(command)
    if preview_result is not None:
        return preview_result
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
        return out[:50000] if out else "(no output)"
    except ValueError as e:
        return f"Error: Invalid command syntax: {e}"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"

def run_read(path: str, limit: int = None) -> str:
    try:
        with open(path,"rb") as f:
            raw=f.read(1000)
        enc = chardet.detect(raw)['encoding'] or 'utf-8'
        print(f"读取的编码格式为:{enc}")
        for enc_try in [enc,"utf-8","gbk","gb2312","gb18030"]:
            try:
                text = safe_path(path).read_text(encoding=enc_try)
                lines = text.splitlines()
                if limit and limit < len(lines):
                    lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
                return "\n".join(lines)[:50000]
            except UnicodeDecodeError:
                continue
    except Exception as e:
        return f"Error: {e}"

def run_read_csv(path:str,limit:int = None)->str:
    try:
        if not limit:
            limit=5
        with open(path,"rb") as f:
            raw=f.read(50000)
        #char_read=safe_path(path).read_bytes()
        enc=chardet.detect(raw)['encoding'] or 'utf-8'
        print(f"读取的编码格式为:{enc}")
        for enc_try in [enc,"utf-8","gbk","gb2312","gb18030"]:
            try:
                df=pd.read_csv(safe_path(path),encoding=enc_try,nrows=limit)
                try:
                    table_df=df.to_markdown(index=False)
                    #print(f"markdown文字为：\n{table_df}")
                except ImportError:
                    table_df=df.to_string(index=False)
                    #print(ImportError)
                    #print(f"string文字为：\n{table_df}")

                #print(f"读取的csv文件内容为:\n{table_df}")

                return f"读取的csv文件内容为:\n{table_df}"
            except UnicodeDecodeError:
                continue

    except Exception as e:
        return f"Error in read csv files:{e}"


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

def run_data_query(sat_id:str,para_name:list,start_time:str,end_time:str)->list:
    try:
        print("调用卫星遥测参数查询工具：")
        request_body={
            "sat_id":sat_id,
            "para_name":para_name,
            "start_time":start_time,
            "end_time":end_time
        }
        print(request_body)
        response=requests.post(data_url,json=request_body)
        result=response.json()

        for item in result:
            print(f"参数: {item['para_name']}")
            for point in item['value']:
                print(f"  {point['time']}: {point['point_value']}")

        return result

    except Exception as e:
        return f"Error:{e}"


#建立工具的函数
TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw["path"], kw.get("limit")),
    "read_csv": lambda **kw:run_read_csv(kw["path"],kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "data_query":lambda **kw:run_data_query(kw["sat_id"],kw["para_name"],kw["start_time"],kw["end_time"]),
    "load_skills": lambda **kw: Skill_loader.get_content(kw["name"])
}
Tools=[
    {"type":"function",
     "function":{
        "name":"bash","description":"运行一个shell command。需要注意，请写好stdout，确保智能体了解程序运行结果。不要用它直接读取 csv/txt/md 文件内容，读取文件请优先使用 read_csv 或 read_file。",
         "parameters":{"type":"object","properties":{
            "command":{"type":"string","description":"要运行的命令。需要注意，必须要写好stdout，确保智能体了解程序运行结果。除非程序运行失败，否则必然要有stdout输出。对于 csv/txt/md 文件内容读取，不要使用 head/cat，请改用 read_csv 或 read_file。"}
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
             "name": "read_csv", "description": "读取一个后缀为.csv的文件",
             "parameters": {"type": "object", "properties": {
                 "path": {"type": "string", "description": "csv文件存储的路径"},
                 "limit": {"type": "integer", "description": "需要读取的csv文件的行数限制，默认为3"}
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
             "name": "data_query", "description": "查询命令，获取指定卫星遥测参数在某个时间段内的值，在要求查询的任务中优先使用",
             "parameters": {"type": "object", "properties": {
                 "sat_id": {"type": "string", "description": "要查询的卫星编号，目前只有编号\'01\'"},
                 "para_name": {
                     "type": "array",
                     "description": "要查询的遥测参数名称列表,必须从指定的参数列表中选择",
                     "items": {"type": "string"}
                 },
                 "start_time": {"type": "string", "description": "查询开始时间，格式为\'YYYY-MM-DD hh:mm\'"},
                 "end_time": {"type": "string", "description": "查询结束时间，格式为\'YYYY-MM-DD hh:mm\'"}
             },"required":["sat_id","para_name","start_time","end_time"]}
         }},
    {"type": "function",
             "function": {
                 "name": "load_skills", "description": "根据skill技能的名称来加载技能的全部内容。",
                 "parameters": {"type": "object", "properties": {
                     "name": {"type": "string", "description": "技能的名称"}
                 },"required":["name"]}
             }}
]

def agent_loop(messages: list):
    rounds_since_todo = 0
    llm_count=0
    max_rounds = 30
    while llm_count < max_rounds:
        full_content=""
        final_tool_calls = []
        printed_tool_call_ids = set()
        llm_count+=1
        print(f"______________________这是本次任务中大模型的第{llm_count}次调用_________________________")
        import threading, queue
        stream = chat_reply_stream(messages, tools=Tools, model_name=model_name)
        chunk_q = queue.Queue()
        stream_finished_marker = {"type": "__STREAM_FINISHED__"}

        def _stream_consumer():
            try:
                for chunk in stream:
                    chunk_q.put(chunk)
            except Exception as e:
                chunk_q.put({"type": "__STREAM_ERROR__", "error": str(e)})
            finally:
                chunk_q.put(stream_finished_marker)

        threading.Thread(target=_stream_consumer, daemon=True).start()

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
                    print(content_text, end="", flush=True)
                    full_content = content_text
                final_tool_calls = chunk.get("tool_calls") or final_tool_calls
            else:
                print(f"[stream event] {chunk}")

        if stream_failed and not full_content and not final_tool_calls:
            print("[stream fallback] stream failed to return data, retrying with sync Gemini request", flush=True)
            try:
                sync_response = chat_reply(messages, tools=Tools, model_name=model_name)
                full_content = sync_response.get("content", "") or ""
                final_tool_calls = sync_response.get("tool_calls", []) or final_tool_calls
                if full_content:
                    print(full_content, end="", flush=True)
            except Exception as e:
                print(f"[stream fallback] sync Gemini request failed: {e}", flush=True)
        print("\n________________________________本次大模型输出结束_____________________________________")
        if not full_content and not final_tool_calls:
            print("[stream note] Gemini did not return direct assistant text in this round.", flush=True)
        assistant_message={"role":"assistant","content":full_content if full_content else None}
        if final_tool_calls:
            assistant_message["tool_calls"] = final_tool_calls
        messages.append(assistant_message)
        if not assistant_message.get("tool_calls"):
            return
        used_todo = False
        for block in assistant_message.get("tool_calls"):
            if block.get("type") == "function":
                tool_name=block.get("function").get("name")
                handler = TOOL_HANDLERS.get(tool_name)
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

if __name__=="__main__":
    history = [{"role":"system","content":SYSTEM}]
    while True:
        try:
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        start_time = datetime.now()
        print(start_time)
        history.append({"role": "user", "content": query})
        agent_loop(history)
        response_content = history[-1]["content"]
        end_time = datetime.now()
        print(f"模型调用结束时间为:{end_time},耗时为:{end_time - start_time}")
        #if response_content:
            # print(response_content)
        # if isinstance(response_content, list):
        #     for block in response_content:
        #         if hasattr(block, "text"):
        #             print(block.text)