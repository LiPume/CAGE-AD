#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DOWNLOAD_ROOT="${BUNDLE_ROOT}/runtime/cache/downloads"
ARCHIVE="${DOWNLOAD_ROOT}/CARLA_0.9.15.tar.gz"
CARLA_ROOT="${BUNDLE_ROOT}/runtime/carla/0.9.15"
URL='https://carla-releases.s3.us-east-005.backblazeb2.com/Linux/CARLA_0.9.15.tar.gz'
EXPECTED_BYTES=8386636048

mkdir -p "${DOWNLOAD_ROOT}" "${CARLA_ROOT}"
if [[ ! -x "${CARLA_ROOT}/CarlaUE4.sh" ]]; then
  if [[ ! -f "${ARCHIVE}" ]] || [[ "$(stat -c %s "${ARCHIVE}")" -ne "${EXPECTED_BYTES}" ]]; then
    aria2c --continue=true --max-connection-per-server=16 --split=16 \
      --min-split-size=16M --file-allocation=none --retry-wait=5 --max-tries=10 \
      --dir="${DOWNLOAD_ROOT}" --out="$(basename "${ARCHIVE}")" "${URL}"
  fi
  [[ "$(stat -c %s "${ARCHIVE}")" -eq "${EXPECTED_BYTES}" ]]
  tar -xzf "${ARCHIVE}" -C "${CARLA_ROOT}"
fi

test -x "${CARLA_ROOT}/CarlaUE4.sh"
sha256sum "${ARCHIVE}"
echo "CARLA 0.9.15 packaged runtime: READY"

