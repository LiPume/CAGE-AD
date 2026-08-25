#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${1:?usage: $0 RUN_ID HINT_STATE_ROOT RAW_ROOT LOG_ROOT}"
HINT_STATE_ROOT="${2:?}"
RAW_ROOT="${3:?}"
HINT_LOG_ROOT="${4:?}"
: "${CAGE_BUNDLE_ROOT:?}"
: "${CAGE_RUNTIME_ROOT:?}"
: "${CAGE_STATE_ROOT:?}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd -P)"
CAGE_PYTHON="${CAGE_RUNTIME_ROOT}/envs/cage-ad-py310/bin/python"
RUN_STATE="${HINT_STATE_ROOT}/runs/${RUN_ID}"
PLANNED="${RUN_STATE}/planned.json"
FINISHED="${RUN_STATE}/finished.json"
RUN_RAW="${RAW_ROOT}/${RUN_ID}"
PRIVATE_ROOT="${RUN_RAW}/private"
CAPTURE_ROOT="${RUN_RAW}/capture"
LOG_ROOT="${HINT_LOG_ROOT}/${RUN_ID}"
TRACE="${CAPTURE_ROOT}/trace.jsonl"
SUMMARY="${CAPTURE_ROOT}/summary.json"
BRIDGE_CONTROL_TELEMETRY="${CAPTURE_ROOT}/bridge_control_telemetry.jsonl"
APOLLO_CONF_ROOT="${RUN_RAW}/apollo_conf"
SCENARIO_PID=""
INTERPOSER_PID=""
STACK_PID=""
POWER_STARTED_NS=""
RUNTIME_EXIT=1

[[ -s "${PLANNED}" ]] || { echo "missing planned.json" >&2; exit 2; }
[[ ! -e "${FINISHED}" ]] || { echo "run already finished" >&2; exit 2; }
[[ "${RAW_ROOT}" == "${CAGE_RUNTIME_ROOT}/raw/"* ]] || { echo "raw root is not canonical" >&2; exit 2; }
install -d -m 0700 "${CAPTURE_ROOT}" "${LOG_ROOT}"

APOLLO_EXTRA="${CAGE_RUNTIME_ROOT}/bridge/python:${CAGE_RUNTIME_ROOT}/bridge/apollo-carla:${REPO_ROOT}/src"
CONTROL_RENDER_ARGS=()
if [[ -s "${APOLLO_CONF_ROOT}/modules/control/control_component/conf/control.conf" ]]; then
  CONTROL_RENDER_ARGS=(--control-flag-file "${APOLLO_CONF_ROOT}/modules/control/control_component/conf/control.conf")
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
  APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" \
    bash -c 'export APOLLO_CONF_PATH="$1:$APOLLO_CONF_PATH"; shift; exec "$@"' \
    bash "${APOLLO_CONF_ROOT}" cyber_launch stop "${LAUNCH}" >>"${LOG_ROOT}/stack.log" 2>&1 || true
  stop_group "${STACK_PID}"
  stop_group "${INTERPOSER_PID}"
  stop_group "${SCENARIO_PID}"
  "${CAGE_BUNDLE_ROOT}/scripts/manage_carla_bridge.sh" stop >>"${LOG_ROOT}/cleanup.log" 2>&1 || true
  "${CAGE_BUNDLE_ROOT}/scripts/manage_carla_server.sh" stop >>"${LOG_ROOT}/cleanup.log" 2>&1 || true
}

finish_if_needed() {
  local code="$1"
  if [[ -n "${POWER_STARTED_NS}" && ! -e "${FINISHED}" ]]; then
    local ended_ns powered
    ended_ns="$(date +%s%N)"
    powered="$(${CAGE_PYTHON} -c 'import sys; print((int(sys.argv[2])-int(sys.argv[1]))/1e9)' "${POWER_STARTED_NS}" "${ended_ns}")"
    "${CAGE_PYTHON}" "${REPO_ROOT}/scripts/d0/hint_gold/finish_candidate_run.py" \
      --planned "${PLANNED}" --trace "${TRACE}" --summary "${SUMMARY}" --finished "${FINISHED}" \
      --powered-on-seconds "${powered}" --runtime-exit "${code}" >>"${LOG_ROOT}/finish.log" 2>&1 || true
  fi
}

