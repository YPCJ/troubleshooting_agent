#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${APP_ROOT}"

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "aarch64" ]]; then
  echo "This package requires Linux aarch64." >&2
  exit 1
fi
if [[ ! -x python/bin/python3.12 || ! -d wheelhouse || ! -f requirements-offline-arm64.lock ]]; then
  echo "Incomplete offline package: Python 3.12, wheelhouse or lockfile is missing." >&2
  exit 1
fi
if [[ -f .venv/.offline-installed ]]; then
  echo "Already installed. Edit .env and run ./run.sh"
  exit 0
fi

if [[ ! -x .venv/bin/python ]]; then
  python/bin/python3.12 -m venv .venv
fi
PIP_NO_INDEX=1 PIP_NO_CACHE_DIR=1 .venv/bin/python -m pip install \
  --no-index --find-links="${APP_ROOT}/wheelhouse" -r requirements-offline-arm64.lock
.venv/bin/python -m pip check
.venv/bin/python -c 'import langgraph, openai, yaml, requests, pydantic; from langgraph.checkpoint.sqlite import SqliteSaver'
touch .venv/.offline-installed
mkdir -p data outputs/sbc
if [[ ! -e .env ]]; then
  cp offline.env.example .env
  chmod 600 .env
fi
echo "Installed without network access. Edit ${APP_ROOT}/.env, then run ./run.sh"
