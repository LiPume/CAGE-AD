# Reproduction best practices

## Stable configured reference

- Apollo 10 host AEM mode; CARLA 0.9.15 Town04; seed 82601.
- Synchronous world, fixed delta 0.05 s, substepping 0.01 s ×10, ClearNoon, no background actors
  or Traffic Manager.
- Start in this order: CARLA → RPC ready → bridge reload/ego spawn → Apollo stack → 45 s Prediction
  initialization → route/NPC runtime.
- Use the frozen configured map, V17 CARLA-Lincoln calibration, bridge settings and current-lane
  tangent NPC policy from the canonical reference contract/report.
- NPC speed is 1.10 m/s. It must not read Apollo output or future ground truth. Apollo remains the
  sole ego controller.
- Do not call this unmodified stock Apollo: Prediction/Planning behavior is stock, compatibility
  configuration is not.

## Deterministic actor lifecycle

- A successful spawn RPC is command acceptance, not proof that actor state is materialized. Wait
  for the next synchronous snapshot before validating pose, road/lane and physics state.
- Validate road ID and lane ID; lane ID alone is not globally unique.
- Abort invalid transforms rather than projecting actors into a visually plausible scene.
- Record spawn order, actor IDs, frame/timestamps and resolved road/lane.
- Keep exactly one synchronous tick owner (the bridge in this setup).

## Scientific gates

- Freeze contract, semantic dose, time window, run IDs and oracle before results.
- Separate implementation validity, runtime/transport validity, semantic validity, arm behavior and
  admission. A generic legacy `infrastructure_valid` flag is not a substitute.
- Planning-valid ratio, optimizer failures and fallback can be downstream response or baseline
  quality metrics. Do not label them infrastructure failures when route/channels/runtime are valid.
- Preserve unrelated Prediction fields during boundary interventions: header, ID, timestamp,
  obstacle count/state, probability, point count/time, velocity and acceleration.
- A sensitivity probe is privileged non-admission evidence. Never present it as a natural PR826
  run.
- Never promote pass delay or smaller margin to `FAILED_OVERTAKE` after observing results.

## Temporal coverage

An interface transform that renews a 2–4 s future trajectory is present only while the transform is
active. Cover the downstream decision/outcome window plus the declared prediction horizon. Record
first/last transformed message, first Planning consumption and outcome time. Any window correction
requires a new frozen contract and new runs; the earlier result remains unchanged.

## Current persistent confirmation

- S0: byte-exact straight Prediction.
- S1: target left-normal smoothstep, 3.5 m over relative 2–4 s, renewed at elapsed 12–75 s.
- Pair audit requires matched allowed deltas, runtime-valid, transport-valid, semantic-valid,
  collision/lane-safe behavior, S0 overtake and S1 no overtake.
- Pair A/B raw payloads may be removed after compact common audits contain final metrics and
  normalized repeat-manifest hashes.
- Stop sensitivity tuning after 3/3. The next stage must test the frozen native PR826 port through
  L0 activation → L1 candidate delta → L2 output phenotype → L3 Planning response → L4 failure.

## Common errors and fixes

- Apollo protobuf tests fail under Conda with `ModuleNotFoundError: modules`: run them through
  `scripts/apollo_host_exec.sh`; Apollo/Cyber remain outside Conda.
- Version-specific auditor rejects a later contract: do not alter the frozen contract. Use the
  common schema adapter/core and add a regression test.
- Runner exits 3 while transport is healthy: inspect layered audit output; the old runner may be
  enforcing a normal-reference Planning-valid gate that is a response metric for sensitivity runs.
