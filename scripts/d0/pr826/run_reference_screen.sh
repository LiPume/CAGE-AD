#!/usr/bin/env bash
set -euo pipefail

RUN_DIR="${1:?usage: $0 RUN_DIR}"
BUNDLE_ROOT="${CAGE_BUNDLE_ROOT:-/root/autodl_apollo10_g0_bundle}"
REPO_ROOT="${BUNDLE_ROOT}/project/CAGE-AD"
MANIFEST="${RUN_DIR}/manifest.json"
MAP_NAME="$("${BUNDLE_ROOT}/runtime/envs/cage-ad-py310/bin/python" -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["candidate"]["map"])' \
  "${MANIFEST}")"
case "${MAP_NAME}" in
  Town01) DEFAULT_MAP_DIR="${BUNDLE_ROOT}/runtime/maps/carla_town01" ;;
  Town04) DEFAULT_MAP_DIR="${BUNDLE_ROOT}/runtime/maps/carla_town04" ;;
  *) echo "unsupported frozen reference map: ${MAP_NAME}" >&2; exit 2 ;;
esac
MAP_VARIANT="$("${BUNDLE_ROOT}/runtime/envs/cage-ad-py310/bin/python" -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["candidate"].get("apollo_map_variant", ""))' \
  "${MANIFEST}")"
if [[ -n "${MAP_VARIANT}" ]]; then
  [[ "${MAP_VARIANT}" =~ ^[a-z0-9_]+$ ]] || {
    echo "invalid frozen Apollo map variant: ${MAP_VARIANT}" >&2; exit 2;
  }
  MAP_DIR="${BUNDLE_ROOT}/runtime/maps/${MAP_VARIANT}"
else
  MAP_DIR="${DEFAULT_MAP_DIR}"
fi
GENERATED="${RUN_DIR}/generated"
APOLLO_CONF_ROOT="${GENERATED}/apollo_conf"
CYBER_ROOT="${GENERATED}/cyber"
LAUNCH=""
STACK_PID=""
INTERPOSER_PID=""
RUN_STARTED_NS="$(date +%s%N)"
CUSTOM_LIBRARY_DIR="$("${BUNDLE_ROOT}/runtime/envs/cage-ad-py310/bin/python" -c \
  'import json,sys; print(json.load(open(sys.argv[1])).get("private_prediction_runtime", {}).get("library_dir", ""))' \
  "${MANIFEST}")"

[[ "${RUN_DIR}" == "${BUNDLE_ROOT}/runtime/runs/pr826_greybox_demo_v1/"* ]] || {
  echo "run directory is outside the canonical PR826 runtime" >&2
  exit 2
}
test -s "${MANIFEST}"
test -s "${MAP_DIR}/base_map.bin"
install -d "${GENERATED}"

stop_stack() {
  if [[ -n "${LAUNCH}" ]]; then
    timeout 10 "${BUNDLE_ROOT}/scripts/apollo_host_exec.sh" bash -c \
      'export APOLLO_CONF_PATH="$1:$APOLLO_CONF_PATH"; export CYBER_PATH="$2"; if [[ -n "$3" ]]; then export LD_LIBRARY_PATH="$3:${LD_LIBRARY_PATH:-}"; fi; shift 3; exec "$@"' bash \
      "${APOLLO_CONF_ROOT}" "${CYBER_ROOT}" "${CUSTOM_LIBRARY_DIR}" cyber_launch stop "${LAUNCH}" \
      >>"${RUN_DIR}/stack.log" 2>&1 || true
  fi
  if [[ -n "${STACK_PID}" ]] && kill -0 "${STACK_PID}" 2>/dev/null; then
    kill -INT -- "-${STACK_PID}" 2>/dev/null || kill -INT "${STACK_PID}" 2>/dev/null || true
    for _ in $(seq 1 15); do
      kill -0 "${STACK_PID}" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "${STACK_PID}" 2>/dev/null; then
      kill -KILL -- "-${STACK_PID}" 2>/dev/null || kill -KILL "${STACK_PID}" 2>/dev/null || true
    fi
    wait "${STACK_PID}" 2>/dev/null || true
  fi
  if [[ -n "${INTERPOSER_PID}" ]] && kill -0 "${INTERPOSER_PID}" 2>/dev/null; then
    kill -INT -- "-${INTERPOSER_PID}" 2>/dev/null || kill -INT "${INTERPOSER_PID}" 2>/dev/null || true
    for _ in $(seq 1 10); do
      kill -0 "${INTERPOSER_PID}" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "${INTERPOSER_PID}" 2>/dev/null; then
      kill -KILL -- "-${INTERPOSER_PID}" 2>/dev/null || kill -KILL "${INTERPOSER_PID}" 2>/dev/null || true
    fi
    wait "${INTERPOSER_PID}" 2>/dev/null || true
  fi
}

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM
  stop_stack
  "${BUNDLE_ROOT}/scripts/manage_carla_bridge.sh" stop \
    >>"${RUN_DIR}/cleanup.log" 2>&1 || true
  "${BUNDLE_ROOT}/scripts/manage_carla_server.sh" stop \
    >>"${RUN_DIR}/cleanup.log" 2>&1 || true
  exit "${exit_code}"
}
trap cleanup EXIT INT TERM

"${BUNDLE_ROOT}/scripts/manage_a1_apollo_stack.sh" stop >"${RUN_DIR}/preclean.log" 2>&1 || true
"${BUNDLE_ROOT}/scripts/manage_carla_bridge.sh" stop >>"${RUN_DIR}/preclean.log" 2>&1 || true
"${BUNDLE_ROOT}/scripts/manage_carla_server.sh" stop >>"${RUN_DIR}/preclean.log" 2>&1 || true

