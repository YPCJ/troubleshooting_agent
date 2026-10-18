#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${APP_ROOT}"
if [[ ! -x .venv/bin/python || ! -f .env ]]; then
  echo "Run ./install.sh and configure .env first." >&2
  exit 1
fi
export LD_LIBRARY_PATH="${APP_ROOT}/runtime-libs${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
exec .venv/bin/python backend/server.py
