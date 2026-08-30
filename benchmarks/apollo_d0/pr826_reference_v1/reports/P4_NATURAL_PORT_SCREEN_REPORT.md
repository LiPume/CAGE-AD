# P4 native PR826-family port screening report

Status: `CANDIDATE_SEMANTIC_DELTA_ABSENT`

Decision: `SCENE_FAULT_PAIR_NOT_ADMITTED`

Date: 2026-08-30 UTC

## Frozen experiment

The screening used `P4_NATURAL_PORT_SCREEN_CONTRACT.yaml`, frozen before either new arm result
(SHA256 `4f0ddab4ee437969c49dc3cae2c9a605d35d37df57230caa5fea565438536268`).
Both arms used the same custom Prediction binary, CARLA scene, map, route, NPC physics policy,
Planning, Control and oracle. The manifest checker found exactly three allowed differences:
`arm`, `screening_id` and the sole behavioral switch
`private_prediction_runtime.domain_active`. No privileged Prediction-output interposer was present.

## Vehicle result

| Arm | Domain | Overtake | Max pass margin | Planning valid | Prediction coverage |
|---|---:|---:|---:|---:|---:|
| QX0_A | fixed/off | yes | +12.089 m | 0.9258 | 0.9391 |
| QX1_A | active/on | yes | +23.880 m | 0.9365 | 0.9502 |

Both arms were runtime-valid and transport-valid, accepted the route, reached the success region,
and had no collision or illegal lane invasion. L4 failed: the active arm did not produce failed
overtake.

## L0–L4 mechanism audit

### L0 — fault activation: PASS

The active Prediction trace contained 4588 target eligibility events in domain 1. Of these, 1535
were STRAIGHT candidates admitted only by the expanded PR826-family eligibility domain.

### L1 — candidate-set semantic delta: FAIL

The expanded STRAIGHT candidate overlapped the ADC trajectory 43 times, but all 43 signed distances
were between 12.326 m and 14.341 m. Zero samples entered the unchanged strict `(0, 10 m)` guard;
therefore zero expanded candidates reached the disable decision.

This is direct evidence that the frozen semantic fault did not alter the candidate set in this
scene. The fault predicate must not be widened after this result.

### L2/L3 — not causally attributable

The independent signature analyzer observed 45 lateral native-output frames in active versus 43 in
fixed and ordinary matched Planning differences. Because L1 never occurred and the physical NPC
itself performs a lane merge, those downstream differences cannot be attributed to the frozen
fault. The causal chain terminates at L1.

### L4 — vehicle failure: FAIL

The active vehicle completed the overtake and reached the success region. No failure oracle was
changed after seeing this result.

## Conclusion and next constraint

The configured physical-merge scene is sensitive to persistent left-lane occupancy, but its native
PR826-family candidate is still outside the modern 10 m nearby-distance guard. This particular
scene–fault pair is closed.

The next allowed action is normal-only scene–fault matching: derive one closer initial longitudinal
geometry from the measured 12.326–14.341 m guard distance, keep the frozen fault unchanged, and
admit the fixed arm before any active run. Moving the target closer is justified only to exercise
the historical nearby predicate, not to tune the final vehicle failure.

## Compact evidence

- Common audit: `P4_NATURAL_PORT_SCREEN_AUDIT.json`, SHA256
  `0c73cff144c31d9266aaf41519d58fa0f47583c7c2c49d4cf6e3337b2f029f55`
- Manifest diff SHA256: `8ffa551c69cbfb50fc8ac5b013b99b8d986113268a84031b3dc80c0bf5cec531`
- Fixed/active manifest SHA256:
  `760e3bb0f7d6f3ef792d369c42f889d24350bbc0a9499bf979a4ffbda1458d5e` /
  `4c499f0af991eeb528d2bd3f78687244d404caedc2562fe78f37edf32161a5e5`
- Fixed/active Prediction trace SHA256:
  `0941fcfbc78b1c2b6d1293318ea51c7fabc3dbc3da3e0abe13744f95bbc66429` /
  `eac473fd3a6a58332f1e4d7d06f41f31b37746ce10b5630667d29480f40bd2bf`

The QX0_A/QX1_A raw run and private audit-view directories were removed after this report, audit
and ledgers validated. Their compact metrics and hashes above remain the canonical evidence.
