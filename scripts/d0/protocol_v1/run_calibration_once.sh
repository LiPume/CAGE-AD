#!/usr/bin/env bash
set -euo pipefail

ATTEMPT_ID="${1:?usage: $0 ATTEMPT_ID PRIVATE_ROOT VISIBLE_ROOT LOG_ROOT}"
PRIVATE_ROOT="${2:?}"
VISIBLE_ROOT="${3:?}"
LOG_ROOT="${4:?}"
: "${CAGE_BUNDLE_ROOT:?}"
: "${CAGE_RUNTIME_ROOT:?}"
: "${CAGE_STATE_ROOT:?}"
: "${CAGE_DATA_ROOT:?}"
: "${CAGE_PRIVATE_ORACLE_ROOT:?}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd -P)"
CAGE_PYTHON="${CAGE_RUNTIME_ROOT}/envs/cage-ad-py310/bin/python"
RESULT="${PRIVATE_ROOT}/run_metrics.json"
RESOURCE="${PRIVATE_ROOT}/resource_usage.json"
FAILURE="${PRIVATE_ROOT}/runtime_failure.json"
PID_REGISTRY="${PRIVATE_ROOT}/required_pids.json"
SCENARIO_PID=""
INTERPOSER_PID=""
STACK_PID=""
POWER_STARTED_NS=""
RUN_EXIT=0

install -d -m 0700 "${PRIVATE_ROOT}"
install -d -m 0750 "${VISIBLE_ROOT}" "${LOG_ROOT}"

if [[ -s "${PRIVATE_ROOT}/attempt_result.json" ]]; then
  echo "protocol_v1_attempt=SKIP_COMPLETED attempt_id=${ATTEMPT_ID}"
  exit 0
fi
if [[ -s "${RESULT}" && -s "${RESOURCE}" ]]; then
  "${CAGE_PYTHON}" "${REPO_ROOT}/scripts/d0/protocol_v1/complete_attempt.py" \
    --repo-root "${REPO_ROOT}" --state-root "${CAGE_STATE_ROOT}" \
    --data-root "${CAGE_DATA_ROOT}" --private-oracle-root "${CAGE_PRIVATE_ORACLE_ROOT}" \
    --attempt-id "${ATTEMPT_ID}"
  echo "protocol_v1_attempt=SKIP_SIDE_EFFECT_COMPLETE_LEDGER attempt_id=${ATTEMPT_ID}"
  exit 0
fi

SEED="$(${CAGE_PYTHON} -c 'import json,sys; print(json.load(open(sys.argv[1]))["seed"])' "${PRIVATE_ROOT}/scenario.json")"
LAUNCH="$(${CAGE_PYTHON} "${REPO_ROOT}/scripts/d0/render_apollo_runtime.py" \
  --repo-root "${REPO_ROOT}" --state-root "${CAGE_STATE_ROOT}")"
APOLLO_EXTRA="${CAGE_RUNTIME_ROOT}/bridge/python:${CAGE_RUNTIME_ROOT}/bridge/apollo-carla:${REPO_ROOT}/src"

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

stop_protocol_runtime() {
  local pattern pid
  for pattern in \
    'cage_ad.adapters.apollo_d0.scenario_runtime' \
    'cage_ad.adapters.apollo_d0.interposer_runtime'; do
    while read -r pid; do
      if [[ -n "${pid}" ]]; then
        kill -INT "${pid}" 2>/dev/null || true
      fi
    done < <(pgrep -f "${pattern}" || true)
  done
}

cleanup() {
  APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" \
    "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" cyber_launch stop "${LAUNCH}" \
    >>"${LOG_ROOT}/stack.log" 2>&1 || true
  stop_group "${STACK_PID}"
  stop_group "${INTERPOSER_PID}"
  stop_group "${SCENARIO_PID}"
  stop_protocol_runtime
  "${CAGE_BUNDLE_ROOT}/scripts/manage_carla_bridge.sh" stop >>"${LOG_ROOT}/cleanup.log" 2>&1 || true
  "${CAGE_BUNDLE_ROOT}/scripts/manage_carla_server.sh" stop >>"${LOG_ROOT}/cleanup.log" 2>&1 || true
}

record_resources() {
  local ended_ns powered_seconds
  ended_ns="$(date +%s%N)"
  powered_seconds="$(${CAGE_PYTHON} -c 'import sys; print((int(sys.argv[2])-int(sys.argv[1]))/1e9)' "${POWER_STARTED_NS}" "${ended_ns}")"
  "${CAGE_PYTHON}" -c \
    'import json,os,sys; p=sys.argv[1]; t=p+".tmp."+str(os.getpid()); open(t,"w").write(json.dumps({"wall_seconds":float(sys.argv[2]),"powered_on_seconds":float(sys.argv[2])},sort_keys=True)+"\n"); os.chmod(t,0o600); os.replace(t,p)' \
    "${RESOURCE}" "${powered_seconds}"
}

