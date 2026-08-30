# Reproduction best practices and verified recipes

This is a living operational companion to `FINAL_REFERENCE_REPORT.md`, `RESEARCH_LOG.md`, and the
machine ledgers. It records only practices supported by repeated evidence. A candidate screen is
not promoted to a verified recipe until its formal gate passes.

## Verified stable reference recipe

The only admitted normal recipe remains P2 `STABLE_REFERENCE_ADMITTED`:

- Apollo 10 host mode, CARLA 0.9.15, Town04, seed 82601.
- Deterministic reload before every run; synchronous mode, fixed delta 0.05 s, substepping 0.01 s
  × 10, ClearNoon, no background actors and no Traffic Manager.
- Start order: CARLA server, RPC readiness, deterministic bridge reload/ego spawn, Apollo stack,
  45 s Prediction model initialization, then route/NPC runner.
- Use candidate `RF04_13_SLOW_110_LANE_TANGENT_LC_LONG_80S_MAP_WIDTH_V1_CTRL_V17`, configured map
  `carla_town04_road_width_v1`, V17 Control calibration and the 80 s oracle exactly as frozen.
- NPC speed is 1.10 m/s and yaw follows only the current driving-lane tangent. Position is not
  projected, ego/Apollo output is not read, and future GT is never read.
- Before execution, verify `reference_repeat_contract_v2.yaml` SHA256
  `163f523d2d552cc5627efcce67df01d074db7ea6d52d28c6ea99831f1946dfe2` and all artifact hashes
  listed in that contract. The ordered admitted manifest SHA256 is
  `c7c7d8dd90861e994dd5565007b8433a45670f09b1129da5ad6f6a041af3c8de`.
- Judge every repeat using `FORMAL_REPEAT_V2_AUDIT.json`; do not substitute a later threshold.

Authoritative evidence: `FINAL_REFERENCE_REPORT.md`, `FORMAL_REPEAT_V2_AUDIT.json`,
`reference_repeat_contract_v2.yaml`, and the three immutable runtime manifests.

## Proven simulator lifecycle practices

1. Treat a successful spawn RPC as command acceptance, not proof that actor state is already
   materialized. In synchronous CARLA, wait for a subsequent world snapshot before deriving pose,
   waypoint, lane-relative offset, velocity, or physics-dependent state.
2. After materialization, validate the actor XY against the frozen spawn and validate both road ID
   and lane ID. Lane ID alone is not globally unique.
3. Abort on an invalid transform instead of projecting or correcting the actor into the scene.
   Silent projection can create a visually plausible but scientifically different run.
4. Record the pre-frame, materialized frame, XY error, resolved road/lane, signed offset, actor ID
   and spawn order in the run summary.
5. Use the bridge-owned synchronous tick. Do not introduce a second tick owner.

Evidence: `P2H_IMPLEMENTATION_INVALID_AUDIT.json` and
`P2I_IMPLEMENTATION_INVALID_AUDIT.json`. The isolated P2I probe observed `(0,0,0)` immediately
after spawn and the exact frozen pose after one synchronous tick.

## Gate and debugging discipline

- Freeze contract, candidate canonical hash, environment hash, runtime hash and oracle before a
  screening run. Use a new opaque run ID for every execution.
- Preserve every failed and implementation-invalid run. Never overwrite a manifest or reuse its
  run ID.
- Separate implementation validity, mechanism validity and behavioral admission. A successful
  overtake does not compensate for zero Prediction trajectory coverage or a wrong target lane.
- For any rejection, record the first violated invariant and retain summary, timeline, native logs,
  bridge telemetry and checksums.
- Correct an implementation defect only with a new contract. Do not change scientific parameters
  while repairing instrumentation.
- Run fixed-only screening first, then freeze a 3-repeat fixed contract. An active fault run is
  forbidden until the fixed scene passes 3/3.

## Known non-recipes

- Static RF01: nonrepeatable and no target trajectories.
- P2B active pair: semantic output changed but route dominated Planning.
- P2C: moving target did not satisfy LaneBorrow's long-term blocking gate.
- P2D/P2E: lateral-offset candidates failed frozen formal gates.
- P2F: first lane-change path missed its frozen timing gate.
- P2G: interaction window passed, but fixed Planning-valid and clearance gates failed.
- P2H/P2I: implementation-invalid waypoint/actor-lifecycle runs; never use as scientific evidence.
- P2J: lifecycle and interaction valid, but Planning-valid ratio 0.893484 missed the frozen 0.90
  normal gate; stop-and-go family closed without formal or active runs.

Future entries must distinguish `VERIFIED`, `SCREEN_ONLY`, `REJECTED`, and
`IMPLEMENTATION_INVALID` explicitly.
