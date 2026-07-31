#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "[ERROR] ${PYTHON_BIN} not found."
  echo "Run ./scripts/setup_py311_venv.sh first."
  exit 1
fi

PY_VERSION="$("${PYTHON_BIN}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "${PY_VERSION}" != "3.14" ]]; then
  echo "[ERROR] .venv Python version is ${PY_VERSION}, expected 3.14."
  echo "Recreate environment with ./scripts/setup_py311_venv.sh"
  exit 1
fi

export AGENT_API_HOST="${AGENT_API_HOST:-127.0.0.1}"
export AGENT_API_PORT="${AGENT_API_PORT:-8001}"

exec "${PYTHON_BIN}" "${PROJECT_ROOT}/backend/server.py"
