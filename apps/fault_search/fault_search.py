from llm.legacy import legacy_chat_completion, legacy_openai_client
from dotenv import load_dotenv
import subprocess
from pathlib import Path
import os
import json
import re
import yaml
from datetime import datetime
import tool_boxes
import time
import requests
from typing import List, Dict,Any
import shlex
import pandas as pd
import chardet
from tabulate import tabulate
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import ast
from llm.call_tracking import format_model_call_progress


# 加载环境变量，设置时间
now=datetime.now()

PROJECT_ROOT = tool_boxes.find_project_root(Path(__file__).resolve().parent)
dotenv_path = PROJECT_ROOT / ".env"
load_dotenv(override=True, dotenv_path=dotenv_path)
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'FangSong']
plt.rcParams['axes.unicode_minus'] = False
#print(os.getenv("base_url"))

WORKDIR=Path.cwd()  #工作目录
model_name=os.getenv("model_name")
Skills_dir=tool_boxes.resolve_skills_dir(__file__, workdir=WORKDIR, project_root=PROJECT_ROOT)
#data_url='http://localhost:5000/api/external-query'
data_url='http://49.233.215.205:5000/api/external-query'

sample_query="请排查01号卫星在2025-10-28 15:00发生的蓄电池故障的原因，请排查01号卫星在2025-10-28 15:00发生的太阳能电池故障的原因"
sample_query="请查询01号卫星在2025-10-28 15:00到2025-10-28 18:00时间段内的“蓄电池A测点1”的数据并且绘制图表"
sample_query="请读取demo文件夹下面的PACK_3_00E6_ss_20251028_889258497.csv文件，并且解析其表头标题的含义"
sample_query="请使用卫星遥测参数日志格式转换技能，针对skills/format_transform/target/PACK_3_0058_ss_20251024_50397441.csv文件进行日志格式转换"
sample_query="请读取skills/format_transform/reference/standard_log2.csv文件，并且解析其表头标题的含义"
sample_query="请使用卫星遥测参数日志格式转换技能，针对skills/format_transform/target文件夹下的文件进行日志格式转换"
sample_query="01号卫星在2025年10月26日14点左右发生了蓄电池故障。请先查询‘蓄电池D测点1’的数据并且绘制图表。"
sample_query="01号卫星在2025年10月24日18点左右发生了星敏感器故障。请判断是什么原因导致的。"
sample_query="01号卫星在2025年10月24日18点左右发生了星敏感器故障。可能原因有哪些？"

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
在处理你不熟悉的任务时使用你的skill技能来解决问题。你在调用函数工具时，会严格按照要求撰写。
可以采用的skill技能包括：
{Skill_loader.get_descriptions()}

