# troubleshooting_agent

troubleshooting_agent 是一个面向故障分析场景的 AI 工具工程。项目主体是 **SBC（天基承载网）故障排查智能体**（[backend/agents/sbc_network_troubleshooting/](backend/agents/sbc_network_troubleshooting)）：基于 LangGraph 实现的受控故障树排查流程，用图约束分支、必查项和停止条件，要求每个结论必须有工具证据支撑，详细设计见 [docs/sbc_network_troubleshooting_langgraph_design.md](docs/sbc_network_troubleshooting_langgraph_design.md)。

支撑这个主体运行的是通用故障诊断 agent（[backend/fault_diagnoses_agent.py](backend/fault_diagnoses_agent.py)）：一个 ReAct 循环 + 工具调用框架，既承载 SBC agent 的混合执行模式，也独立用于更通用的遥测/日志处理、诊断结论生成和故障分析报告输出场景。

## 项目简介

这个仓库包含以下几个部分：
- Python 后端服务：位于 [backend/](backend)
  - [backend/server.py](backend/server.py)：手写的 HTTP + SSE 服务，负责鉴权、会话编排与流式消息
  - [backend/agents/sbc_network_troubleshooting/](backend/agents/sbc_network_troubleshooting)：项目主体，SBC 故障排查 LangGraph 实现
  - [backend/fault_diagnoses_agent.py](backend/fault_diagnoses_agent.py)：通用 ReAct 诊断 agent
  - [backend/tools/](backend/tools)：通用工具注册表（ToolRegistry）
  - [backend/tests/](backend/tests)：后端与 agent 测试
- 前端界面：位于 [frontend/](frontend)，基于 Vite + React 构建，提供多 Session 工作台
- 技能模块：位于 [skills/](skills)，通过 `SKILL.md` 描述和装载，包括 SBC 故障树知识（`sbc_network_troubleshooting`）、报告生成、遥测处理和格式转换等
- 领域知识语料：位于 [knowledge/](knowledge)，是 SBC 故障树技能的案例素材来源
- 早期 CLI 原型：位于 [apps/](apps)（`fault_diagnoses`、`fault_search`、`document_write`、`log_transform`），仍作为本地调试入口保留，内部复用 `backend/` 的 agent 实现
- 其他支持代码与配置：位于 [llm/](llm)（多模型 provider 适配层）、[config/](config)（模型配置）和 [docs/](docs)（设计文档）

## 快速开始

### 1) 创建 Python 虚拟环境

在仓库根目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) 安装前端依赖

```bash
cd frontend
npm install
```

### 3) 启动服务

在仓库根目录执行：

```bash
./start_services.sh
```

这会后台启动后端和前端服务。

如需停止服务：

```bash
./stop_services.sh
```

## 主要入口

- 后端入口：[backend/server.py](backend/server.py)
- 前端入口：[frontend/src/main.tsx](frontend/src/main.tsx)
- 主要页面位于 [frontend/src/views/](frontend/src/views)

## 环境变量配置

仓库根目录下提供了 [.env_template](.env_template) 作为模板文件。
建议按以下方式使用：

```bash
cp .env_template .env
```

然后根据你的实际环境填写 `.env` 中的值。
- 其中敏感项（如 API Key、Token、Secret）请使用你自己的真实值，不要直接提交到 Git
- URL 类配置可以保留默认值或根据实际地址调整
- 本仓库已经将 `.env` 设为忽略文件，避免把本地配置泄露到远程仓库
- `.env_template` 已按当前代码精简为"实际会读取"的变量，主要包含：
  - OpenAI/兼容接口：`api_key`、`base_url`、`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`BASE_URL`、`DASHSCOPE_API_KEY`
  - Gemini：`GEMINI_API_KEY`、`GOOGLE_API_KEY`、`GEMINI_MODEL`
  - 业务参数：`MODEL_PROFILE`、`LLM_PROVIDER_MODULES`、`DATA_URL`、`WEB_SEARCH_URL`
  - 百度搜索：`BAIDU_SEARCH_API_KEY`

## 扩展新的模型 Provider

麒麟 ARM64 环境的 Python 3.12 自带运行时、离线 wheel 打包及安装步骤见 [docs/offline_kylin_arm64.md](docs/offline_kylin_arm64.md)。该交付版本仅保留天基承载网排障与报告，接入内网 OpenAI 兼容模型。

兼容 OpenAI Chat Completions 的服务商可在“模型管理 → 新增服务商连接”中填写 API 根地址和密钥环境变量名，再为该连接创建模型入口。Gemini 继续使用 Google 原生 SDK。完整的调用路径、配置方式和示例见 [llm/README.md](llm/README.md)。

若需接入其他原生协议，可在 `llm/providers/` 实现 `list_models`、`get_model_capabilities`、`chat`、`chat_stream`，调用 `register_provider("provider_id", ProviderClass)` 注册，并将模块导入路径加入 `LLM_PROVIDER_MODULES`。聊天与模型目录统一通过 [llm/providers/registry.py](llm/providers/registry.py) 选择适配器。


## 仓库维护说明

请勿将本地密钥、环境变量文件或生成结果提交到版本控制中。
不要提交 `.env`、`.env.*`、缓存目录、依赖目录和运行产物。
