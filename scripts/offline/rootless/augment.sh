#!/usr/bin/env bash
set -euo pipefail

STAGE="${1:?Pass the extracted package directory}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$(uname -m)" != "aarch64" || "$(getconf GNU_LIBC_VERSION)" != "glibc 2.31" ]]; then
  echo "Run on the ARM64 glibc 2.31 build container." >&2
  exit 1
fi
if [[ ! -x "${STAGE}/python/bin/python3.12" || ! -d "${STAGE}/wheelhouse" ]]; then
  echo "Expected an extracted offline package." >&2
  exit 1
fi

# Installation uses prebuilt wheels, so headers, static libraries and bytecode
# caches from the build machine are unnecessary in the delivered runtime.
rm -rf "${STAGE}/python/include"
rm -f "${STAGE}/python/lib/libpython3.12.a"
find "${STAGE}/python/lib/python3.12" -type f -name 'libpython3.12.a' -delete
find "${STAGE}" -type d -name __pycache__ -prune -exec rm -rf {} +
find "${STAGE}" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

mkdir -p "${STAGE}/runtime-libs" "${STAGE}/licenses/runtime"
for soname in \
  libbz2.so.1.0 libcrypt.so.1 libcrypto.so.1.1 libffi.so.7 \
  liblzma.so.5 libncursesw.so.6 libnsl.so.1 libpanelw.so.6 \
  libreadline.so.8 libsqlite3.so.0 libssl.so.1.1 libtinfo.so.6 \
  libuuid.so.1 libz.so.1; do
  path="/lib/aarch64-linux-gnu/${soname}"
  if [[ ! -f "${path}" ]]; then
    echo "Missing runtime library: ${path}" >&2
    exit 1
  fi
  cp -L "${path}" "${STAGE}/runtime-libs/${soname}"
done

for package in libbz2-1.0 libcrypt1 libffi7 liblzma5 libncursesw6 libnsl1 \
  libpanelw6 libreadline8 libsqlite3-0 libssl1.1 libtinfo6 libuuid1 zlib1g; do
  notice="/usr/share/doc/${package}/copyright"
  if [[ -f "${notice}" ]]; then
    cp "${notice}" "${STAGE}/licenses/runtime/${package}.copyright"
  fi
done

cp "${SCRIPT_DIR}/install.sh" "${STAGE}/install.sh"
cp "${SCRIPT_DIR}/run.sh" "${STAGE}/run.sh"
chmod 755 "${STAGE}/install.sh" "${STAGE}/run.sh"
