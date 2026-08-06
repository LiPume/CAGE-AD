#!/usr/bin/env bash
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
LAUNCH_FILE="${BUNDLE_ROOT}/runtime/apollo_g0/a1_pnc.launch"
LOG_DIR="${BUNDLE_ROOT}/runtime/logs/apollo"
SEMANTIC_LOG="${LOG_DIR}/a1_semantic.log"
PNC_LOG="${LOG_DIR}/a1_pnc.log"
semantic_pid=""
pnc_pid=""

cleanup() {
  trap - EXIT INT TERM
  if [[ -n "${pnc_pid}" ]] && kill -0 "${pnc_pid}" 2>/dev/null; then
    "${BUNDLE_ROOT}/scripts/apollo_host_exec.sh" cyber_launch stop "${LAUNCH_FILE}" \
      >>"${PNC_LOG}" 2>&1 || true
    kill -INT "${pnc_pid}" 2>/dev/null || true
  fi
  if [[ -n "${semantic_pid}" ]] && kill -0 "${semantic_pid}" 2>/dev/null; then
    kill -INT "${semantic_pid}" 2>/dev/null || true
  fi
  [[ -z "${pnc_pid}" ]] || wait "${pnc_pid}" 2>/dev/null || true
  [[ -z "${semantic_pid}" ]] || wait "${semantic_pid}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

install -d "${LOG_DIR}"
"${BUNDLE_ROOT}/scripts/apollo_host_exec.sh" \
  python3 "${BUNDLE_ROOT}/scripts/a1_semantic_heartbeat.py" \
  >"${SEMANTIC_LOG}" 2>&1 &
semantic_pid=$!

"${BUNDLE_ROOT}/scripts/apollo_host_exec.sh" cyber_launch start "${LAUNCH_FILE}" \
  >"${PNC_LOG}" 2>&1 &
pnc_pid=$!

wait "${pnc_pid}"
