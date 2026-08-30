# Current status

Updated: 2026-08-30 UTC

## Established

- `STABLE_REFERENCE_ADMITTED`: Apollo 10 + CARLA 0.9.15 configured reference passed 3/3.
- The accurate label is **Apollo 10 configured reference**. Prediction and Planning behavior are
  stock; map width metadata, CARLA-Lincoln Control calibration, bridge configuration,
  deterministic timing, and NPC policy are frozen compatibility configuration.
- `P3_SEMANTIC_FIXTURE_PASS`: the frozen Apollo 10 PR826-family port changes only the intended
  candidate-filter responsibility semantic in the function fixture and passes identity,
  wrong-condition, target-condition, and reversibility controls.
- P4-SENS v3 is closed historical evidence: temporary S1 (about 12–40 s) changed/delayed Planning,
  but S1 overtook 3/3. It did not establish failed-overtake scene kill.
- Persistent privileged S1 (about 12–75 s) passed all three prospective pairs:

  | Pair | S0 | S1 | Common-core audit |
  |---|---|---|---|
  | A | overtake, max margin +24.783 m | no overtake, -11.236 m | PASS |
  | B | overtake, max margin +23.267 m | no overtake, -6.253 m | PASS |
  | C | overtake, max margin +19.104 m | no overtake, -6.859 m | PASS |

  All six arms are runtime-valid, transport-valid, semantic-valid and behavior-valid under the
  frozen gates. `STABLE_PERSISTENT_S1_CANCELLATION_3_OF_3` is established. These privileged probes
  are explicitly not admission evidence.

## Not established

- The first natural-port screen on the physical-merge scene reached L0 but not L1: 43 expanded
  overlap events remained at 12.326–14.341 m, outside the unchanged `(0,10 m)` guard. The active arm
  still overtook. This scene–fault pair is rejected.
- A mechanism-derived 12.25 m-gap scene then passed fixed reference 3/3. Its native active screen
  reached L0→L3 (24 candidates disabled, 59 changed sequences consumed, 28 Planning response
  deltas) but recovered and overtook at +18.501 m. L4 failed; this pair is also rejected.
- A normal-only 1.50 m/s temporal-persistence candidate was rejected before any active run. It was
  runtime/route/channel valid and safe, but its +5.556 m maximum pass margin missed the unchanged
  +6.0 m normal gate. The result is a normal-reference capability boundary, not PR826 evidence.
- The bracketed 1.30 m/s normal screen passed at +11.912 m with 0.9425 Prediction trajectory
  coverage and no collision/illegal lane invasion. Its 0.536 m minimum clearance is explicitly
  retained as a response metric. Formal fixed repeats then passed 3/3 at
  +11.630/+7.937/+13.487 m with identical normalized manifests, which authorized one matched
  native screen.
- Its matched native screen is now closed: fixed passed +14.272 m and active passed +13.185 m.
  L0 executed, but all ten expanded candidates inside 9.455–9.969 m had
  `polygon_in_own_lane=0`, so L1 produced zero disables. Apparent L2/L3 differences are not causal
  evidence without L1. This is another scene–fault mismatch, not a golden case.
- No PR826 L0→L4 causal chain or golden case is admitted.
- No diagnosis Agent, probability claim, repair, or animation is in scope yet.

## Current gate

`DELAY9_NORMAL_REFERENCE_REJECTED_EARLY_STOP`

The v5 sensitivity contract is closed without further tuning. Three native-port scene pairs are
closed without changing the fault: QX missed the distance guard at L1; QY reached L3 but recovered
before L4; QZ entered the distance guard but failed the modern own-lane polygon guard at L1. The
1.50 m/s normal candidate failed its frozen normal gate and never received an active run. None is
golden-case admission.

## Only next action

Delayed-onset F1 produced one illegal lane invasion, so the candidate is rejected and F2/F3/active
were not run. Reassess scene–fault compatibility from the accumulated QX/QY/QZ guard evidence
before proposing another normal-only candidate; do not continue merge-timing tuning by outcome.

## Current contracts and canonical reports

- Closed delayed-onset screen contract: `contracts/P4B_SPEED130_DELAY9_NORMAL_SCREEN_CONTRACT.yaml`
- Closed delayed-onset repeat contract: `contracts/P4B_SPEED130_DELAY9_NORMAL_REPEAT_CONTRACT.yaml`
- Latest closed native contract: `contracts/P4B_SPEED130_NATURAL_SCREEN_CONTRACT.yaml`
- Completed repeat contract: `contracts/P4B_SPEED130_NORMAL_REPEAT_CONTRACT.yaml`
- Completed screen contract: `contracts/P4B_SPEED130_NORMAL_SCREEN_CONTRACT.yaml`
- Closed persistent-sensitivity contract: `P4_SENS_V5_CONFIRMATION_CONTRACT.yaml`
- Canonical configured-reference report: `reports/FINAL_REFERENCE_REPORT.md`
- Canonical persistent-sensitivity report: `reports/P4_PERSISTENT_SENSITIVITY_REPORT.md`
- Canonical persistent-sensitivity aggregate: `reports/aggregate.json`
- Latest native-port screen: `reports/P4_NATURAL_PORT_SCREEN_REPORT.md`
- Latest L0→L3 native screen: `reports/P4B_GAP1225_NATURAL_SCREEN_REPORT.md`
- Latest normal-only boundary screen: `reports/P4B_SPEED150_NORMAL_SCREEN_AUDIT.json`
- Current normal screen: `reports/P4B_SPEED130_NORMAL_SCREEN_AUDIT.json`
- Current fixed-repeat audit: `reports/P4B_SPEED130_NORMAL_REPEAT_AUDIT.json`
- Delayed-onset early-stop audit: `reports/P4B_SPEED130_DELAY9_REPEAT_EARLY_STOP_AUDIT.json`
- Latest native screen: `reports/P4B_SPEED130_NATURAL_SCREEN_REPORT.md`
- Canonical machine state: `run_state.yaml`

## Explicit non-claim

The established sensitivity conclusion is limited to:

> Persistent Prediction semantic occupancy is a reproducible system-level failure amplifier in
> this configured scenario.

It does **not** establish that PR826 naturally produces the same phenotype.
