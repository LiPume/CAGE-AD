#!/usr/bin/env bash
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
RUN_DIR="${BUNDLE_ROOT}/runtime/runs/apollo_a1"
PID_FILE="${RUN_DIR}/stack.pid"

read_pid() {
  [[ -s "${PID_FILE}" ]] || return 1
  local pid
  pid="$(<"${PID_FILE}")"
  [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
  printf '%s\n' "${pid}"
}

is_running() {
  local pid
  pid="$(read_pid)" || return 1
  kill -0 "${pid}" 2>/dev/null || return 1
  local cmdline
  cmdline="$(tr '\0' ' ' <"/proc/${pid}/cmdline")" || return 1
  [[ "${cmdline}" == *"run_a1_apollo_stack.sh"* ]]
}

case "${1:-status}" in
  start)
    install -d "${RUN_DIR}"
    if is_running; then
      echo "Apollo A1 stack already running: pid=$(read_pid)"
      exit 0
    fi
    rm -f "${PID_FILE}"
    setsid "${BUNDLE_ROOT}/scripts/run_a1_apollo_stack.sh" </dev/null &
    pid=$!
    printf '%s\n' "${pid}" >"${PID_FILE}"
    sleep 3
    if ! is_running; then
      echo "Apollo A1 stack exited during startup; inspect runtime/logs/apollo/a1_pnc.log" >&2
      exit 1
    fi
    echo "Apollo A1 stack started: pid=${pid}"
    ;;
  status)
    if is_running; then
      echo "Apollo A1 stack running: pid=$(read_pid)"
    else
      echo "Apollo A1 stack stopped"
      exit 1
    fi
    ;;
  stop)
    if ! is_running; then
      rm -f "${PID_FILE}"
      echo "Apollo A1 stack already stopped"
      exit 0
    fi
    pid="$(read_pid)"
    kill -INT -- "-${pid}" 2>/dev/null || kill -INT "${pid}" 2>/dev/null || true
    for _ in $(seq 1 30); do
      kill -0 "${pid}" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "${pid}" 2>/dev/null; then
      echo "Apollo A1 stack did not stop after 30 seconds" >&2
      exit 1
    fi
    rm -f "${PID_FILE}"
    echo "Apollo A1 stack stopped cleanly"
    ;;
  *)
    echo "usage: $0 {start|status|stop}" >&2
    exit 2
    ;;
esac
