#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${1:?usage: $0 RUN_ID STATE_ROOT DATA_ROOT}"
STATE_ROOT="${2:?}"
DATA_ROOT="${3:?}"
: "${CAGE_BUNDLE_ROOT:?}"
: "${CAGE_RUNTIME_ROOT:?}"

[[ "${RUN_ID}" == CARLA_V13_* || "${RUN_ID}" == CARLA_V14_* ]] || {
  echo "invalid v13/v14 run id" >&2
  exit 2
}
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd -P)"
RUN_STATE="${STATE_ROOT}/runs/${RUN_ID}"
RUN_DATA="${DATA_ROOT}/${RUN_ID}"
LOG_ROOT="${RUN_DATA}/logs"
RESULT="${RUN_STATE}/result.json"
TRACE="${RUN_DATA}/trace.jsonl"
SUMMARY="${RUN_DATA}/summary.json"
APOLLO_EXTRA="${CAGE_RUNTIME_ROOT}/bridge/python:${CAGE_RUNTIME_ROOT}/bridge/apollo-carla:${REPO_ROOT}/src"

[[ ! -e "${RESULT}" ]] || { echo "v13 calibration already finished" >&2; exit 2; }
install -d -m 0700 "${RUN_STATE}" "${RUN_DATA}" "${LOG_ROOT}"

cleanup() {
  "${CAGE_BUNDLE_ROOT}/scripts/manage_carla_server.sh" stop >>"${LOG_ROOT}/cleanup.log" 2>&1 || true
}
trap cleanup EXIT INT TERM

"${CAGE_BUNDLE_ROOT}/scripts/manage_carla_bridge.sh" stop >>"${LOG_ROOT}/preclean.log" 2>&1 || true
"${CAGE_BUNDLE_ROOT}/scripts/manage_carla_server.sh" stop >>"${LOG_ROOT}/preclean.log" 2>&1 || true
started_ns="$(date +%s%N)"
"${CAGE_BUNDLE_ROOT}/scripts/manage_carla_server.sh" start >>"${LOG_ROOT}/carla.log" 2>&1
APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" python3 "${REPO_ROOT}/scripts/d0/wait_for_carla.py" --timeout 90 >>"${LOG_ROOT}/carla.log" 2>&1
APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" python3 "${REPO_ROOT}/scripts/d0/repair/load_carla_world_once.py" >>"${LOG_ROOT}/carla.log" 2>&1

set +e
APOLLO_EXTRA_PYTHONPATH="${APOLLO_EXTRA}" "${CAGE_BUNDLE_ROOT}/scripts/apollo_host_exec.sh" python3 "${REPO_ROOT}/scripts/d0/repair/carla_gear_one_conditioned_calibration.py" --trace "${TRACE}" --summary "${SUMMARY}" >"${LOG_ROOT}/calibration.log" 2>&1
runtime_exit=$?
set -e
cleanup
ended_ns="$(date +%s%N)"
powered="$(${CAGE_RUNTIME_ROOT}/envs/cage-ad-py310/bin/python -c 'import sys; print((int(sys.argv[2])-int(sys.argv[1]))/1e9)' "${started_ns}" "${ended_ns}")"

${CAGE_RUNTIME_ROOT}/envs/cage-ad-py310/bin/python - "${RUN_ID}" "${SUMMARY}" "${runtime_exit}" "${powered}" "$(git -C "${REPO_ROOT}" rev-parse HEAD)" "${RESULT}" <<'PY'
import json, os, pathlib, sys
run_id, summary_path, runtime_exit, powered, commit, output = sys.argv[1:]
summary_file = pathlib.Path(summary_path)
summary = json.loads(summary_file.read_text()) if summary_file.exists() else None
result = {
    "schema_version": 1,
    "label": "CONTROL_LOOP_DIAGNOSTIC_NOT_DATASET",
    "run_id": run_id,
    "result": "PASS" if int(runtime_exit) == 0 and summary and summary.get("passed") else "FAIL",
    "runtime_exit": int(runtime_exit),
    "powered_on_seconds": float(powered),
    "source_commit": commit,
    "summary": summary,
}
path = pathlib.Path(output)
temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
os.replace(temporary, path)
print(json.dumps({"result": result["result"], "checks": None if not summary else summary["checks"]}, sort_keys=True))
raise SystemExit(0 if result["result"] == "PASS" else 2)
PY
trap - EXIT INT TERM
