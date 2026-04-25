#!/usr/bin/env bash
set -euo pipefail

KEYFILE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/mongo-keyfiles"
KEYFILE_PATH="${KEYFILE_DIR}/rs0.key"

mkdir -p "${KEYFILE_DIR}"

if [[ -f "${KEYFILE_PATH}" ]]; then
  current_mode="$(stat -f "%Lp" "${KEYFILE_PATH}" 2>/dev/null || stat -c "%a" "${KEYFILE_PATH}")"
  if [[ "${current_mode}" == "400" ]]; then
    echo "keyfile already exists at ${KEYFILE_PATH}; not overwriting" >&2
    exit 0
  fi

  chmod 400 "${KEYFILE_PATH}"
  chown 999:999 "${KEYFILE_PATH}" 2>/dev/null || true
  echo "keyfile already exists at ${KEYFILE_PATH}; fixed permissions, not overwriting" >&2
  exit 0
fi

openssl rand -base64 756 > "${KEYFILE_PATH}"
chmod 400 "${KEYFILE_PATH}"
chown 999:999 "${KEYFILE_PATH}" 2>/dev/null || true

echo "wrote ${KEYFILE_PATH}"
