#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv"
TARGET_PYTHON_MM="3.14"
PYTHON_CMD=""

if command -v python3.14 >/dev/null 2>&1; then
  PYTHON_CMD="python3.14"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_CMD="python3"
else
  echo "[ERROR] python3 not found in PATH."
  echo "Please install Python ${TARGET_PYTHON_MM} first, then rerun this script."
  exit 1
fi

if [[ -x "${VENV_DIR}/bin/python" ]]; then
  EXISTING_VERSION="$("${VENV_DIR}/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  if [[ "${EXISTING_VERSION}" != "${TARGET_PYTHON_MM}" ]]; then
    echo "[ERROR] Existing .venv uses Python ${EXISTING_VERSION}, expected ${TARGET_PYTHON_MM}."
    echo "Please remove .venv manually, then rerun this script."
    exit 1
  fi
fi

"${PYTHON_CMD}" -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/python" - <<'PY'
import sys
version = f"{sys.version_info.major}.{sys.version_info.minor}"
if version != "3.14":
    raise SystemExit(f"[ERROR] .venv Python version is {version}, expected 3.14.")
print(f"[OK] .venv Python version: {version}")
PY

"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/pip" install -r "${PROJECT_ROOT}/requirements.txt"

echo "[OK] Python 3.14 virtual environment is ready: ${VENV_DIR}"
echo "[NEXT] Activate it with: source ${VENV_DIR}/bin/activate"
