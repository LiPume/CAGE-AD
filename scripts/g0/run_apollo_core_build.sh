#!/usr/bin/env bash
set -uo pipefail

BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
LOG_DIR="${BUNDLE_ROOT}/runtime/logs/apollo"
LOG_FILE="${LOG_DIR}/core_build_retry2.log"
STATUS_FILE="${LOG_DIR}/core_build_retry2.status"
LOCK_FILE="${LOG_DIR}/core_build.lock"

mkdir -p "${LOG_DIR}"
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  printf 'another Apollo core build holds %s\n' "${LOCK_FILE}" >&2
  exit 75
fi

write_status() {
  local state="$1"
  local exit_code="$2"
  local finished_at="$3"
  local temporary="${STATUS_FILE}.tmp.$$"
  {
    printf 'state=%s\n' "${state}"
    printf 'pid=%s\n' "$$"
    printf 'started_at=%s\n' "${STARTED_AT}"
    printf 'finished_at=%s\n' "${finished_at}"
    printf 'exit_code=%s\n' "${exit_code}"
    printf 'log=%s\n' "${LOG_FILE}"
  } >"${temporary}"
  mv -f "${temporary}" "${STATUS_FILE}"
}

STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
write_status RUNNING '' ''

set +e
"${BUNDLE_ROOT}/scripts/build_apollo_core.sh" >"${LOG_FILE}" 2>&1
BUILD_EXIT=$?
set -e

FINISHED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if (( BUILD_EXIT == 0 )); then
  write_status SUCCEEDED "${BUILD_EXIT}" "${FINISHED_AT}"
else
  write_status FAILED "${BUILD_EXIT}" "${FINISHED_AT}"
fi
exit "${BUILD_EXIT}"
