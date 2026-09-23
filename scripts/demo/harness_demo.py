from llm.legacy import legacy_chat_completion, legacy_openai_client
from dotenv import load_dotenv
import subprocess
from pathlib import Path
import os
import json
import re
import yaml
import requests
import httpx
from datetime import datetime
import time
import requests
from typing import List, Dict, Any
import shlex

now=datetime.now()

def find_project_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / ".env").exists():
            return p
    return start

PROJECT_ROOT = find_project_root(Path(__file__).resolve().parent)
dotenv_path = PROJECT_ROOT / ".env"
load_dotenv(override=True, dotenv_path=dotenv_path)
print(dotenv_path)

WORKDIR=Path.cwd()
#print(os.getenv("api_key"),os.getenv("base_url"))
model_name=os.getenv("model_name")
sub_system=f"你是一个工作在{os.getcwd()}目录下的编程助手，你接受指定的任务，并且总结你的发现。"
Skills_dir=WORKDIR/"skills"

data_url='http://localhost:5000/api/external-query'
query="请排查01号卫星在2025-10-28 15:00发生的蓄电池故障的原因，请排查01号卫星在2025-10-28 15:00发生的太阳能电池故障的原因"

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
    def get_skill_ref(self,name:str)->str:
        #获取reference文件夹下面的json文件
        file_path=os.path.join(WORKDIR,"skills",name,"reference")
        print(file_path)
        file_list=os.listdir(file_path)
        for file in file_list:
            skill_data=run_read(os.path.join(file_path,file))
            return skill_data

Skill_loader = SkillLoader(Skills_dir)
SYSTEM = f"""你是一个故障排查专家.工作在{WORKDIR}目录下，现在的时间是{now}.
在处理你不熟悉的任务时使用你的skill技能来解决问题。你在调用函数工具时，会严格按照要求撰写。
可以采用的skill技能包括：
{Skill_loader.get_descriptions()}
"""
print(SYSTEM)

##搜索引擎
class BaiduOfficialWebSearch:
    """
    百度官方 Web Search API 封装
    鉴权方式: Bearer Token (AppBuilder API Key)
    """

    BASE_URL = "https://qianfan.baidubce.com/v2/ai_search/web_search"

    def __init__(self, api_key: str = None):
        """
        :param api_key: bce-v3/ALTAK-xxx 格式的 API Key
                        不传则从环境变量 BAIDU_SEARCH_API_KEY 读取
        """
        self.api_key = api_key or os.getenv("BAIDU_SEARCH_API_KEY")
        if not self.api_key:
            raise ValueError(
                "❌ 缺少 API Key！\n"
                "请设置环境变量 BAIDU_SEARCH_API_KEY 或在构造函数传入。\n"
                "获取地址: https://console.bce.baidu.com/ai-search/qianfan/ais/console/apiKey"
            )

    # ------------------------------------------------------------------
    # 核心搜索
    # ------------------------------------------------------------------
    def search(
        self,
        query: str,
        top_k: int = 5,
        edition: str = "standard",
        site_filter: List[str] | None = None,
        time_filter: str | None = None,
        max_retry: int = 2,
    ) -> List[Dict[str, Any]]:
        """
        调用百度官方搜索 API

        :param query:      搜索关键词（≤72字符，汉字算2字符）
        :param top_k:      返回网页条数（≤50）
        :param edition:    standard | lite（lite更快但效果略弱）
        :param site_filter:限定站点，如 ["zhihu.com", "github.com"]
        :param time_filter: week | month | semiyear | year
        :param max_retry:  失败自动重试次数
        :return:          结构化结果列表
        """

        if not query or not query.strip():
            return []

        payload = {
            "messages": [{"role": "user", "content": query.strip()}],
            "search_source": "baidu_search_v2",
            "resource_type_filter": [
                {"type": "web", "top_k": min(top_k, 50)},
                {"type": "video", "top_k": 0},
                {"type": "image", "top_k": 0},
            ],
            "edition": edition,
        }

        if site_filter:
            payload.setdefault("search_filter", {})
            payload["search_filter"]["match"] = {"site": site_filter}

        if time_filter:
            payload["search_recency_filter"] = time_filter

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        # -------- 请求 + 重试 --------
        for attempt in range(max_retry + 1):
            try:
                resp = requests.post(
                    self.BASE_URL,
                    headers=headers,
                    json=payload,
                    timeout=20,
                )

                if resp.status_code == 429:
                    # 限流：等一会儿重试
                    wait = 2 ** (attempt + 1)
                    print(f"[WARN] 触发限流(429)，{wait}s 后重试…")
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                body = resp.json()

                # -------- 解析结果 --------
                return self._parse(body)

            except requests.exceptions.RequestException as e:
                if attempt < max_retry:
                    time.sleep(2)
                    continue
                print(f"[ERROR] 请求失败: {e}")
                break
            except Exception as e:
                print(f"[ERROR] 解析失败: {e}")
                break

        return []

    # ------------------------------------------------------------------
    # 解析响应
    # ------------------------------------------------------------------
    def _parse(self, body: dict) -> List[Dict[str, Any]]:
        """
        官方响应中搜索结果在 body["references"] 里
        """
        refs = (body or {}).get("references") or (body or {}).get("data") or []
        results: List[Dict[str, Any]] = []

        for i, item in enumerate(refs, start=1):
            results.append({
                "rank": i,
                "title": (item.get("title") or "").strip(),
                "url": (item.get("url") or item.get("href") or "").strip(),
                "snippet": (item.get("content") or item.get("snippet") or "").strip()[:400],
                "date": (item.get("date") or item.get("page_time") or ""),
                "authority_score": item.get("authority_score"),
            })

        return results

    # ------------------------------------------------------------------
    # 渲染为 LLM context 文本
    # ------------------------------------------------------------------
    def render_for_context(self, results: List[Dict]) -> str:
        if not results:
            return "[百度官方搜索：无结果 / API Key 未配置？]"
        lines = ["## 百度搜索参考信息（官方 API）\n"]
        for r in results:
            lines.append(
                f"**[{r['rank']}] {r['title']}**  \n"
                f"{r['snippet']}  \n"
                f"<{r['url']}>\n"
            )
        return "\n".join(lines)

