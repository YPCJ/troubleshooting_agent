#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="${PROJECT_ROOT}/.run"
BACKEND_PID_FILE="${RUN_DIR}/backend.pid"
FRONTEND_PID_FILE="${RUN_DIR}/frontend.pid"
BACKEND_PORT="${AGENT_API_PORT:-8001}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

is_running() {
  local pid="$1"
  if [[ -z "${pid}" ]] || [[ ! "${pid}" =~ ^[0-9]+$ ]]; then
    return 1
  fi
  kill -0 "${pid}" >/dev/null 2>&1
}

stop_one() {
  local name="$1"
  local pid_file="$2"
  if [[ ! -f "${pid_file}" ]]; then
    echo "[${name}] not running (no pid file)"
    return
  fi

  local pid
  pid="$(cat "${pid_file}" 2>/dev/null || true)"
  if ! is_running "${pid}"; then
    echo "[${name}] stale pid file removed (pid=${pid})"
    rm -f "${pid_file}"
    return
  fi

  kill "${pid}"
  for _ in {1..20}; do
    if ! is_running "${pid}"; then
      break
    fi
    sleep 0.2
  done

  if is_running "${pid}"; then
    kill -9 "${pid}"
  fi
  rm -f "${pid_file}"
  echo "[${name}] stopped (pid=${pid})"
}

stop_one "frontend" "${FRONTEND_PID_FILE}"
stop_one "backend" "${BACKEND_PID_FILE}"

kill_port_listeners() {
  local name="$1"
  local port="$2"
  local pids
  pids="$(lsof -ti tcp:${port} 2>/dev/null || true)"
  if [[ -z "${pids}" ]]; then
    return
  fi
  for pid in ${pids}; do
    if is_running "${pid}"; then
      kill "${pid}"
      echo "[${name}] killed listener pid=${pid} on port ${port}"
    fi
  done
}

kill_port_listeners "frontend" "${FRONTEND_PORT}"
kill_port_listeners "backend" "${BACKEND_PORT}"
