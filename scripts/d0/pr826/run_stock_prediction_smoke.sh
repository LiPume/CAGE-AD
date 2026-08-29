#!/usr/bin/env bash
set -euo pipefail

RUN_DIR="${1:?usage: $0 RUN_DIR}"
BUNDLE_ROOT="${CAGE_BUNDLE_ROOT:-/root/autodl_apollo10_g0_bundle}"
REPO_ROOT="${BUNDLE_ROOT}/project/CAGE-AD"
LAUNCH="modules/prediction/launch/prediction.launch"
STACK_PID=""

[[ "${RUN_DIR}" == "${BUNDLE_ROOT}/runtime/runs/"* ]] || {
  echo "run directory is not under canonical runtime/runs" >&2
  exit 2
}
install -d "${RUN_DIR}"

cleanup() {
  trap - EXIT INT TERM
  timeout 8 "${BUNDLE_ROOT}/scripts/apollo_host_exec.sh" cyber_launch stop "${LAUNCH}" \
    >>"${RUN_DIR}/stack.log" 2>&1 || true
  if [[ -n "${STACK_PID}" ]] && kill -0 "${STACK_PID}" 2>/dev/null; then
    kill -INT -- "-${STACK_PID}" 2>/dev/null || kill -INT "${STACK_PID}" 2>/dev/null || true
    for _ in $(seq 1 10); do
      kill -0 "${STACK_PID}" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "${STACK_PID}" 2>/dev/null; then
      kill -KILL -- "-${STACK_PID}" 2>/dev/null || kill -KILL "${STACK_PID}" 2>/dev/null || true
    fi
    wait "${STACK_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

timeout 5 "${BUNDLE_ROOT}/scripts/apollo_host_exec.sh" cyber_launch stop "${LAUNCH}" \
  >"${RUN_DIR}/preclean.log" 2>&1 || true
setsid "${BUNDLE_ROOT}/scripts/apollo_host_exec.sh" cyber_launch start "${LAUNCH}" \
  >"${RUN_DIR}/stack.log" 2>&1 </dev/null &
STACK_PID=$!
# Stock Prediction loads several Torch evaluators before it creates its readers/writer.
# Cold host-mode startup has measured above 17 seconds on this machine.
sleep 35
kill -0 "${STACK_PID}"

APOLLO_EXTRA_PYTHONPATH="${REPO_ROOT}/src" \
  "${BUNDLE_ROOT}/scripts/apollo_host_exec.sh" python3 \
  "${REPO_ROOT}/scripts/d0/pr826/prediction_smoke_runtime.py" \
  --output "${RUN_DIR}/summary.json" --duration 8 --rate-hz 20 \
  --stack-log "${RUN_DIR}/stack.log" \
  >"${RUN_DIR}/runtime.log" 2>&1

cleanup
trap - EXIT INT TERM
