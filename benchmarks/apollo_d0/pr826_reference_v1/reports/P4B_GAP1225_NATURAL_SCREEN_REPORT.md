# P4B gap-12.25 native PR826-family screening report

Status: `SCENE_FAULT_PAIR_NOT_ADMITTED`

Date: 2026-08-30 UTC

## Normal-only admission

The target was moved exactly 4.0 m closer only after the prior scene showed every expanded overlap
outside the unchanged 10 m guard. No active result for this geometry existed during design.

The fixed/inactive candidate passed its screening and then three frozen formal repeats:

| Run | Max pass margin | Prediction coverage | Planning valid |
|---|---:|---:|---:|
| RN_G1225_F1 | +18.861 m | 0.9422 | 0.9536 |
| RN_G1225_F2 | +12.843 m | 0.9314 | 0.9326 |
| RN_G1225_F3 | +20.353 m | 0.9372 | 0.9530 |

All repeats overtook, reached the success region and had no collision, illegal lane invasion or
runtime exception. The normalized manifests were identical. The active arm was authorized only
after `STABLE_NORMAL_REFERENCE_3_OF_3`.

## Matched native-port screen

Contract SHA256: `b8e36d2505c1ecc6178020c6001d19a245af1213cc727f8d4440cfe426a6364d`.
The QY manifests differed only in `arm`, `screening_id` and the frozen native Prediction domain
switch. There was no privileged Prediction-output intervention.

| Arm | Overtake | Max margin | Prediction coverage | Planning valid |
|---|---:|---:|---:|---:|
| QY0_A fixed | yes | +15.784 m | 0.9372 | 0.9311 |
| QY1_A active | yes | +18.501 m | 0.9314 | 0.9415 |

## L0–L4 result

- L0 PASS: 4522 target events executed in active domain; 1513 expanded STRAIGHT eligibility events.
- L1 PASS: 75 expanded candidates entered the nearby guard and 24 were disabled.
- L2 PASS: active produced 67 frozen lateral-signature frames versus 43 fixed.
- L3 PASS: Planning consumed 59 changed native Prediction sequences; 28 consuming frames differed
  categorically or by at least 1 m planned horizon from fixed.
- L4 FAIL: active recovered, completed the overtake and reached the success region.

The attributable native-output/Planning window was approximately elapsed 8.9–14.7 s. It changed
Planning while active, but the system recovered after the transient candidate filtering episode.
No failure threshold or fault predicate was changed after observing this result.

## Decision

This scene–fault pair is rejected and no faulty formal repeats are authorized. It proves a native
L0→L3 propagation path but not vehicle-level failed overtake.

The next scene search may change normal geometry/target motion only to keep the existing nearby
guard active during the decision interval. A single normal-only candidate with lower ego–target
relative speed is justified by the observed transient window. The semantic patch, 10 m guard,
Planning, Control and failure oracle remain frozen.

Canonical machine evidence:

- `P4B_GAP1225_NORMAL_REPEAT_AUDIT.json`
- `P4B_GAP1225_NATURAL_SCREEN_AUDIT.json`
