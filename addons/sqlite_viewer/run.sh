#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${APP_ROOT}/.venv/bin/python"
if [[ ! -x "${PYTHON}" ]]; then
  echo "找不到包内虚拟环境。请先在安装目录运行 ./install.sh。" >&2
  exit 1
fi
export LD_LIBRARY_PATH="${APP_ROOT}/runtime-libs${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
exec "${PYTHON}" "${APP_ROOT}/addons/sqlite_viewer/viewer.py" "$@"
