# P3 semantic fixture report

Final status: `P3_SEMANTIC_FIXTURE_PASS`
Recorded: 2026-08-29
Pinned application-pnc commit: `d994e55fb3c3cf88222f8b4813fa5425cc7c1f56`

## Scope and result

P3 verifies a Prediction-internal semantic fixture.  It does not claim a vehicle-level failure,
does not authorize a diagnosis Agent, and does not change Planning, Control, the bridge, CARLA or
the P2 map/configuration.  The frozen candidate reproduces the PR #826 *responsibility family*:
a nearby-candidate filter is applied to a valid non-lane-change candidate because its maneuver
domain is too broad.

All P3 gates passed.  P4 is authorized to perform exactly one faulty screening with this frozen
patch.  P4 may not strengthen or otherwise alter the semantic predicate after observing CARLA.

## Historical bug and Apollo 10 mapping

Historical Apollo repair commit
[`92b7434c4656555d8350fc051e5d1d5c32897db6`](https://github.com/ApolloAuto/apollo/commit/92b7434c4656555d8350fc051e5d1d5c32897db6)
added a LEFT/RIGHT maneuver-type restriction around a nearby lane-sequence filter.  The pinned
Apollo 10 implementation has been refactored: `FilterLaneSequences` now protects `STRAIGHT` and
`INVALID` with an early eligibility gate, while `LEFT`, `RIGHT` and `ONTO_LANE` enter the nearby
branch.  The modern branch also requires overlap with the ADC trajectory, signed distance in
`(0, 10)` metres and the target polygon to remain inside its own lane.

The frozen port changes only the maneuver eligibility domain:

```text
fixed  = LEFT | RIGHT | ONTO_LANE
active = LEFT | RIGHT | ONTO_LANE | STRAIGHT
```

Parking handling, invalid-candidate handling, overlap, signed-distance, polygon, probability,
conflicting-side selection, trajectory generation and validation remain unchanged.  The shared
pure predicate in `nearby_filter_policy.h` is compiled by both the fixture and the production
Prediction overlay, preventing a test-only reimplementation from silently drifting.

## Fixture design and results

The target fixture creates three candidates before filtering:

| ID | type | probability | overlap | signed distance | polygon in own lane | fixed | active |
|---|---:|---:|---:|---:|---:|---:|---:|
| A | STRAIGHT | 0.65 | true | +5 m | true | enabled | disabled |
| B | LEFT | 0.30 | true | +15 m | true | enabled | enabled |
| C | INVALID | 0.05 | true | +5 m | true | enabled | enabled |

Fixed output selects A and emits trajectories for A and B.  Active output removes only A,
selects B, and emits only B.  `changed_candidate_ids` is exactly `["A"]`.

Machine-readable private artifacts are under `runtime/private/sb3_v1/fixture_candidate_01` with
directory mode 0700.  The diff status is `PASS` and records:

- fixed JSON SHA256: `519e57636c30661b6d54548b51e48fc50d12acab5cb322412f688ddc8a5d2b5c`;
- active JSON SHA256: `bf46e07fe28406d99b938007cafa9b2d3b5848cf11ea447a06e8f377cec91d0b`;
- fixture binary SHA256: `2a65eb4208bb969e49d65575c60bde0fdfdc70077ffb94d95af6bacda8aaf367`;
- shared policy header SHA256: `7340834b5af643563a4f6545106a49917b2e2b02e3cfdaa6e20db5308de14305`.

## Controls

- Identity control: the pure fixed policy equals the legacy pinned expression.  In addition, a
  160-frame deterministic runtime stream was sent to stock Prediction and to the optimized port
  binary with its behavior switch disabled.  All 160 common target frames, probabilities and
  trajectory points were exactly equal; normalized semantics SHA256 is
  `54e470d650b899a9751812a571cc4d6a6e78a8c13d760bd292ad636e4bccc5`.
- Wrong-condition control: distance `0`, distance `10`, no overlap, polygon outside, parking and
  invalid cases have identical fixed/active output semantics.  Existing nearby LEFT/RIGHT/
  ONTO_LANE behavior is also unchanged.
- Target-condition control: only candidate A changes under the predeclared trigger.
- Reversibility: switching back to fixed produces the exact fixed JSON SHA above.

The optimized custom component was launched by an absolute private DAG.  The custom flag file was
accepted and `ldd` under the exact launch library order resolved all three Prediction libraries to
the candidate build directory.  This excludes an accidental stock-library identity result.

## Patch and build audit

The semantic patch is `p3_semantic_port/apollo10_semantic_port.patch`:

- semantic patch SHA256:
  `f00cd04565564e85b22b6f4bdabb58c907b6c14044e9ea1d624575d09ac718b6`;
- stock `sequence_predictor.cc` SHA256:
  `8c8ad816ac7aff8caefcd873f8f7c07378e1a678817854fb4d9bd1af14ec4bb5`;
- candidate `sequence_predictor.cc` SHA256:
  `dd61ad35539e30e918325ffb1d4a909cab05bc88eb87d12ba84e5bc156c9122c`;
- optimized behavior library SHA256:
  `251fb80d060f5c43f059ba7b188429d34f9f09be8e92e800a4a3d915a701fa71`;
- optimized component SHA256:
  `0fe5e1e75bb3736e2fe1350c960d04431e83b7531b90a55b61e8c9b35efcff70`.

Apollo's host-mode Bazel dependency macro selected duplicate CPU/GPU libtorch branches in this
overlay workspace.  The separate build-only patch pins the already-installed GPU dependency for
this GPU build; SHA256 is
`54b7aed35992e9781669bcb654ac410ba04b1b973b9fa7ab708c9392e81609fe`.
Both P4 arms use the same component and build-compat patch, so it contributes no matched-arm
behavioral delta.  Reapplying both frozen patches to a clean pinned Prediction tree reproduced the
candidate source hashes exactly.  An optimized `--config=gpu` build completed successfully.

## Negative evidence retained

The append-only research log retains three non-scientific implementation failures: a fixture
compile warning promoted to an error, an initially over-strict wrong-condition trace comparison,
and two host-build failures (duplicate libtorch selection, then absent direct-link search paths).
Each was corrected without changing the predeclared target semantic or weakening a gate.

## Known differences and limitations

- Apollo 10 includes `ONTO_LANE` in the fixed eligibility domain; 2017's repair hunk named only
  LEFT/RIGHT.  The port preserves current stock behavior and broadens it only by STRAIGHT.
- Modern overlap, positive-distance and own-lane polygon guards can prevent activation.
- Later candidate selection or trajectory validation can compensate for an internal delta.
- A fixture PASS does not imply the admitted Town04 scene reaches the trigger.
- Even if Prediction changes, Planning may ignore the affected trajectory or route intent may
  dominate the pass.  Those are P4 outcomes, not reasons to increase the fault dose.

## Gate audit

| Gate | Result |
|---|---|
| Modern responsibility located | PASS |
| Patch and SHA frozen | PASS |
| Fixed target behavior correct | PASS |
| Active exact candidate delta | PASS |
| Runtime identity | PASS |
| Wrong-condition controls | PASS |
| Reversibility | PASS |
| No behavior modification outside Prediction | PASS |
| Private mechanism telemetry | PASS |

Final decision: `P3_SEMANTIC_FIXTURE_PASS`.