# -- TodoManager: structured state the LLM writes to --
class TodoManager:
    def __init__(self):
        self.items = []

    def update(self, items: list) -> str:
        if len(items) > 20:
            raise ValueError("Max 20 todos allowed")
        validated = []
        in_progress_count = 0
        for i, item in enumerate(items):
            text = str(item.get("text", "")).strip()
            status = str(item.get("status", "pending")).lower()
            item_id = str(item.get("id", str(i + 1)))
            if not text:
                raise ValueError(f"Item {item_id}: text required")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {item_id}: invalid status '{status}'")
            if status == "in_progress":
                in_progress_count += 1
            validated.append({"id": item_id, "text": text, "status": status})
        if in_progress_count > 1:
            raise ValueError("Only one task can be in_progress at a time")
        self.items = validated
        return self.render()

    def render(self) -> str:
        if not self.items:
            return "No todos."
        lines = []
        for item in self.items:
            marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}[item["status"]]
            lines.append(f"{marker} #{item['id']}: {item['text']}")
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)

TODO = TodoManager()
client=legacy_openai_client(http_client=httpx.Client())
web_searchtool=BaiduOfficialWebSearch()
#message=[{"role":"system", "content":SYSTEM},{"role":"user", "content":"请介绍一下你自己"}]


def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path

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
            r = subprocess.run(["cmd", "/c", command], shell=False, cwd=str(WORKDIR),
                               capture_output=True, text=True, timeout=120, encoding="utf-8", errors="ignore")
        else:
            args = shlex.split(command)
            if not args:
                return "Error: Empty command"
            r = subprocess.run(args, shell=False, cwd=str(WORKDIR),
                               capture_output=True, text=True, timeout=120, encoding="utf-8", errors="ignore")
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

def web_search(query:str)->str:
    try:
        result=web_searchtool.search(query,top_k=5)
        print(f"百度搜索得到的结果是：")
        print(f"{result}")
        return json.dumps(result)
    except Exception as e:
        return f"在调用百度搜索工具时发生错误:{e}"



#建立工具的函数
TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "todo": lambda **kw: TODO.update(kw["items"]),
    "data_query":lambda **kw:run_data_query(kw["sat_id"],kw["para_name"],kw["start_time"],kw["end_time"]),
    "load_skills": lambda **kw: Skill_loader.get_content(kw["name"]),
    "web_search":lambda **kw:web_search(kw["query"])
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
                 "sat_id": {"type": "string", "description": "要查询的卫星编号，目前只有编号\'01\'"},
                 "para_name": {"type": "array", "description": "要查询的遥测参数名称列表,必须从指定的参数列表中选择"},
                 "start_time": {"type": "string", "description": "查询开始时间，格式为\'YYYY-MM-DD hh:mm\'"},
                 "end_time": {"type": "string", "description": "查询结束时间，格式为\'YYYY-MM-DD hh:mm\'"}
             },"required":["sat_id","para_name","start_time","end_time"]}
         }},
    {"type": "function",
             "function": {
                 "name": "load_skills", "description": "根据skill技能的名称来加载技能的全部内容。",
                 "parameters": {"type": "object", "properties": {
                     "name": {"type": "string", "description": "技能的名称"}
                 },"reuired":"name"}
             }},
    {"type": "function",
         "function": {
             "name": "web_search", "description": "当你感觉到自己的知识不足以回答用户问题时，使用百度搜索搜索网络上相关的内容。",
             "parameters": {"type": "object", "properties": {
                 "query": {"type": "string", "description": "在百度搜索中要搜索的内容"}
             }}
         }}
]

