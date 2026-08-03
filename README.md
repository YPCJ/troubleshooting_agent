# fault_assistant_AI

fault_assistant_AI 是一个面向故障分析场景的 AI 工具工程，主要用于处理遥测/日志数据、生成诊断结论，并输出初步故障分析报告。

## 项目简介

这个仓库包含以下几个部分：
- Python 后端服务：位于 [backend/](/Users/ypcj/GIT/fault_assistant_AI/backend)，负责数据处理与代理编排
- 前端界面：位于 [frontend/](/Users/ypcj/GIT/fault_assistant_AI/frontend)，基于 Vite + React 构建
- 技能模块：位于 [skills/](/Users/ypcj/GIT/fault_assistant_AI/skills)，用于报告生成、遥测处理和格式转换
- 其他支持代码与配置：位于 [apps/](/Users/ypcj/GIT/fault_assistant_AI/apps)、[llm/](/Users/ypcj/GIT/fault_assistant_AI/llm)、[config/](/Users/ypcj/GIT/fault_assistant_AI/config) 和 [docs/](/Users/ypcj/GIT/fault_assistant_AI/docs)

## 快速开始

### 1) 创建 Python 虚拟环境

```bash
cd /Users/ypcj/GIT/fault_assistant_AI
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

- 后端入口：[backend/server.py](/Users/ypcj/GIT/fault_assistant_AI/backend/server.py)
- 前端入口：[frontend/src/main.tsx](/Users/ypcj/GIT/fault_assistant_AI/frontend/src/main.tsx)
- 主要页面位于 [frontend/src/views/](/Users/ypcj/GIT/fault_assistant_AI/frontend/src/views)

## 环境变量配置

项目根目录下提供了 [.env_template](/Users/ypcj/GIT/fault_assistant_AI/.env_template) 作为模板文件。
建议按以下方式使用：

```bash
cp .env_template .env
```

然后根据你的实际环境填写 `.env` 中的值。
- 其中敏感项（如 API Key、Token、Secret）请使用你自己的真实值，不要直接提交到 Git
- URL 类配置可以保留默认值或根据实际地址调整
- 本仓库已经将 `.env` 设为忽略文件，避免把本地配置泄露到远程仓库

## 仓库维护说明

请勿将本地密钥、环境变量文件或生成结果提交到版本控制中。
不要提交 `.env`、`.env.*`、缓存目录、依赖目录和运行产物。