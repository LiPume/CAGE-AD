# P4-SENS Prediction-to-Planning Semantic Sensitivity Plan

Status: `NON_ADMISSION / CAUSAL_SENSITIVITY_PROBE`

## Question

Does Apollo Planning materially change its lane-change, path, or speed behavior when the same
target obstacle is predicted to merge left into ego's adjacent overtaking lane, compared with a
straight prediction and a no-trajectory control?

This probe is deliberately more privileged than the future diagnosis path. It is a mechanism kill
criterion, not a benchmark arm, natural fault, golden-case result, or paper performance result.

## Scene and timing

Use the immutable `SN_N01_A` P2N manifest as the world source because it already demonstrated:

- a physics-generated target merge from CARLA lane -3 into lane -2;
- Prediction trajectory coverage `0.939055`;
- Planning valid ratio `0.940990`;
- target lane entry at 11.0 s, before the 52.7 s pass outcome;
- 95 post-entry trajectory-bearing Planning overlap frames.

P2N remains rejected for golden-case admission because its minimum body clearance was 0.794307 m
against the frozen 0.90 m gate. P4-SENS cannot change or override that disposition.

The semantic probe is active from observation elapsed time 12.0 through 40.0 s, after the target is
settled in lane -2 and before the normal pass. A left-merge trajectory begins lateral motion at
relative prediction time 2.0 s and finishes at 4.0 s.

## Matched semantics

- `S0_STRAIGHT`: forward the raw stock Prediction message byte-for-byte.
- `S1_LEFT_MERGE_OCCUPANCY`: preserve the message header, target obstacle ID, perception state,
  obstacle count, trajectory count, probabilities, point count, relative times, speed and
  acceleration. Change only each target trajectory's path-point x/y/theta so it moves one 3.5 m
  lane width along the left normal between 2 and 4 s and then occupies the adjacent lane.
- `S2_NO_TRAJECTORY`: preserve the same fields but clear only the target's trajectory list during
  the same active window.

No future CARLA ground truth is read. The S1 path is an explicit hypothesis constructed from the
current prediction tangent and the frozen Town04 lane width; it is not an oracle replacement.

## Interface isolation

Prediction publishes to `/apollo/prediction_raw`. A dedicated private interposer reads that topic
and writes `/apollo/prediction`, which is the unchanged Planning input. The interposer must abort on
missing target identity or invalid trajectories; it must never control ego or edit Planning,
Control, bridge, CARLA, map, route, NPC physics, or success logic.

Private telemetry records input/output hashes and a field-level preservation audit. It is excluded
from future diagnosis-visible data.

## Execution and kill criteria

Run one matched screen for S0, S1, and S2. If S1 does not produce a clear Planning delta relative
to S0, close this scene without confirmation repeats. A clear delta means at least one predeclared
Planning effect during or after the active interval:

1. lane-change or selected-path availability changes for at least 1.0 continuous second;
2. ego entry into lane -1 is delayed by at least 5.0 s or absent by 60.0 s;
3. planned longitudinal progress over a matched 5 s window drops by at least 5.0 m; or
4. target obstacle longitudinal/lateral decision or ST treatment changes in a structured Planning
   field for at least five consecutive Planning cycles.

If a screen-level delta exists, execute two additional S0 and two additional S1 repeats. Stable
sensitivity requires the same predeclared effect direction in all three S0/S1 pairs. S2 remains a
single diagnostic control unless its infrastructure result is invalid.

This probe does not require a collision, failed overtake, or success-oracle classification. Any
system behavior is descriptive only; the decisive result is Planning's response to the semantic
boundary change.

## PR826 follow-up

Only after stable S1 sensitivity is established, inspect private native candidate telemetry. The
historical semantic route is admitted for further work only if an unmodified frozen PR826 port
naturally produces:

1. fixed: a straight candidate is enabled and emitted;
2. faulty: that same straight candidate is disabled by the nearby predicate;
3. a pre-existing lateral candidate remains enabled;
4. the emitted target trajectory changes to the same left-occupancy semantic tested by S1.

Deleting straight without emitting a left trajectory is insufficient. In that case the result is
`MECHANISM_ACTIVATED_NO_PLANNING_LEVEL_PR826_CASE`, not a PR826 replication.

