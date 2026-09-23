#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${APP_ROOT}"
if [[ ! -x .venv/bin/python || ! -f .env ]]; then
  echo "Run ./install.sh and configure .env first." >&2
  exit 1
fi
exec .venv/bin/python backend/server.py
