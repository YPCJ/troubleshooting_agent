#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${APP_ROOT}"
export LD_LIBRARY_PATH="${APP_ROOT}/runtime-libs${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "aarch64" ]]; then
  echo "This package requires Linux aarch64." >&2
  exit 1
fi
if [[ ! -x python/bin/python3.12 || ! -d runtime-libs || ! -d wheelhouse || ! -f requirements-offline-arm64.lock ]]; then
  echo "Incomplete offline package." >&2
  exit 1
fi

python/bin/python3.12 -c 'import ssl, sqlite3, zlib, bz2, lzma, ctypes, ensurepip'
if [[ ! -x .venv/bin/python ]]; then
  python/bin/python3.12 -m venv .venv
fi
PIP_NO_INDEX=1 PIP_NO_CACHE_DIR=1 .venv/bin/python -m pip install \
  --no-index --find-links="${APP_ROOT}/wheelhouse" -r requirements-offline-arm64.lock
.venv/bin/python -m pip check
.venv/bin/python -c 'import langgraph, openai, yaml, requests, pydantic; from langgraph.checkpoint.sqlite import SqliteSaver'

mkdir -p data outputs/sbc
if [[ ! -e .env ]]; then
  cp offline.env.example .env
  chmod 600 .env
fi
touch .venv/.offline-installed
echo "Offline installation complete. Edit ${APP_ROOT}/.env, then run ./run.sh"