on_exit() {
  local exit_code=$?
  trap - EXIT INT TERM
  cleanup
  if [[ -n "${POWER_STARTED_NS}" ]]; then
    record_resources
  fi
  if [[ ${exit_code} -ne 0 && ! -s "${FAILURE}" ]]; then
    "${CAGE_PYTHON}" -c \
      'import json,os,sys; p=sys.argv[1]; t=p+".tmp."+str(os.getpid()); open(t,"w").write(json.dumps({"exit_code":int(sys.argv[2]),"reason":"runtime_command_failed"},sort_keys=True)+"\n"); os.chmod(t,0o600); os.replace(t,p)' \
      "${FAILURE}" "${exit_code}"
  fi
  if [[ ${exit_code} -ne 0 && -s "${RESOURCE}" ]]; then
    "${CAGE_PYTHON}" "${REPO_ROOT}/scripts/d0/protocol_v1/complete_attempt.py" \
      --repo-root "${REPO_ROOT}" --state-root "${CAGE_STATE_ROOT}" \
      --data-root "${CAGE_DATA_ROOT}" --private-oracle-root "${CAGE_PRIVATE_ORACLE_ROOT}" \
      --attempt-id "${ATTEMPT_ID}" >>"${LOG_ROOT}/completion.log" 2>&1 || true
  fi
}
trap on_exit EXIT INT TERM

"${CAGE_BUNDLE_ROOT}/scripts/manage_a1_apollo_stack.sh" stop >>"${LOG_ROOT}/preclean.log" 2>&1 || true
"${CAGE_BUNDLE_ROOT}/scripts/manage_carla_bridge.sh" stop >>"${LOG_ROOT}/preclean.log" 2>&1 || true
stop_protocol_runtime
"${CAGE_BUNDLE_ROOT}/scripts/manage_carla_server.sh" stop >>"${LOG_ROOT}/preclean.log" 2>&1 || true

POWER_STARTED_NS="$(date +%s%N)"
"${CAGE_BUNDLE_ROOT}/scripts/manage_carla_server.sh" start >>"${LOG_ROOT}/carla.log" 2>&1
APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" \
  "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" python3 \
  "${REPO_ROOT}/scripts/d0/wait_for_carla.py" --timeout 90 >>"${LOG_ROOT}/carla.log" 2>&1
CARLA_BRIDGE_CONTROL_TOPIC=/apollo/control_guarded \
  "${CAGE_BUNDLE_ROOT}/scripts/manage_carla_bridge.sh" start >>"${LOG_ROOT}/bridge.log" 2>&1

setsid env PYTHONHASHSEED="${SEED}" APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" \
  "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" python3 -m \
  cage_ad.adapters.apollo_d0.scenario_runtime \
  --private-scenario-config "${PRIVATE_ROOT}/scenario.json" \
  --private-stats "${PRIVATE_ROOT}/scenario_stats.json" \
  --repo-root "${REPO_ROOT}" >"${LOG_ROOT}/scenario.log" 2>&1 </dev/null &
SCENARIO_PID=$!

setsid env APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" \
  "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" python3 -m \
  cage_ad.adapters.apollo_d0.interposer_runtime \
  --private-config "${PRIVATE_ROOT}/interposer.json" \
  --capture "${VISIBLE_ROOT}/semantic_evidence.json" \
  --private-stats "${PRIVATE_ROOT}/interposer_stats.json" \
  --repo-root "${REPO_ROOT}" >"${LOG_ROOT}/interposer.log" 2>&1 </dev/null &
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

"${CAGE_PYTHON}" "${REPO_ROOT}/scripts/d0/protocol_v1/capture_runtime_pids.py" \
  --stack-log "${LOG_ROOT}/stack.log" \
  --bridge-pid-file "${CAGE_RUNTIME_ROOT}/runs/carla_bridge/bridge.pid" \
  --scenario-pid "${SCENARIO_PID}" --interposer-pid "${INTERPOSER_PID}" \
  --output "${PID_REGISTRY}"

set +e
env APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" \
  "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" python3 -m \
  cage_ad.adapters.apollo_d0.run_runtime \
  --opaque-run-id "${ATTEMPT_ID}" \
  --private-run-config "${PRIVATE_ROOT}/run.json" \
  --private-output "${RESULT}" \
  --required-pids-json "${PID_REGISTRY}" \
  --repo-root "${REPO_ROOT}" >"${LOG_ROOT}/runner.log" 2>&1
RUN_EXIT=$?
set -e

cleanup
record_resources
trap - EXIT INT TERM
if [[ ${RUN_EXIT} -ne 0 && ! -s "${RESULT}" ]]; then
  "${CAGE_PYTHON}" -c \
    'import json,os,sys; p=sys.argv[1]; t=p+".tmp."+str(os.getpid()); open(t,"w").write(json.dumps({"exit_code":int(sys.argv[2]),"reason":"runner_failed_without_metrics"},sort_keys=True)+"\n"); os.chmod(t,0o600); os.replace(t,p)' \
    "${FAILURE}" "${RUN_EXIT}"
fi
"${CAGE_PYTHON}" "${REPO_ROOT}/scripts/d0/protocol_v1/complete_attempt.py" \
  --repo-root "${REPO_ROOT}" --state-root "${CAGE_STATE_ROOT}" \
  --data-root "${CAGE_DATA_ROOT}" --private-oracle-root "${CAGE_PRIVATE_ORACLE_ROOT}" \
  --attempt-id "${ATTEMPT_ID}"
echo "protocol_v1_attempt=FINISHED attempt_id=${ATTEMPT_ID} runner_exit=${RUN_EXIT}"
