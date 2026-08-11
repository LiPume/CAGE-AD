#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${1:?usage: $0 RUN_ID REPAIR_STATE_ROOT REPAIR_DATA_ROOT}"
REPAIR_STATE_ROOT="${2:?}"
REPAIR_DATA_ROOT="${3:?}"
: "${CAGE_BUNDLE_ROOT:?}"
: "${CAGE_RUNTIME_ROOT:?}"
: "${CAGE_STATE_ROOT:?}"

[[ "${RUN_ID}" == NO_NPC_* ]] || { echo "invalid no-NPC run id" >&2; exit 2; }
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd -P)"
CAGE_PYTHON="${CAGE_RUNTIME_ROOT}/envs/cage-ad-py310/bin/python"
RUN_STATE="${REPAIR_STATE_ROOT}/runs/${RUN_ID}"
RUN_DATA="${REPAIR_DATA_ROOT}/${RUN_ID}"
LOG_ROOT="${RUN_DATA}/logs"
TRACE="${RUN_DATA}/trace.jsonl"
SUMMARY="${RUN_DATA}/runtime_summary.json"
RESULT="${RUN_STATE}/result.json"
EMPTY_STATS="${RUN_DATA}/empty_road_stats.json"
INTERPOSER_STATS="${RUN_DATA}/private/interposer_stats.json"
INTERPOSER_CAPTURE="${RUN_DATA}/private/interposer_capture.json"
INTERPOSER_CONFIG="${RUN_DATA}/private/interposer.json"
BRIDGE_CONTROL_TELEMETRY="${RUN_DATA}/bridge_control_telemetry.jsonl"
APOLLO_CONF_ROOT="${RUN_DATA}/apollo_conf"
LAUNCH=""
APOLLO_EXTRA="${CAGE_RUNTIME_ROOT}/bridge/python:${CAGE_RUNTIME_ROOT}/bridge/apollo-carla:${REPO_ROOT}/src"
EMPTY_PID=""
INTERPOSER_PID=""
STACK_PID=""
POWER_STARTED_NS=""
RUNTIME_EXIT=1

[[ ! -e "${RESULT}" ]] || { echo "execution smoke already finished" >&2; exit 2; }
install -d -m 0700 "${RUN_STATE}" "${RUN_DATA}" "${LOG_ROOT}"
"${CAGE_PYTHON}" "${REPO_ROOT}/scripts/d0/repair/prepare_execution_smoke.py" --repo-root "${REPO_ROOT}" --run-id "${RUN_ID}" --run-state "${RUN_STATE}" --run-data "${RUN_DATA}" >"${LOG_ROOT}/prepare.log"
CONTROL_RENDER_ARGS=()
if [[ -n "${CAGE_APOLLO_CALIBRATION_OVERRIDE:-}" ]]; then
  CONTROL_RENDER_ARGS=(
    --control-flag-file
    "${APOLLO_CONF_ROOT}/modules/control/control_component/conf/control.conf"
  )
fi
LAUNCH="$(${CAGE_PYTHON} "${REPO_ROOT}/scripts/d0/render_apollo_runtime.py" --repo-root "${REPO_ROOT}" --state-root "${CAGE_STATE_ROOT}" "${CONTROL_RENDER_ARGS[@]}")"

stop_group() {
  local pid="$1"
  [[ -n "${pid}" ]] || return 0
  if kill -0 "${pid}" 2>/dev/null; then
    kill -INT -- "-${pid}" 2>/dev/null || kill -INT "${pid}" 2>/dev/null || true
    for _ in $(seq 1 20); do
      kill -0 "${pid}" 2>/dev/null || return 0
      sleep 1
    done
    kill -TERM -- "-${pid}" 2>/dev/null || kill -TERM "${pid}" 2>/dev/null || true
  fi
}

cleanup() {
  # shellcheck disable=SC2016 # expansion belongs to the activated child shell
  APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" bash -c 'export APOLLO_CONF_PATH="$1:$APOLLO_CONF_PATH"; shift; exec "$@"' bash "${APOLLO_CONF_ROOT}" cyber_launch stop "${LAUNCH}" >>"${LOG_ROOT}/stack.log" 2>&1 || true
  stop_group "${STACK_PID}"
  stop_group "${INTERPOSER_PID}"
  stop_group "${EMPTY_PID}"
  "${CAGE_BUNDLE_ROOT}/scripts/manage_carla_bridge.sh" stop >>"${LOG_ROOT}/cleanup.log" 2>&1 || true
  "${CAGE_BUNDLE_ROOT}/scripts/manage_carla_server.sh" stop >>"${LOG_ROOT}/cleanup.log" 2>&1 || true
}

