#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CPYTHON_VERSION="${CPYTHON_VERSION:?Set CPYTHON_VERSION to an official 3.12.x release}"
CPYTHON_TARBALL="${CPYTHON_TARBALL:?Set CPYTHON_TARBALL to the official Python source archive path}"
OUTPUT_DIR="${OUTPUT_DIR:-${PROJECT_ROOT}/offline-packages}"

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "aarch64" ]]; then
  echo "Build on Linux aarch64 matching the target Kylin release." >&2
  exit 1
fi
if [[ ! "${CPYTHON_VERSION}" =~ ^3\.12\.[0-9]+$ ]]; then
  echo "Only CPython 3.12.x is supported." >&2
  exit 1
fi
if [[ ! -f "${CPYTHON_TARBALL}" || ! -f "${PROJECT_ROOT}/frontend/dist/index.html" ]]; then
  echo "Python source tarball or built frontend/dist is missing." >&2
  exit 1
fi
if grep -R -q 'http://127.0.0.1:8001' "${PROJECT_ROOT}/frontend/dist"; then
  echo "Frontend/dist still has a loopback API URL; rebuild with VITE_API_BASE_URL unset." >&2
  exit 1
fi
if [[ ! -f "${PROJECT_ROOT}/data/sbc_simulation_20260808.db" ]]; then
  echo "The SBC simulation database is missing." >&2
  exit 1
fi
if [[ -n "${CPYTHON_SHA256:-}" ]]; then
  printf '%s  %s\n' "${CPYTHON_SHA256}" "${CPYTHON_TARBALL}" | sha256sum -c -
fi

BUILD_ROOT="$(mktemp -d)"
trap 'rm -rf "${BUILD_ROOT}"' EXIT
STAGE="${BUILD_ROOT}/package"
PYTHON_ROOT="${STAGE}/python"
mkdir -p "${STAGE}" "${OUTPUT_DIR}"
tar -xf "${CPYTHON_TARBALL}" -C "${BUILD_ROOT}"
SOURCE_DIR="${BUILD_ROOT}/Python-${CPYTHON_VERSION}"
if [[ ! -f "${SOURCE_DIR}/configure" ]]; then
  echo "Python source archive has an unexpected layout." >&2
  exit 1
fi

(
  cd "${SOURCE_DIR}"
  ./configure --prefix="${PYTHON_ROOT}" --with-ensurepip=install
  make -j"$(getconf _NPROCESSORS_ONLN)"
  make altinstall
)
"${PYTHON_ROOT}/bin/python3.12" -c 'import ssl, sqlite3, zlib, bz2, lzma, ctypes, ensurepip; print(ssl.OPENSSL_VERSION)'
cp "${SOURCE_DIR}/LICENSE" "${STAGE}/PYTHON-LICENSE"
rm -rf "${PYTHON_ROOT}/lib/python3.12/test" \
  "${PYTHON_ROOT}/lib/python3.12/idlelib" \
  "${PYTHON_ROOT}/lib/python3.12/tkinter" \
  "${PYTHON_ROOT}/lib/python3.12/turtledemo"

cp -R "${PROJECT_ROOT}/backend" "${PROJECT_ROOT}/llm" "${STAGE}/"
mkdir -p "${STAGE}/frontend" "${STAGE}/skills" "${STAGE}/data" "${STAGE}/outputs/sbc"
cp -R "${PROJECT_ROOT}/frontend/dist" "${STAGE}/frontend/"
cp -R "${PROJECT_ROOT}/skills/sbc_network_troubleshooting" "${PROJECT_ROOT}/skills/sbc_troubleshooting_report" "${STAGE}/skills/"
cp "${PROJECT_ROOT}/tool_boxes.py" "${PROJECT_ROOT}/requirements-offline-arm64.txt" "${STAGE}/"
cp "${PROJECT_ROOT}/scripts/offline/install.sh" "${PROJECT_ROOT}/scripts/offline/run.sh" "${STAGE}/"
cp "${PROJECT_ROOT}/scripts/offline/offline.env.example" "${STAGE}/"
chmod +x "${STAGE}/install.sh" "${STAGE}/run.sh"

# Keep only the production UI and the two SBC skills. No Node runtime, source
# datasets, development tests, generated outputs, or user credentials are shipped.
rm -rf "${STAGE}/skills/sbc_network_troubleshooting/output" "${STAGE}/skills/sbc_troubleshooting_report/output"
rm -rf "${STAGE}/backend/tests"
find "${STAGE}" -type d -name __pycache__ -prune -exec rm -rf {} +
find "${STAGE}" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
"${PYTHON_ROOT}/bin/python3.12" -c 'import sqlite3, sys; src=sqlite3.connect(sys.argv[1]); dst=sqlite3.connect(sys.argv[2]); src.backup(dst); dst.close(); src.close()' \
  "${PROJECT_ROOT}/data/sbc_simulation_20260808.db" "${STAGE}/data/sbc_simulation_20260808.db"

mkdir -p "${STAGE}/wheelhouse"
"${PYTHON_ROOT}/bin/python3.12" -m pip wheel --only-binary=:all: \
  --wheel-dir "${STAGE}/wheelhouse" -r "${STAGE}/requirements-offline-arm64.txt"
"${PYTHON_ROOT}/bin/python3.12" -m venv "${BUILD_ROOT}/verify-venv"
PIP_NO_INDEX=1 PIP_NO_CACHE_DIR=1 "${BUILD_ROOT}/verify-venv/bin/python" -m pip install \
  --no-index --find-links="${STAGE}/wheelhouse" -r "${STAGE}/requirements-offline-arm64.txt"
"${BUILD_ROOT}/verify-venv/bin/python" -m pip freeze > "${STAGE}/requirements-offline-arm64.lock"
"${BUILD_ROOT}/verify-venv/bin/python" -m pip check
PYTHONPATH="${STAGE}" "${BUILD_ROOT}/verify-venv/bin/python" -c \
  'import backend.agents.sbc_network_troubleshooting.graph; import skills.sbc_troubleshooting_report.scripts.generate_report; import llm.providers.openai_provider'

# This records the build platform. Build on the oldest supported target image:
# binaries linked on newer glibc cannot safely run on older Kylin releases.
{
  echo "CPython: ${CPYTHON_VERSION}"
  echo "Architecture: $(uname -m)"
  echo "OS: $(cat /etc/os-release | head -6 | tr '\n' ' ')"
  echo "glibc: $(getconf GNU_LIBC_VERSION)"
} > "${STAGE}/BUILD-INFO.txt"

PACKAGE="${OUTPUT_DIR}/troubleshooting-sbc-kylin-arm64-py${CPYTHON_VERSION}.tar.gz"
tar -C "${STAGE}" -czf "${PACKAGE}" .
(cd "${OUTPUT_DIR}" && sha256sum "$(basename "${PACKAGE}")") > "${PACKAGE}.sha256"
du -h "${PACKAGE}"
echo "Package: ${PACKAGE}"
