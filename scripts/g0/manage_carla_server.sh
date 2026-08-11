#!/usr/bin/env bash
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
RUN_DIR="${BUNDLE_ROOT}/runtime/runs/carla"
LOG_DIR="${BUNDLE_ROOT}/runtime/logs/carla"
PID_FILE="${RUN_DIR}/server.pid"
LOG_FILE="${LOG_DIR}/server.log"

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
  [[ "${cmdline}" == *"${BUNDLE_ROOT}/runtime/carla/0.9.15/CarlaUE4.sh"* ]]
}

case "${1:-status}" in
  start)
    install -d "${RUN_DIR}" "${LOG_DIR}"
    if is_running; then
      echo "CARLA already running: pid=$(read_pid) log=${LOG_FILE}"
      exit 0
    fi
    rm -f "${PID_FILE}"
    setsid "${BUNDLE_ROOT}/scripts/start_carla_offscreen.sh" \
      >"${LOG_FILE}" 2>&1 </dev/null &
    pid=$!
    printf '%s\n' "${pid}" >"${PID_FILE}"
    sleep 2
    if ! is_running; then
      echo "CARLA exited during startup; inspect ${LOG_FILE}" >&2
      exit 1
    fi
    echo "CARLA started: pid=${pid} log=${LOG_FILE}"
    ;;
  status)
    if is_running; then
      echo "CARLA running: pid=$(read_pid) log=${LOG_FILE}"
    else
      echo "CARLA stopped"
      exit 1
    fi
    ;;
  stop)
    if ! is_running; then
      rm -f "${PID_FILE}"
      echo "CARLA already stopped"
      exit 0
    fi
    pid="$(read_pid)"
    kill -TERM -- "-${pid}" 2>/dev/null || kill -TERM "${pid}" 2>/dev/null || true
    for _ in $(seq 1 30); do
      kill -0 -- "-${pid}" 2>/dev/null || break
      sleep 1
    done
    if kill -0 -- "-${pid}" 2>/dev/null; then
      echo "CARLA did not stop after 30 seconds" >&2
      exit 1
    fi
    rm -f "${PID_FILE}"
    echo "CARLA stopped"
    ;;
  *)
    echo "usage: $0 {start|status|stop}" >&2
    exit 2
    ;;
esac