你是一个有记忆的智能体，针对用户的提问，可以根据你的记忆系统资料给用户一些后续操作步骤的建议。但是要注意**你只需要建议步骤，在用户确认之前，不要调用工具执行，不要调用工具执行**。
"""
print(f"智能体首次运行，其初始提示词为：\n{SYSTEM}\n--------------------")
client=legacy_openai_client()

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
        return out[:50000] if out else "(no output)"
    except ValueError as e:
        return f"Error: Invalid command syntax: {e}"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"
    except (FileNotFoundError, OSError) as e:
        return f"Error: {e}"

def memory_search(query:str)->list:
    try:
        #先把所有的记忆文件的yaml部分读进来
        memory_file=[]
        memory_path=os.path.join(os.getcwd(),r"memory/fault")
        memory_list=os.listdir(memory_path)
        #print(f"memory_list:{memory_list}")
        for file in memory_list:
            with open(os.path.join(memory_path,file),"r",encoding="utf-8") as f:
                content=f.read()
                #print(f"content:{content}")
                match = re.match(r"^---\n(.*?)\n---\n(.*)", content, re.DOTALL)
                #print(match)
                if not match:
                    print("没有匹配到yaml部分")
                    continue
                try:
                    abstract = yaml.safe_load(match.group(1)) or {}
                    #print(f"abstract:{abstract}")
                except yaml.YAMLError:
                    abstract = {}
                memory_file.append(abstract)
                #print(f"memory_file:{memory_file}")
        all_memory=memory_file
        #print(f"所有的记忆为:{all_memory}")
        memory_prompt=f"""你是一个卫星互联网故障诊断的记忆检索大师，根据用户的提问，从已有的记忆文件里面检索相关度在80%以上的记忆文件，并且按照相关性排序，选择前5条记忆文件。
        你必须以列表的方式返回选择的记忆文件的文件名，例如['memory_20261031103125.md','memory_20261021103125.md','memory_20261025103125.md']，返回的文件名不要超过5个,列表中的引号需要用单引号。
        已有的记忆文件为：{all_memory}
        记忆文件的字段解释如下：
        memory_name是记忆文件的文件名，
        memory_time是记忆创建的时间，格式为XXX年X月X日。
        memory_background是记忆的背景，不超过100token，简述对话发生的背景。
        memory_abstract是记忆的摘要，不超过200 token，概述记忆中主要内容。
        第二部分是记忆的详细部分，分为两个子模块，分别是记忆主要内容和记忆经验总结。
        """
        memory_history=[]
        memory_history.append({"role":"system","content":memory_prompt})
        memory_history.append({"role":"user","content":query})
        #print(f"memory_history:{memory_history}")
        response = legacy_chat_completion(client,
            model=model_name,
            messages=memory_history,
            max_tokens=10000,
            temperature=0.7
        )
        if response.choices[0].message.content:
            #print(f"response:{response.choices[0].message.content}")
            return response.choices[0].message.content
        else:
            print(f"没有返回值")
            return []

    except Exception as e:
        print(f"memory_search error:{e}")
        return []


def run_read(path: str, limit: int = None) -> str:
    try:
        with open(path,"rb") as f:
            raw=f.read(1000)
        enc = chardet.detect(raw)['encoding'] or 'utf-8'
        print(f"读取的编码格式为:{enc}")
        for enc_try in [enc,"utf-8","gbk","gb2312","latin-1"]:
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
        for enc_try in [enc,"utf-8","gbk","gb2312","latin-1"]:
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

def run_plot_figure(x_data:list,y_data:list,y_label:str=None)->str:
    times = []
    values = []
    time_formats = [
        "%Y-%m-%d %H:%M:%S.%f",  # 带毫秒
        "%Y-%m-%d %H:%M:%S",  # 不带毫秒
        "%Y-%m-%d %H:%M",  # 只有小时分钟
        "%Y/%m/%d %H:%M:%S",  # 斜杠分隔
        "%Y-%m-%d",  # 只有日期
    ]

    # 检查数据长度
    if len(x_data) != len(y_data):
        return f"调用函数时给出的时间点数量为{len(x_data)},给出的值数量为{len(y_data)},数量不一致，请检查。"

    # 解析数据
    for i in range(len(x_data)):
        time_parsed = False
        for time_format in time_formats:
            try:
                t = datetime.strptime(x_data[i], time_format)
                times.append(t)
                values.append(float(y_data[i]))
                time_parsed = True
                break  # 成功解析，跳出格式循环
            except ValueError:
                continue  # 尝试下一个格式

        if not time_parsed:
            print(f"⚠️ 第 {i} 个时间点无法解析: {x_data[i]}")

    # 检查是否有有效数据
    if len(times) == 0 or len(values) == 0:
        return "❌ 没有有效的时间数据可用于绘图"

    if len(times) < 2:
        return f"⚠️ 有效数据点太少 ({len(times)}个)，无法绘制有意义的图表"

    try:
        # 创建图表
        fig, ax = plt.subplots(figsize=(12, 6))

        # 设置标签
        if not y_label:
            y_label = "y"

        # 绘制折线图
        ax.plot(times, values, 'b-o', markersize=4, linewidth=1.5, label=y_label)

        # 设置标题和标签
        title_str = f'Satellite {y_label} data'
        ax.set_title(title_str, fontsize=14, fontweight='bold')
        ax.set_xlabel('Time', fontsize=12)
        ax.set_ylabel('Value', fontsize=12)

        # 格式化x轴时间
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.xticks(rotation=45)

        # 添加网格和图例
        ax.grid(True, alpha=0.3)
        ax.legend()

        # 自动调整布局
        plt.tight_layout()

        # 保存图片
        output_dir = './plot'
        os.makedirs(output_dir, exist_ok=True)  # 确保目录存在
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        output_path = os.path.join(output_dir, f"{timestamp}.png")

        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()  # 关闭图表，释放内存

        print(f"Chart saved to: {output_path}")

        # 计算统计信息
        min_val = min(values)
        max_val = max(values)
        avg_val = sum(values) / len(values)

        output = f"""已经成功完成了图表生成，图表保存在{output_path}，请查看。
            图表中共绘制了时间点{len(times)}个，时间范围为{times[0].strftime('%Y-%m-%d %H:%M:%S')}~{times[-1].strftime('%Y-%m-%d %H:%M:%S')}，
            y轴的最大值为{max_val:.2f},最小值为{min_val:.2f},平均值为{avg_val:.2f}。
            """
        print(output)
        return output

    except Exception as e:
        return f"在绘制图表时发生错误: {str(e)}"



#建立工具的函数
TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw["path"], kw.get("limit")),
    "read_csv": lambda **kw:run_read_csv(kw["path"],kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "data_query":lambda **kw:run_data_query(kw["sat_id"],kw["para_name"],kw["start_time"],kw["end_time"]),
    "load_skills": lambda **kw: Skill_loader.get_content(kw["name"]),
    "plot_figure":lambda **kw:run_plot_figure(kw["x_data"],kw["y_data"],kw.get("y_label"))
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
                    },"required":"name"}
             }},

    {"type": "function",
                 "function": {
                     "name": "plot_figure", "description": "绘制时序数据折线图，x_data为时间点列表，y_data为对应的值列表，y_label为y轴的标签",
                     "parameters": {"type": "object", "properties": {
                         "x_data": {"type": "array",
                                    "items":{"type":"string","description":"时间点，格式为\'YYYY-MM-DD hh:mm:ss\'"},
                                    "description": "时间点列表，作为x坐标"},
                         "y_data": {"type": "array",
                                    "itmes":{"type":"number","description":"对应的参数值"},
                                    "description": "对应的参数值列表，作为y坐标,y_data和x_data的长度必须一致"},
                         "y_label": {"type": "string", "description": "y轴的标签，一般为中文"}
                     },"required":["x_data","y_data"]}
                 }}
]

def agent_loop(messages: list,client:Any):
    rounds_since_todo = 0
    llm_count=0
    while True:
        #编写了两套代码，一套是固定输出，一套是流式输出
        #流式输出的代码开始
        full_content=""
        full_tool={}
        llm_count+=1
        id_print=0
        name_print=0
        arg_print=0
        print(f"______________________{format_model_call_progress(llm_count)}_________________________")
        response=legacy_chat_completion(client,
            model=model_name,
            messages=messages,
            max_tokens=10000,
            tools=Tools,
            temperature=0.7,
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
                            if not id_print:
                                print(f"\n本次工具调用的id是:")
                                id_print=1
                            print(tool_chunk.id,end="",flush=True)
                        if tool_chunk.function and tool_chunk.function.name:
                            full_tool[idx]["function"]["name"]+=tool_chunk.function.name
                            if not name_print:
                                print(f"\n本次工具调用的名称是:")
                                name_print = 1
                            print(tool_chunk.function.name,end="",flush=True)
                        if tool_chunk.function and tool_chunk.function.arguments:
                            full_tool[idx]["function"]["arguments"]+=tool_chunk.function.arguments
                            if not arg_print:
                                print(f"\n本次工具调用的参数为:")
                                arg_print = 1
                            print(tool_chunk.function.arguments,end="",flush=True)
                # if delta.tool_calls:
                #     print(f"本次调用的工具id为：{full_tool[idx]['id']}\n", flush=True)
                #     print(f"本次调用的工具名称为：{full_tool[idx]['function']['name']}\n", flush=True)
                #     print(f"本次调用的工具参数为：{full_tool[idx]['function']['arguments']}\n",flush=True)
                            #print(tool_chunk.function.arguments,end="",flush=True)
        print("\n________________________________本次大模型输出结束_____________________________________")
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
                #print(f"{block.get('function')}")
                tool_name=block.get("function").get("name")
                handler = TOOL_HANDLERS.get(block.get("function").get("name"))
                argument_json = json.loads(block.get("function").get("arguments"))
                try:
                    output = handler(**argument_json) if handler else f"Unknown tool: {block.name}"
                except Exception as e:
                    output = f"Error:{e}"
                #print(f"> {tool_name}:")
                print(f">>>>>>>本次工具调用的结果为：")
                print(output[:500])
                if tool_name == "todo":
                    used_todo = True
                if tool_name == "load_skills":
                    print(f"\n本次运行中，加载了技能文件，内容为{output}\n")
                messages.append({"role": "tool", "tool_call_id": block.get("id"), "content": json.dumps(output)})
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
    user_turn=True
    history = []
    memory_load=True
    while user_turn:
        #history=[]
        memory_demo_path=os.path.join(os.getcwd(),r"memory/demo/demo.md")
        memory_fact_path=os.path.join(os.getcwd(),r"memory/fact/fact.md")
        memory_fault_path=os.path.join(os.getcwd(),r"memory/fault")
        try:
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        if query.strip().lower()=="save":
            #将当前的用户记录保存为记忆
            save_history=[]
            try:
                with open(memory_demo_path, "r", encoding="utf-8") as f_demo:
                    f=f_demo.read()
                    memoryname="memory_"+datetime.now().strftime("%Y%m%d%H%M%S")+".md"
                    memory_prompt=f"""你是一个用户记忆归纳总结专家，工作在目录{os.getcwd()}下，你运行于windows环境。你可以将智能体与用户的对话记录总结为用户记忆，你关注用户对话中的以下几个内容:
                    (1) 事实性内容，例如目前在轨卫星数量，在轨卫星的属性等等，这些事实性内容是关于整个系统的，而不是关于某个具体的任务的。
                    (2) 故障排查及故障分析的经验记忆。
                    ## 具体要求：
                    ### 1. 事实性内容
                    事实性内容是指用户对话中提到的关于整个系统的信息，例如目前在轨卫星数量，在轨卫星的属性等等。每次对话的事实性内容不要超过200token，如果本次对话没有事实性内容，无需写入任何东西。
                    ### 2. 故障排查及故障分析的经验记忆
                    故障排查的记忆文件以yaml格式进行存储，文件分为两个部分，用---进行分割。
                    第一部分是记忆的概述部分，以字典的方式存放，一共有四个键，分别是memory_name,memory_time,memory_background,memory_abstract.
                    memory_name是记忆文件的文件名，
                    memory_time是记忆创建的时间，格式为XXX年X月X日。
                    memory_background是记忆的背景，不超过100token，简述对话发生的背景。
                    memory_abstract是记忆的摘要，不超过200 token，概述记忆中主要内容。
                    第二部分是记忆的详细部分，分为两个子模块，分别是记忆主要内容和记忆经验总结。
                    记忆主要内容描述用户在进行故障排查或者数据分析时的主要步骤。记忆经验总结描述用户在进行故障排查或者数据分析时遇到的困难和解决方案。
                    记忆文件的模板格式可以参考下面的示例：**{f}**。
                    ### 3. 存储方式
                    对于事实性内容，统一存放在一个记忆文件里面，记忆文件的地址为：os.getcwd()+r"/memory/fact/fact.md"。每次添加在已有文件的末尾加入新增事实记忆内容。
                    对于故障排查及故障分析的经验记忆，每一次会话（用户要求保存的）都生成一个独立的记忆文件，保存在os.getcwd()+r"/memory/fault文件夹下面。记忆文件的命名方式为系统当前时间（memory_%y%M%d%H%M%S.md）,参考{memoryname}的命名方式。                    
                    
                    """

                    save_history.append({"role":"system","content":memory_prompt})
                    save_history.append({"role":"user","content":f"请按照要求提炼智能体与用户的历史对话记录形成记忆：{history}"})
                    #print(history)
                    agent_loop(save_history,client)
                    break

            except Exception as e:
                print(f"保存记忆失败，错误信息为：{e}")

        #正常的循环过程
        start_time = datetime.now()
        print(start_time)
        history.append({"role":"system","content":SYSTEM})
        history.append({"role": "user", "content": query})
        if memory_load:
            try:
                #先检索相关记忆
                with open(memory_fact_path,"r",encoding="utf-8") as f_fact:
                    fact=f_fact.read()
                history.append({"role":"assistant","content":f"经过智能体记忆检索，现有的事实类记忆为：{fact}"})
                #print(fact)
                fault_file_str=memory_search(query)
                print(f"选择的记忆文件为：{fault_file_str}")
                fault_file_list=ast.literal_eval(fault_file_str)
                for fault_file in fault_file_list:
                    with open(os.path.join(memory_fault_path,fault_file),"r",encoding="utf-8") as f_fault:
                        fault=f_fault.read()
                        history.append({"role":"assistant","content":f"经过智能体记忆检索，可供参考的故障类记忆为：{fault}"})
                memory_load=False
            except Exception as e:
                print(f"检索记忆失败，错误信息为：{e}")


        agent_loop(history, client)
        response_content = history[-1]["content"]
        end_time = datetime.now()
        print(f"模型调用结束时间为:{end_time},耗时为:{end_time - start_time}")
        #if response_content:
            # print(response_content)
        # if isinstance(response_content, list):
        #     for block in response_content:
        #         if hasattr(block, "text"):
        #             print(block.text)
