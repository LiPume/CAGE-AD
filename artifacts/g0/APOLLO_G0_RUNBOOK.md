# Apollo 10 G0 replay runbook

Run every command from `${CAGE_BUNDLE_ROOT}`. Apollo/CyberRT commands are launched by the provided host-mode wrappers; do not activate Conda and do not use Docker. This checked-in copy normalizes the original server path; its original checksum is recorded in `SOURCE_PROVENANCE.yaml`.

## Health and startup

```bash
scripts/verify_bundle.sh
scripts/manage_carla_server.sh start
scripts/manage_carla_server.sh status
```

CARLA is off-screen and bound to the container-private interface. Wait for the manager to report a live PID before running a gate.

## A0 rendered sensor gate

```bash
scripts/apollo_bridge_exec.sh python3 \
  "${CAGE_BUNDLE_ROOT}/scripts/a0_carla_sensor_gate.py" \
  --wall-seconds 1800 \
  --output "${CAGE_STATE_ROOT}/../evidence/a0/replay_1800s.json"
```

The output must report synchronous 0.05-second ticks, rendering enabled, non-empty RGB/LiDAR payloads, monotonic aligned timestamps, and `PASS`.

## A1 closed loop

Use a new positive run index to avoid confusing evidence provenance:

```bash
scripts/run_a1_repetition.sh 5
```

The script clean-starts and cleans the bridge/Apollo stack while retaining the CARLA server. The JSON result must pass route, planning, control, motion, lane, timing, and semantic-heartbeat criteria.

## A2 diagnostic chain

```bash
scripts/run_a2_repetition.sh 5
```

This creates a root-only evaluator area and a UID-1001 diagnosis area, injects the fixed control delay, queries the L1 `tracking_execution` window, applies the non-GT I2 brake probe, evaluates the oracle separately, and cleans all Apollo/bridge processes.

To reproduce the clean-shell audit:

```bash
env -i HOME=/root USER=root LOGNAME=root LANG=C.UTF-8 \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  TERM=xterm-256color bash --noprofile --norc scripts/run_a2_repetition.sh 6
```

## Contract and Guardian validation

```bash
runtime/envs/guardian-py310/bin/python scripts/validate_contracts.py \
  --bundle-root "${CAGE_BUNDLE_ROOT}"

cd project/CAGE-AD
python -m pytest -q
cd ../..
```

CAGE-AD's CPU-only test suite is self-contained. The historical project dependency from the original runbook is intentionally not retained.

## Shutdown and residual check

```bash
scripts/manage_a1_apollo_stack.sh stop
scripts/manage_carla_bridge.sh stop
scripts/manage_carla_server.sh stop
ps -eo pid,args | grep -E 'CarlaUE4|carla_bridge.main|a2_control_interposer|mainboard' | grep -v grep || true
```

The final command must print no managed runtime process. Private A2 evaluator directories must remain mode `0700`; do not make them diagnosis-readable.
