#!/usr/bin/env bash
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
RUN_DIR="${BUNDLE_ROOT}/runtime/runs/carla_bridge"
LOG_DIR="${BUNDLE_ROOT}/runtime/logs/carla"
PID_FILE="${RUN_DIR}/bridge.pid"
LOG_FILE="${LOG_DIR}/bridge.log"

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
  [[ "${cmdline}" == *"python3 -m carla_bridge.main"* ]]
}

case "${1:-status}" in
  start)
    install -d "${RUN_DIR}" "${LOG_DIR}"
    if is_running; then
      echo "CARLA bridge already running: pid=$(read_pid) log=${LOG_FILE}"
      exit 0
    fi
    rm -f "${PID_FILE}"
    setsid env CARLA_BRIDGE_CONTROL_TOPIC="${CARLA_BRIDGE_CONTROL_TOPIC:-/apollo/control}" \
      CAGE_BRIDGE_CONTROL_TELEMETRY="${CAGE_BRIDGE_CONTROL_TELEMETRY:-}" \
      "${BUNDLE_ROOT}/scripts/apollo_bridge_exec.sh" \
      python3 -m carla_bridge.main >"${LOG_FILE}" 2>&1 </dev/null &
    pid=$!
    printf '%s\n' "${pid}" >"${PID_FILE}"
    sleep 2
    if ! is_running; then
      echo "CARLA bridge exited during startup; inspect ${LOG_FILE}" >&2
      exit 1
    fi
    echo "CARLA bridge started: pid=${pid} log=${LOG_FILE}"
    ;;
  status)
    if is_running; then
      echo "CARLA bridge running: pid=$(read_pid) log=${LOG_FILE}"
    else
      echo "CARLA bridge stopped"
      exit 1
    fi
    ;;
  stop)
    if ! is_running; then
      rm -f "${PID_FILE}"
      echo "CARLA bridge already stopped"
      exit 0
    fi
    pid="$(read_pid)"
    kill -INT -- "-${pid}" 2>/dev/null || kill -INT "${pid}" 2>/dev/null || true
    for _ in $(seq 1 30); do
      kill -0 "${pid}" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "${pid}" 2>/dev/null; then
      kill -TERM -- "-${pid}" 2>/dev/null || kill -TERM "${pid}" 2>/dev/null || true
      echo "CARLA bridge required SIGTERM after its 30-second cleanup window" >&2
      exit 1
    fi
    rm -f "${PID_FILE}"
    echo "CARLA bridge stopped cleanly"
    ;;
  *)
    echo "usage: $0 {start|status|stop}" >&2
    exit 2
    ;;
esac
