# fault_assistant_AI

fault_assistant_AI is a small AI-assisted fault analysis workspace for processing telemetry/log data, generating diagnostic insights, and producing preliminary fault analysis reports.

## Project overview

The repository combines:
- Python backend services under [backend/](/Users/ypcj/GIT/fault_assistant_AI/backend) for data processing and agent orchestration
- A Vite + React frontend under [frontend/](/Users/ypcj/GIT/fault_assistant_AI/frontend) for interacting with the project
- Skill modules under [skills/](/Users/ypcj/GIT/fault_assistant_AI/skills) for report generation, telemetry processing, and formatting
- Supporting utilities and configs under [apps/](/Users/ypcj/GIT/fault_assistant_AI/apps), [llm/](/Users/ypcj/GIT/fault_assistant_AI/llm), [config/](/Users/ypcj/GIT/fault_assistant_AI/config), and [docs/](/Users/ypcj/GIT/fault_assistant_AI/docs)

## Quick start

### 1) Python environment

```bash
cd /Users/ypcj/GIT/fault_assistant_AI
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Frontend dependencies

```bash
cd frontend
npm install
```

### 3) Start services

From the repository root:

```bash
./start_services.sh
```

This will launch the backend and frontend in the background.

To stop them:

```bash
./stop_services.sh
```

## Development notes

- The backend entrypoint is [backend/server.py](/Users/ypcj/GIT/fault_assistant_AI/backend/server.py)
- The frontend entrypoint is [frontend/src/main.tsx](/Users/ypcj/GIT/fault_assistant_AI/frontend/src/main.tsx)
- The main UI and workflow views live under [frontend/src/views/](/Users/ypcj/GIT/fault_assistant_AI/frontend/src/views)

## Repository hygiene

Keep local secrets and environment-specific settings out of version control.
Do not commit files such as `.env`, `.env.*`, local caches, or generated output directories.
