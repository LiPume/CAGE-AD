#!/usr/bin/env bash
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
RUN_INDEX="${1:?usage: $0 RUN_INDEX}"
if [[ ! "${RUN_INDEX}" =~ ^[1-9][0-9]*$ ]]; then
  echo "RUN_INDEX must be a positive integer" >&2
  exit 2
fi
OUTPUT="${BUNDLE_ROOT}/runtime_state/evidence/a1/run_${RUN_INDEX}.json"

cleanup() {
  trap - EXIT INT TERM
  "${BUNDLE_ROOT}/scripts/manage_a1_apollo_stack.sh" stop || true
  "${BUNDLE_ROOT}/scripts/manage_carla_bridge.sh" stop || true
}
trap cleanup EXIT INT TERM

"${BUNDLE_ROOT}/scripts/manage_a1_apollo_stack.sh" stop
"${BUNDLE_ROOT}/scripts/manage_carla_bridge.sh" stop
"${BUNDLE_ROOT}/scripts/manage_carla_server.sh" status
"${BUNDLE_ROOT}/scripts/manage_carla_bridge.sh" start
sleep 5
"${BUNDLE_ROOT}/scripts/manage_a1_apollo_stack.sh" start
sleep 15
"${BUNDLE_ROOT}/scripts/apollo_bridge_exec.sh" python3 \
  "${BUNDLE_ROOT}/scripts/a1_closed_loop_run.py" \
  --run-id "${RUN_INDEX}" --output "${OUTPUT}" --duration 45