Child_Tools=[
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
]

def run_subagent(prompt: str) -> str:
    sub_context=[]
    sub_context.append({"role":"system","content":sub_system})
    sub_context.append({"role": "user", "content": prompt})
    for _ in range(10):  # safety limit
        response=legacy_chat_completion(client,
            model=model_name,
            messages=sub_context,
            max_tokens=10000,
            temperature=0.7,
            tools=Child_Tools,
            tool_choice="auto"
        )
        if response.choices[0].finish_reason!="tool_calls":
            sub_context.append({"role": "assistant", "content": response.choices[0].message.content})
            break
        else:
            sub_context.append(response.choices[0].message)

        results = []
        for block in response.choices[0].message.tool_calls:
            if block.type == "function":
                json_pr=json.loads(block.function.arguments)
                handler = TOOL_HANDLERS.get(block.function.name)
                output = handler(**json_pr) if handler else f"Unknown tool: {block.function.name}"
                print(str(output[:5000]))
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)[:50000]})
            sub_context.append({"role":"tool","tool_call_id":block.id,"content":json.dumps(output)})

        print(response.choices[0].message.content)
        #sub_messages.append({"role": "user", "content": results})
    # Only the final text returns to the parent -- child context is discarded
    return response.choices[0].message.content or "(no summary)"
    #return "".join(b.text for b in response.choices[0].message if hasattr(b, "text")) or "(no summary)"