on_exit() {
  local code=$?
  trap - EXIT INT TERM
  cleanup
  exit "${code}"
}
trap on_exit EXIT INT TERM

"${CAGE_BUNDLE_ROOT}/scripts/manage_a1_apollo_stack.sh" stop >>"${LOG_ROOT}/preclean.log" 2>&1 || true
"${CAGE_BUNDLE_ROOT}/scripts/manage_carla_bridge.sh" stop >>"${LOG_ROOT}/preclean.log" 2>&1 || true
"${CAGE_BUNDLE_ROOT}/scripts/manage_carla_server.sh" stop >>"${LOG_ROOT}/preclean.log" 2>&1 || true

POWER_STARTED_NS="$(date +%s%N)"
"${CAGE_BUNDLE_ROOT}/scripts/manage_carla_server.sh" start >>"${LOG_ROOT}/carla.log" 2>&1
APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" python3 "${REPO_ROOT}/scripts/d0/wait_for_carla.py" --timeout 90 >>"${LOG_ROOT}/carla.log" 2>&1
APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" python3 "${REPO_ROOT}/scripts/d0/repair/load_carla_world_once.py" >>"${LOG_ROOT}/carla.log" 2>&1
CARLA_BRIDGE_CONTROL_TOPIC=/apollo/control_guarded \
  CAGE_BRIDGE_CONTROL_TELEMETRY="${BRIDGE_CONTROL_TELEMETRY}" \
  "${CAGE_BUNDLE_ROOT}/scripts/manage_carla_bridge.sh" start >>"${LOG_ROOT}/bridge.log" 2>&1

setsid env APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" python3 -m cage_ad.adapters.apollo_d0.empty_road_runtime --run-id "${RUN_ID}" --stats "${EMPTY_STATS}" >"${LOG_ROOT}/empty_road.log" 2>&1 </dev/null &
EMPTY_PID=$!
sleep 2
kill -0 "${EMPTY_PID}"

setsid env APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" python3 -m cage_ad.adapters.apollo_d0.interposer_runtime --private-config "${INTERPOSER_CONFIG}" --capture "${INTERPOSER_CAPTURE}" --private-stats "${INTERPOSER_STATS}" --repo-root "${REPO_ROOT}" >"${LOG_ROOT}/interposer.log" 2>&1 </dev/null &
INTERPOSER_PID=$!
sleep 2
kill -0 "${INTERPOSER_PID}"

# shellcheck disable=SC2016 # expansion belongs to the activated child shell
setsid env APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" bash -c 'export APOLLO_CONF_PATH="$1:$APOLLO_CONF_PATH"; shift; exec "$@"' bash "${APOLLO_CONF_ROOT}" cyber_launch start "${LAUNCH}" >"${LOG_ROOT}/stack.log" 2>&1 </dev/null &
STACK_PID=$!
sleep 12
kill -0 "${STACK_PID}"

set +e
env APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" python3 -m cage_ad.adapters.apollo_d0.execution_smoke_runtime --run-id "${RUN_ID}" --duration-s 20 --trace "${TRACE}" --summary "${SUMMARY}" >"${LOG_ROOT}/runtime.log" 2>&1
RUNTIME_EXIT=$?
set -e

cleanup
ended_ns="$(date +%s%N)"
powered="$(${CAGE_PYTHON} -c 'import sys; print((int(sys.argv[2])-int(sys.argv[1]))/1e9)' "${POWER_STARTED_NS}" "${ended_ns}")"
set +e
"${CAGE_PYTHON}" "${REPO_ROOT}/scripts/d0/repair/evaluate_execution_smoke.py" --run-id "${RUN_ID}" --runtime-summary "${SUMMARY}" --stack-log "${LOG_ROOT}/stack.log" --empty-road-stats "${EMPTY_STATS}" --interposer-stats "${INTERPOSER_STATS}" --runtime-exit "${RUNTIME_EXIT}" --powered-on-seconds "${powered}" --source-commit "$(git -C "${REPO_ROOT}" rev-parse HEAD)" --output "${RESULT}"
EVAL_EXIT=$?
set -e
trap - EXIT INT TERM
exit "${EVAL_EXIT}"