on_exit() {
  local code=$?
  trap - EXIT INT TERM
  cleanup
  finish_if_needed "${RUNTIME_EXIT}"
  exit "${code}"
}
trap on_exit EXIT INT TERM

"${CAGE_BUNDLE_ROOT}/scripts/manage_a1_apollo_stack.sh" stop >>"${LOG_ROOT}/preclean.log" 2>&1 || true
"${CAGE_BUNDLE_ROOT}/scripts/manage_carla_bridge.sh" stop >>"${LOG_ROOT}/preclean.log" 2>&1 || true
"${CAGE_BUNDLE_ROOT}/scripts/manage_carla_server.sh" stop >>"${LOG_ROOT}/preclean.log" 2>&1 || true

POWER_STARTED_NS="$(date +%s%N)"
"${CAGE_BUNDLE_ROOT}/scripts/manage_carla_server.sh" start >>"${LOG_ROOT}/carla.log" 2>&1
APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" \
  python3 "${REPO_ROOT}/scripts/d0/wait_for_carla.py" --timeout 90 >>"${LOG_ROOT}/carla.log" 2>&1
APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" \
  python3 "${REPO_ROOT}/scripts/d0/repair/load_carla_world_once.py" >>"${LOG_ROOT}/carla.log" 2>&1
CARLA_BRIDGE_CONTROL_TOPIC=/apollo/control_guarded \
  CAGE_BRIDGE_CONTROL_TELEMETRY="${BRIDGE_CONTROL_TELEMETRY}" \
  "${CAGE_BUNDLE_ROOT}/scripts/manage_carla_bridge.sh" start >>"${LOG_ROOT}/bridge.log" 2>&1

setsid env PYTHONHASHSEED=1101 APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" \
  "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" python3 \
  -m cage_ad.adapters.apollo_d0.scenario_runtime \
  --private-scenario-config "${PRIVATE_ROOT}/scenario.json" \
  --private-stats "${PRIVATE_ROOT}/scenario_stats.json" --repo-root "${REPO_ROOT}" \
  >"${LOG_ROOT}/scenario.log" 2>&1 </dev/null &
SCENARIO_PID=$!

setsid env APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" \
  "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" python3 \
  -m cage_ad.adapters.apollo_d0.interposer_runtime \
  --private-config "${PRIVATE_ROOT}/interposer.json" \
  --capture "${PRIVATE_ROOT}/semantic_evidence.json" \
  --private-stats "${PRIVATE_ROOT}/interposer_stats.json" --repo-root "${REPO_ROOT}" \
  >"${LOG_ROOT}/interposer.log" 2>&1 </dev/null &
INTERPOSER_PID=$!
sleep 2
kill -0 "${SCENARIO_PID}"
kill -0 "${INTERPOSER_PID}"

setsid env APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" \
  "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" \
  bash -c 'export APOLLO_CONF_PATH="$1:$APOLLO_CONF_PATH"; shift; exec "$@"' \
  bash "${APOLLO_CONF_ROOT}" cyber_launch start "${LAUNCH}" \
  >"${LOG_ROOT}/stack.log" 2>&1 </dev/null &
STACK_PID=$!
sleep 12
kill -0 "${STACK_PID}"

set +e
env APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" \
  python3 -m cage_ad.adapters.apollo_d0.ttc_diagnostic_runtime \
  --config "${PRIVATE_ROOT}/capture.json" --trace "${TRACE}" --summary "${SUMMARY}" \
  --repo-root "${REPO_ROOT}" >"${LOG_ROOT}/capture.log" 2>&1
RUNTIME_EXIT=$?
set -e

cleanup
ended_ns="$(date +%s%N)"
powered="$(${CAGE_PYTHON} -c 'import sys; print((int(sys.argv[2])-int(sys.argv[1]))/1e9)' "${POWER_STARTED_NS}" "${ended_ns}")"
"${CAGE_PYTHON}" "${REPO_ROOT}/scripts/d0/hint_gold/finish_candidate_run.py" \
  --planned "${PLANNED}" --trace "${TRACE}" --summary "${SUMMARY}" --finished "${FINISHED}" \
  --powered-on-seconds "${powered}" --runtime-exit "${RUNTIME_EXIT}"
trap - EXIT INT TERM
exit "${RUNTIME_EXIT}"
