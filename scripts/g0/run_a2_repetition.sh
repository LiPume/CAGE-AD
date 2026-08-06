#!/usr/bin/env bash
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
RUN_INDEX="${1:?usage: $0 RUN_INDEX}"
if [[ ! "${RUN_INDEX}" =~ ^[1-9][0-9]*$ ]]; then
  echo "RUN_INDEX must be a positive integer" >&2
  exit 2
fi
RUN_ROOT="${BUNDLE_ROOT}/runtime/runs/a2/${RUN_INDEX}"
VISIBLE_DIR="${RUN_ROOT}/visible"
PRIVATE_DIR="${BUNDLE_ROOT}/runtime_state/evidence/a2/private/${RUN_INDEX}"
PUBLIC_DIR="${BUNDLE_ROOT}/runtime_state/evidence/a2"
RESULT="${PUBLIC_DIR}/run_${RUN_INDEX}.json"
ISOLATION="${PUBLIC_DIR}/isolation_${RUN_INDEX}.json"
MANIFEST="${PUBLIC_DIR}/manifest_${RUN_INDEX}.json"
INTERPOSER_PID=""

cleanup() {
  trap - EXIT INT TERM
  "${BUNDLE_ROOT}/scripts/manage_a1_apollo_stack.sh" stop || true
  if [[ -n "${INTERPOSER_PID}" ]] && kill -0 "${INTERPOSER_PID}" 2>/dev/null; then
    kill -INT -- "-${INTERPOSER_PID}" 2>/dev/null || kill -INT "${INTERPOSER_PID}" 2>/dev/null || true
    for _ in $(seq 1 20); do
      kill -0 "${INTERPOSER_PID}" 2>/dev/null || break
      sleep 1
    done
  fi
  "${BUNDLE_ROOT}/scripts/manage_carla_bridge.sh" stop || true
}
trap cleanup EXIT INT TERM

install -d "${PUBLIC_DIR}"
"${BUNDLE_ROOT}/scripts/manage_a1_apollo_stack.sh" stop
"${BUNDLE_ROOT}/scripts/manage_carla_bridge.sh" stop
"${BUNDLE_ROOT}/scripts/manage_carla_server.sh" status
"${BUNDLE_ROOT}/runtime/envs/guardian-py310/bin/python" \
  "${BUNDLE_ROOT}/scripts/a2_prepare_run.py" \
  --run-index "${RUN_INDEX}" --run-root "${RUN_ROOT}" --private-root "${PRIVATE_DIR}"

CARLA_BRIDGE_CONTROL_TOPIC=/apollo/control_guarded \
  "${BUNDLE_ROOT}/scripts/manage_carla_bridge.sh" start
sleep 5
setsid "${BUNDLE_ROOT}/scripts/apollo_bridge_exec.sh" python3 \
  "${BUNDLE_ROOT}/scripts/a2_control_interposer.py" \
  --private-config "${PRIVATE_DIR}/injector_config.json" \
  --private-stats "${PRIVATE_DIR}/injector_stats.json" \
  >"${PRIVATE_DIR}/interposer.log" 2>&1 </dev/null &
INTERPOSER_PID=$!
sleep 2
kill -0 "${INTERPOSER_PID}"
"${BUNDLE_ROOT}/runtime/envs/guardian-py310/bin/python" \
  "${BUNDLE_ROOT}/scripts/a2_oracle_isolation_check.py" \
  --private-config "${PRIVATE_DIR}/injector_config.json" \
  --oracle "${PRIVATE_DIR}/oracle.json" \
  --injector-pid "${INTERPOSER_PID}" --output "${ISOLATION}"

"${BUNDLE_ROOT}/scripts/manage_a1_apollo_stack.sh" start
sleep 15
"${BUNDLE_ROOT}/scripts/apollo_bridge_exec.sh" python3 \
  "${BUNDLE_ROOT}/scripts/a2_closed_loop_run.py" \
  --run-id "${RUN_INDEX}" --visible-dir "${VISIBLE_DIR}" --result "${RESULT}" \
  --diagnosis-python "${BUNDLE_ROOT}/runtime/envs/guardian-py310/bin/python" \
  --diagnosis-script "${BUNDLE_ROOT}/scripts/a2_l1_diagnose.py"

"${BUNDLE_ROOT}/scripts/manage_a1_apollo_stack.sh" stop
kill -INT -- "-${INTERPOSER_PID}" 2>/dev/null || kill -INT "${INTERPOSER_PID}" 2>/dev/null || true
for _ in $(seq 1 20); do
  kill -0 "${INTERPOSER_PID}" 2>/dev/null || break
  sleep 1
done
if kill -0 "${INTERPOSER_PID}" 2>/dev/null; then
  echo "A2 interposer failed to stop cleanly" >&2
  exit 1
fi
INTERPOSER_PID=""
"${BUNDLE_ROOT}/scripts/manage_carla_bridge.sh" stop

"${BUNDLE_ROOT}/runtime/envs/guardian-py310/bin/python" \
  "${BUNDLE_ROOT}/scripts/a2_evaluate_run.py" \
  --result "${RESULT}" --oracle "${PRIVATE_DIR}/oracle.json" \
  --isolation "${ISOLATION}" --injector-stats "${PRIVATE_DIR}/injector_stats.json" \
  --versions "${BUNDLE_ROOT}/runtime_state/versions.lock.yaml" --output "${MANIFEST}"