LAUNCH="$("${BUNDLE_ROOT}/runtime/envs/cage-ad-py310/bin/python" \
  "${REPO_ROOT}/scripts/d0/pr826/render_reference_launch.py" \
  --bundle-root "${BUNDLE_ROOT}" --repo-root "${REPO_ROOT}" \
  --output-root "${GENERATED}" --map-dir "${MAP_DIR}" --manifest "${MANIFEST}")"

"${BUNDLE_ROOT}/scripts/manage_carla_server.sh" start >>"${RUN_DIR}/carla.log" 2>&1
"${BUNDLE_ROOT}/scripts/apollo_bridge_exec.sh" python3 \
  "${REPO_ROOT}/scripts/d0/wait_for_carla.py" --timeout 90 >>"${RUN_DIR}/carla.log" 2>&1

CARLA_BRIDGE_CONTROL_TOPIC=/apollo/control \
CAGE_BRIDGE_CONTROL_TELEMETRY="${RUN_DIR}/bridge_control_telemetry.jsonl" \
CARLA_BRIDGE_SETTINGS_FILE="${GENERATED}/bridge_settings.yaml" \
CARLA_BRIDGE_OBJECTS_FILE="${GENERATED}/bridge_objects.json" \
  "${BUNDLE_ROOT}/scripts/manage_carla_bridge.sh" start >>"${RUN_DIR}/bridge.log" 2>&1
sleep 4

if [[ -s "${GENERATED}/p4_sensitivity_config.json" ]]; then
  setsid "${BUNDLE_ROOT}/scripts/apollo_host_exec.sh" bash -c \
    'export APOLLO_CONF_PATH="$1:$APOLLO_CONF_PATH"; export CYBER_PATH="$2"; if [[ -n "$3" ]]; then export LD_LIBRARY_PATH="$3:${LD_LIBRARY_PATH:-}"; fi; shift 3; exec "$@"' bash \
    "${APOLLO_CONF_ROOT}" "${CYBER_ROOT}" "${CUSTOM_LIBRARY_DIR}" python3 \
    "${REPO_ROOT}/scripts/d0/pr826/p4_sensitivity_interposer.py" \
    --config "${GENERATED}/p4_sensitivity_config.json" \
    --telemetry "${RUN_DIR}/private_p4_sensitivity_telemetry.jsonl" \
    --stats "${RUN_DIR}/private_p4_sensitivity_stats.json" \
    >"${RUN_DIR}/private_p4_sensitivity_interposer.log" 2>&1 </dev/null &
  INTERPOSER_PID=$!
  for _ in $(seq 1 40); do
    [[ -s "${RUN_DIR}/private_p4_sensitivity_stats.json" ]] && break
    kill -0 "${INTERPOSER_PID}" 2>/dev/null || break
    sleep 0.25
  done
  test -s "${RUN_DIR}/private_p4_sensitivity_stats.json"
  kill -0 "${INTERPOSER_PID}"
fi

setsid "${BUNDLE_ROOT}/scripts/apollo_host_exec.sh" bash -c \
  'export APOLLO_CONF_PATH="$1:$APOLLO_CONF_PATH"; export CYBER_PATH="$2"; if [[ -n "$3" ]]; then export LD_LIBRARY_PATH="$3:${LD_LIBRARY_PATH:-}"; fi; shift 3; exec "$@"' bash \
  "${APOLLO_CONF_ROOT}" "${CYBER_ROOT}" "${CUSTOM_LIBRARY_DIR}" cyber_launch start "${LAUNCH}" \
  >"${RUN_DIR}/stack.log" 2>&1 </dev/null &
STACK_PID=$!
# Prediction's stock Torch evaluators take roughly 35 seconds to initialize in host mode.
sleep 45
kill -0 "${STACK_PID}"

set +e
APOLLO_EXTRA_PYTHONPATH="${BUNDLE_ROOT}/runtime/bridge/python:${BUNDLE_ROOT}/runtime/bridge/apollo-carla:${BUNDLE_ROOT}/runtime/bridge/carla-agent-deps:${BUNDLE_ROOT}/runtime/carla/0.9.15/PythonAPI/carla:${REPO_ROOT}/src" \
  "${BUNDLE_ROOT}/scripts/apollo_host_exec.sh" python3 \
  "${REPO_ROOT}/scripts/d0/pr826/reference_screen_runtime.py" \
  --manifest "${MANIFEST}" --output "${RUN_DIR}/summary.json" \
  >"${RUN_DIR}/runtime.log" 2>&1
runtime_exit=$?
set -e

test -s "${RUN_DIR}/summary.json"
stop_stack
STACK_PID=""
LAUNCH=""
"${BUNDLE_ROOT}/runtime/envs/cage-ad-py310/bin/python" \
  "${REPO_ROOT}/scripts/d0/pr826/index_native_planning_logs.py" \
  --log-dir "${BUNDLE_ROOT}/runtime/apollo/application-pnc/data/log" \
  --started-ns "${RUN_STARTED_NS}" --output "${RUN_DIR}/native_planning_logs.json"
RUN_ENDED_NS="$(date +%s%N)"
"${BUNDLE_ROOT}/runtime/envs/cage-ad-py310/bin/python" -c \
  'import json,sys; start=int(sys.argv[1]); end=int(sys.argv[2]); print(json.dumps({"started_ns":start,"ended_ns":end,"wall_time_s":(end-start)/1e9},indent=2))' \
  "${RUN_STARTED_NS}" "${RUN_ENDED_NS}" >"${RUN_DIR}/timing.json"
exit "${runtime_exit}"
