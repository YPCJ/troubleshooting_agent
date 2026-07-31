#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="${PROJECT_ROOT}/.run"
BACKEND_PID_FILE="${RUN_DIR}/backend.pid"
FRONTEND_PID_FILE="${RUN_DIR}/frontend.pid"
BACKEND_LOG_FILE="${RUN_DIR}/backend.log"
FRONTEND_LOG_FILE="${RUN_DIR}/frontend.log"

BACKEND_HOST="${AGENT_API_HOST:-127.0.0.1}"
BACKEND_PORT="${AGENT_API_PORT:-8001}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"

is_running() {
  local pid="$1"
  kill -0 "${pid}" >/dev/null 2>&1
}

start_backend() {
  if [[ -f "${BACKEND_PID_FILE}" ]]; then
    local pid
    pid="$(cat "${BACKEND_PID_FILE}")"
    if is_running "${pid}"; then
      echo "[backend] already running (pid=${pid})"
      return
    fi
    rm -f "${BACKEND_PID_FILE}"
  fi

  if [[ ! -x "${PYTHON_BIN}" ]]; then
    echo "[backend] missing ${PYTHON_BIN}"
    exit 1
  fi

  (
    cd "${PROJECT_ROOT}"
    AGENT_API_HOST="${BACKEND_HOST}" AGENT_API_PORT="${BACKEND_PORT}" \
      nohup "${PYTHON_BIN}" "${PROJECT_ROOT}/backend/server.py" >>"${BACKEND_LOG_FILE}" 2>&1 &
    echo $! >"${BACKEND_PID_FILE}"
  )
  echo "[backend] started (pid=$(cat "${BACKEND_PID_FILE}"), http://${BACKEND_HOST}:${BACKEND_PORT})"
}

start_frontend() {
  if [[ -f "${FRONTEND_PID_FILE}" ]]; then
    local pid
    pid="$(cat "${FRONTEND_PID_FILE}")"
    if is_running "${pid}"; then
      echo "[frontend] already running (pid=${pid})"
      return
    fi
    rm -f "${FRONTEND_PID_FILE}"
  fi

  (
    cd "${PROJECT_ROOT}/frontend"
    nohup npm run dev -- --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}" >>"${FRONTEND_LOG_FILE}" 2>&1 &
    echo $! >"${FRONTEND_PID_FILE}"
  )
  echo "[frontend] started (pid=$(cat "${FRONTEND_PID_FILE}"), http://${FRONTEND_HOST}:${FRONTEND_PORT})"
}

mkdir -p "${RUN_DIR}"
touch "${BACKEND_LOG_FILE}" "${FRONTEND_LOG_FILE}"

start_backend
start_frontend

echo "logs:"
echo "  backend:  ${BACKEND_LOG_FILE}"
echo "  frontend: ${FRONTEND_LOG_FILE}"