def agent_loop(messages: list,client:Any):
    rounds_since_todo = 0
    while True:
        #编写了两套代码，一套是固定输出，一套是流式输出
        #流式输出的代码开始
        full_content=""
        full_tool={}
        print("_________________________","大模型开始输出","_________________________")
        response=legacy_chat_completion(client,
            model=model_name,
            messages=messages,
            max_tokens=10000,
            tools=Tools,
            temperature=0.5,
            tool_choice="auto",
            stream=True
        )
        for chunk in response:
            if chunk.choices:
                delta=chunk.choices[0].delta

                if delta.content is not None:
                    print(delta.content,end="",flush=True)
                    full_content+=delta.content

                if delta.tool_calls:
                    for tool_chunk in delta.tool_calls:
                        idx=tool_chunk.index
                        #初始化收集器
                        if idx not in full_tool:
                            full_tool[idx]={"id":"","type":"function","function":{"name":"","arguments":""}}
                        #收集id
                        if tool_chunk.id:
                            full_tool[idx]["id"]+=tool_chunk.id
                            print(tool_chunk.id,end="",flush=True)
                        if tool_chunk.function and tool_chunk.function.name:
                            full_tool[idx]["function"]["name"]+=tool_chunk.function.name
                            print(tool_chunk.function.name,end="",flush=True)
                        if tool_chunk.function and tool_chunk.function.arguments:
                            full_tool[idx]["function"]["arguments"]+=tool_chunk.function.arguments
                            print(tool_chunk.function.arguments,end="",flush=True)
        print("\n________________________________大模型输出结束，转入工具调用及总结_____________________________________")
        assistant_message={"role":"assistant","content":full_content if full_content else None}
        if full_tool:
            assistant_message["tool_calls"]=[
                {
                    "id":data["id"],
                    "type":data["type"],
                    "function":{
                        "name":data["function"]["name"],
                        "arguments":data["function"]["arguments"]
                    }
                } for idx,data in sorted(full_tool.items()) if data["id"]
            ]
        messages.append(assistant_message)
        if not assistant_message.get("tool_calls"):
            return
        results = []
        used_todo = False
        for block in assistant_message.get("tool_calls"):
            if block.get("type") == "function":
                user_verification=input(f"请确认是否执行工具调用？yes/no \n")
                if user_verification=="yes":
                    #print(f"{block.get('function')}")
                    tool_name=block.get("function").get("name")
                    handler = TOOL_HANDLERS.get(block.get("function").get("name"))
                    argument_json = json.loads(block.get("function").get("arguments"))
                    if tool_name=="data_query":
                        #print("进入data_query工具调用")
                        value_judge=Skill_loader.get_skill_ref("telemetry_query")
                        #print("已经读取了文件")
                        value_json=json.loads(value_judge)
                        value_list=value_json.get("value")
                        print(f"value_list:{value_list}")
                        for value in value_list:
                            print(f"value:{value}")
                            if value.get("parameter_name")=="sat_id":
                                sat_id_list=value.get("enum")
                            if value.get("parameter_name")=="para_name":
                                para_name_list=value.get("enum")
                                # print(f"para_name_list:{para_name_list}")
                                # print(argument_json.get("sat_id"))
                                # print(argument_json.get("para_name"))
                                # print(argument_json.get("sat_id") in sat_id_list)
                                #print(all(para in para_name_list for para in argument_json.get("para_name")))
                                para_in_list=argument_json.get("para_name") and all(para in para_name_list for para in argument_json.get("para_name"))
                                #print(para_in_list)
                        if argument_json.get("sat_id") in sat_id_list and para_in_list:
                            try:
                                output = handler(**argument_json) if handler else f"Unknown tool: {block.name}"
                            except Exception as e:
                                output = f"Error:{e}"
                        else:
                            output=f"调用data_query工具时所使用的参数并不在可选范围内,参数的可选范围为{value_list}"
                    else:
                        try:
                            output = handler(**argument_json) if handler else f"Unknown tool: {block.name}"
                        except Exception as e:
                            output = f"Error:{e}"
                    #print(f"> {tool_name}:")
                    print(output[:500])
                    if tool_name == "todo":
                        used_todo = True
                    if tool_name == "load_skills":
                        print(f"加载的技能文件为{output}")

                    if tool_name=="load_skills":
                        messages.append({"role": "system", "tool_call_id": block.get("id"), "content": json.dumps(output)})
                    else:
                        messages.append({"role": "tool", "tool_call_id": block.get("id"), "content": json.dumps(output)})
                else:
                    messages.append({"role": "user", "tool_call_id": block.get("id"), "content": "用户决定不调用工具，请直接跳过工具调用环节直接进行总结。"})
        rounds_since_todo = 0 if used_todo else rounds_since_todo + 1
        if rounds_since_todo >= 300:
            messages.append({"role":"user","content":"<reminder>请注意更新你的todo清单.</reminder>"})
            # 流式输出的代码结束

            # # 固定输出的代码开始
            # print("即将开始调用大模型")
            # response = client.chat.completions.create(
            #     model=model_name,
            #     messages=messages,
            #     max_tokens=10000,
            #     tools=Tools,
            #     temperature=0.7,
            #     tool_choice="auto"
            # )
            # print("大模型调用成功")
            #
            # if response.choices[0].finish_reason!="tool_calls":
            #     messages.append({"role": "assistant", "content": response.choices[0].message.content})
            #     return
            # else:
            #     messages.append(response.choices[0].message)
            #
            # results = []
            # used_todo = False
            # for block in response.choices[0].message.tool_calls:
            #     if block.type == "function":
            #         argument_json = json.loads(block.function.arguments)
            #         if block.function.name=="task":
            #             desc=argument_json.get("description","subtask")
            #             sub_prompt=argument_json.get("prompt")
            #             print(f"> task ({desc}): {sub_prompt[:80]}")
            #             output=run_subagent(sub_prompt)
            #         else:
            #             handler = TOOL_HANDLERS.get(block.function.name)
            #             #argument_json = json.loads(block.function.arguments)
            #             try:
            #                 output = handler(**argument_json) if handler else f"Unknown tool: {block.name}"
            #             except Exception as e:
            #                 output = f"Error:{e}"
            #
            #         print(f"> {block.function.name}:")
            #         print(output[:500])
            #         if block.function.name == "todo":
            #             used_todo = True
            #         #results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
            #         messages.append({"role":"tool","tool_call_id":block.id,"content":json.dumps(output)})
            # rounds_since_todo = 0 if used_todo else rounds_since_todo + 1
            # if rounds_since_todo >= 3:
            #     messages.append({"role": "user", "content": "<reminder>请注意更新你的todo清单.</reminder>"})
            # # 固定输出的代码结束

if __name__=="__main__":
    # response = client.chat.completions.create(
    #     model=model_name,
    #     messages=message,
    #     stream=True
    # )
    history = []
    act_judge=True
    while True:
        #history=[]
        try:
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role":"system","content":SYSTEM})
        history.append({"role": "user", "content": query})
        agent_loop(history, client)
        response_content = history[-1]["content"]
        if response_content:
            print(response_content)
        # if isinstance(response_content, list):
        #     for block in response_content:
        #         if hasattr(block, "text"):
        #             print(block.text)
        print()
