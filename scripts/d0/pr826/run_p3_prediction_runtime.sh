#!/usr/bin/env bash
set -euo pipefail

MODE="${1:?usage: $0 MODE RUN_DIR}"
RUN_DIR="${2:?usage: $0 MODE RUN_DIR}"
BUNDLE_ROOT="${CAGE_BUNDLE_ROOT:-/root/autodl_apollo10_g0_bundle}"
REPO_ROOT="${BUNDLE_ROOT}/project/CAGE-AD"
BUILD_DIR="${BUNDLE_ROOT}/runtime/apollo/p3_semantic_port/workspace_candidate_01/bazel-bin/external/apollo_src/modules/prediction"
STOCK_LAUNCH="modules/prediction/launch/prediction.launch"
LAUNCH="${STOCK_LAUNCH}"
CUSTOM_LIBRARY_DIR=""
STACK_PID=""

case "${MODE}" in
  stock|inactive-port|active-port) ;;
  *) echo "invalid mode: ${MODE}" >&2; exit 64 ;;
esac
[[ "${RUN_DIR}" == "${BUNDLE_ROOT}/runtime/runs/"* ]] || {
  echo "run directory is not under canonical runtime/runs" >&2
  exit 2
}
install -d -m 700 "${RUN_DIR}"

apollo_exec() {
  if [[ -n "${CUSTOM_LIBRARY_DIR}" ]]; then
    "${BUNDLE_ROOT}/scripts/apollo_host_exec.sh" bash -c \
      'export LD_LIBRARY_PATH="$1:${LD_LIBRARY_PATH:-}"; shift; exec "$@"' \
      _ "${CUSTOM_LIBRARY_DIR}" "$@"
  else
    "${BUNDLE_ROOT}/scripts/apollo_host_exec.sh" "$@"
  fi
}

if [[ "${MODE}" != stock ]]; then
  CUSTOM_LIBRARY_DIR="${BUILD_DIR}"
  COMPONENT="${BUILD_DIR}/libprediction_component.so"
  PREP_ARGS=(
    --output-dir "${RUN_DIR}/q1"
    --component "${COMPONENT}"
    --library-dir "${CUSTOM_LIBRARY_DIR}"
    --trace-active
  )
  if [[ "${MODE}" == active-port ]]; then
    PREP_ARGS+=(--domain-active)
  fi
  python3 "${REPO_ROOT}/scripts/d0/pr826/prepare_p3_prediction_launch.py" "${PREP_ARGS[@]}" \
    >"${RUN_DIR}/prepare.log"
  LAUNCH="${RUN_DIR}/q1/q1.launch"
fi

cleanup() {
  trap - EXIT INT TERM
  apollo_exec timeout 8 cyber_launch stop "${LAUNCH}" \
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

apollo_exec timeout 8 cyber_launch stop "${LAUNCH}" \
  >"${RUN_DIR}/preclean.log" 2>&1 || true
setsid bash -c 'exec "$@"' _ "${BUNDLE_ROOT}/scripts/apollo_host_exec.sh" bash -c \
  'if [[ -n "$1" ]]; then export LD_LIBRARY_PATH="$1:${LD_LIBRARY_PATH:-}"; fi; shift; exec "$@"' \
  _ "${CUSTOM_LIBRARY_DIR}" cyber_launch start "${LAUNCH}" \
  >"${RUN_DIR}/stack.log" 2>&1 </dev/null &
STACK_PID=$!
sleep 35
kill -0 "${STACK_PID}"

APOLLO_EXTRA_PYTHONPATH="${REPO_ROOT}/src" \
  "${BUNDLE_ROOT}/scripts/apollo_host_exec.sh" python3 \
  "${REPO_ROOT}/scripts/d0/pr826/prediction_smoke_runtime.py" \
  --output "${RUN_DIR}/summary.json" --duration 8 --rate-hz 20 \
  --message-count 160 --semantic-capture "${RUN_DIR}/semantic_capture.json" \
  --stack-log "${RUN_DIR}/stack.log" \
  >"${RUN_DIR}/runtime.log" 2>&1

cleanup
trap - EXIT INT TERM
