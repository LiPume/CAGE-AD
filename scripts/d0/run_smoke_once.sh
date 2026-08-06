#!/usr/bin/env bash
set -euo pipefail

EPISODE_ID="${1:?usage: $0 EPISODE_ID RUN_ID}"
RUN_ID="${2:?usage: $0 EPISODE_ID RUN_ID}"
: "${CAGE_BUNDLE_ROOT:?}"
: "${CAGE_RUNTIME_ROOT:?}"
: "${CAGE_STATE_ROOT:?}"
: "${CAGE_DATA_ROOT:?}"
: "${CAGE_PRIVATE_ORACLE_ROOT:?}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
CAGE_PYTHON="${CAGE_RUNTIME_ROOT}/envs/cage-ad-py310/bin/python"
BATCH_ID="${CAGE_D0_BATCH_ID:-d0_a0}"
PRIVATE_RUN="${CAGE_PRIVATE_ORACLE_ROOT}/${BATCH_ID}/${RUN_ID}"
EPISODE_ROOT="${CAGE_DATA_ROOT}/${BATCH_ID}/${EPISODE_ID}"
RETAINED_ROOT="${EPISODE_ROOT}/retained"
LOG_ROOT="${CAGE_STATE_ROOT}/logs/${BATCH_ID}/${RUN_ID}"
RESULT="${PRIVATE_RUN}/run_metrics.json"
STATUS="${CAGE_STATE_ROOT}/runs/${BATCH_ID}/${RUN_ID}.status"

if [[ -s "${STATUS}" ]] && grep -qx 'status=PASS' "${STATUS}" && [[ -s "${RESULT}" ]]; then
  echo "smoke_run=SKIP_ALREADY_PASS run_id=${RUN_ID}"
  exit 0
fi
install -d -m 0750 "${RETAINED_ROOT}" "${LOG_ROOT}" "$(dirname "${STATUS}")"
install -d -m 0700 "${PRIVATE_RUN}"

LAUNCH="$(${CAGE_PYTHON} "${REPO_ROOT}/scripts/d0/render_apollo_runtime.py" \
  --repo-root "${REPO_ROOT}" --state-root "${CAGE_STATE_ROOT}")"
APOLLO_EXTRA="${CAGE_RUNTIME_ROOT}/bridge/python:${CAGE_RUNTIME_ROOT}/bridge/apollo-carla:${REPO_ROOT}/src"
SCENARIO_PID=""
INTERPOSER_PID=""
STACK_PID=""

write_status() {
  local value="$1"
  local temporary="${STATUS}.tmp.$$"
  printf 'status=%s\nrun_id=%s\nepisode_id=%s\n' "${value}" "${RUN_ID}" "${EPISODE_ID}" >"${temporary}"
  mv -f "${temporary}" "${STATUS}"
}

stop_group() {
  local pid="$1"
  [[ -n "${pid}" ]] || return 0
  if kill -0 "${pid}" 2>/dev/null; then
    kill -INT -- "-${pid}" 2>/dev/null || kill -INT "${pid}" 2>/dev/null || true
    for _ in $(seq 1 20); do
      kill -0 "${pid}" 2>/dev/null || break
      sleep 1
    done
  fi
}

stop_d0_runtime() {
  local pattern pid
  for pattern in \
    'python3 -m cage_ad.adapters.apollo_d0.scenario_runtime' \
    'python3 -m cage_ad.adapters.apollo_d0.interposer_runtime'; do
    while read -r pid; do
      [[ -n "${pid}" ]] || continue
      kill -INT "${pid}" 2>/dev/null || true
    done < <(pgrep -f "${pattern}" || true)
  done
  for _ in $(seq 1 30); do
    if ! pgrep -f 'python3 -m cage_ad.adapters.apollo_d0.(scenario_runtime|interposer_runtime)' \
      >/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "D0 runtime process required SIGKILL after graceful timeout" >&2
  for pattern in \
    'python3 -m cage_ad.adapters.apollo_d0.scenario_runtime' \
    'python3 -m cage_ad.adapters.apollo_d0.interposer_runtime'; do
    while read -r pid; do
      [[ -n "${pid}" ]] || continue
      kill -KILL "${pid}" 2>/dev/null || true
    done < <(pgrep -f "${pattern}" || true)
  done
  return 1
}

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" \
    "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" cyber_launch stop "${LAUNCH}" \
    >>"${LOG_ROOT}/stack.log" 2>&1 || true
  stop_group "${STACK_PID}"
  stop_group "${INTERPOSER_PID}"
  stop_group "${SCENARIO_PID}"
  stop_d0_runtime || true
  "${CAGE_BUNDLE_ROOT}/scripts/manage_carla_bridge.sh" stop || true
  if [[ ${exit_code} -ne 0 ]]; then
    write_status FAIL
  fi
}
trap cleanup EXIT INT TERM

write_status RUNNING
"${CAGE_BUNDLE_ROOT}/scripts/manage_a1_apollo_stack.sh" stop || true
"${CAGE_BUNDLE_ROOT}/scripts/manage_carla_bridge.sh" stop || true
stop_d0_runtime
if ! "${CAGE_BUNDLE_ROOT}/scripts/manage_carla_server.sh" status; then
  "${CAGE_BUNDLE_ROOT}/scripts/manage_carla_server.sh" start
fi
APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" \
  "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" python3 \
  "${REPO_ROOT}/scripts/d0/wait_for_carla.py" --timeout 90
CARLA_BRIDGE_CONTROL_TOPIC=/apollo/control_guarded \
  "${CAGE_BUNDLE_ROOT}/scripts/manage_carla_bridge.sh" start
sleep 3

setsid env APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" \
  "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" python3 -m \
  cage_ad.adapters.apollo_d0.scenario_runtime \
  --private-scenario-config "${PRIVATE_RUN}/scenario.json" \
  --private-stats "${PRIVATE_RUN}/scenario_stats.json" \
  >"${LOG_ROOT}/scenario.log" 2>&1 </dev/null &
SCENARIO_PID=$!

setsid env APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" \
  "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" python3 -m \
  cage_ad.adapters.apollo_d0.interposer_runtime \
  --private-config "${PRIVATE_RUN}/injector.json" \
  --capture "${RETAINED_ROOT}/${RUN_ID}.json" \
  --private-stats "${PRIVATE_RUN}/interposer_stats.json" \
  >"${LOG_ROOT}/interposer.log" 2>&1 </dev/null &
INTERPOSER_PID=$!
sleep 2
kill -0 "${SCENARIO_PID}"
kill -0 "${INTERPOSER_PID}"

setsid env APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" \
  "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" cyber_launch start "${LAUNCH}" \
  >"${LOG_ROOT}/stack.log" 2>&1 </dev/null &
STACK_PID=$!
sleep 12
kill -0 "${STACK_PID}"

env APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" \
  "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" python3 -m \
  cage_ad.adapters.apollo_d0.run_runtime \
  --run-id "${RUN_ID}" --duration "${CAGE_D0_RUN_DURATION:-32}" \
  --private-output "${RESULT}"

cleanup
trap - EXIT INT TERM
test -s "${RESULT}"
test -s "${RETAINED_ROOT}/${RUN_ID}.json"
write_status PASS
echo "smoke_run=PASS run_id=${RUN_ID}"
