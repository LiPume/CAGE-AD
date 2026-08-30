# PR826 research log

This file is the concise historical record after the 2026-08-30 repository cleanup. Closed-run
raw artifacts were intentionally removed when no current experiment consumed them. Detailed
tool/change events that remain useful are in `ledgers/fix_ledger.jsonl`.

## P1 — Prediction bring-up

Apollo 10 stock Prediction was brought up in host AEM mode and validated on the CARLA bridge.
The target obstacle appeared consistently and produced real trajectories. Credential scans did not
find the user-provided API key in the workspace.

Outcome: Prediction pipeline available; later work must preserve obstacle ID, timestamps,
probabilities and trajectory structure unless a preregistered semantic intervention says otherwise.

## P2 — configured normal reference

### Early RF01 rejection

The first stationary-obstacle reference passed once and then failed its first frozen repeat. Both
the pass and failure had zero target trajectories, so this was a Planning static LaneBorrow case,
not a Prediction→Planning case. `CASE_NOT_ADMITTED` applied only to RF01.

### Town04 exploration

The useful target speed band was around 1.10 m/s: above Apollo 10 Prediction's 0.99 m/s still
threshold, so trajectories were present. A route-driven pass was necessary because Apollo 10
LaneBorrow treats a trajectory-bearing moving obstacle as non-static; raising only Planning's
static speed threshold did not change that classification.

Several candidate families were rejected for concrete reasons: missing Town04 road-width metadata,
route-reference-line failure, NPC curvature drift, Traffic Manager/BasicAgent low-speed instability,
Control calibration mismatch, early interaction timing variance, insufficient clearance, and
kinematic pose-override designs that violated the no-teleport rule. These failures motivated:

- metadata-only road-width repair;
- frozen CARLA-Lincoln low-speed Control calibration;
- synchronous 0.05 s world timing and deterministic startup order;
- a 1.10 m/s NPC policy that follows only the current lane tangent and reads neither Apollo output
  nor future ground truth.

### Admitted reference

Town04 configured reference passed 3/3 with Prediction coverage 0.9839/0.9870/0.9870, Planning-valid
ratios 0.9477/0.9551/0.9415, overtake times 39.00/38.75/44.45 s, pass margins
25.507/26.457/23.625 m, and no collision or illegal lane invasion.

Outcome: `STABLE_REFERENCE_ADMITTED`. Correct label: **Apollo 10 configured reference**, not
unmodified stock Apollo. Prediction and Planning behavior are stock; map, Control, bridge and
deterministic NPC policy are compatibility configuration. Canonical details are in
`reports/FINAL_REFERENCE_REPORT.md`.

P1/P2 exploratory raw runs, candidate audits, debug timelines and obsolete checkpoints were
removed during cleanup after these conclusions were consolidated here and in the final report.

## P3 — PR826-family semantic fixture

Historical PR #826 fixed an overly broad nearby lane-sequence filter by requiring the appropriate
lane-change maneuver type. Apollo 10 contains additional guards and a refactored execution chain.
The semantic port therefore changes only the modern maneuver eligibility domain: active mode lets
STRAIGHT enter the nearby filter alongside LEFT/RIGHT/ONTO_LANE; every other guard remains fixed.

The fixture creates controlled STRAIGHT/LEFT/INVALID candidates. Fixed keeps and selects STRAIGHT;
active incorrectly removes STRAIGHT and selects the lateral candidate. Identity, wrong-condition,
target-condition and reversibility controls passed, including a 160-frame runtime identity check.

Outcome: `P3_SEMANTIC_FIXTURE_PASS`. This proves the candidate-filter semantic mechanism only; it
does not prove a native output phenotype, Planning response or vehicle failure. See
`reports/P3_SEMANTIC_MAPPING.md` and `reports/P3_SEMANTIC_FIXTURE_REPORT.md`.

## P4B — first natural port/scene mismatch

The frozen port activated in a close-gap route-driven scene and changed native Prediction frames;
Planning consumed changed headers. The semantic delta ended before the route lane-change path, so
the route dominated behavior and the vehicle still passed.

Outcome: scene–fault pair rejected. The patch was not strengthened after the result.

## P4-SENS v3 — temporary interface probe

The non-admission probe compared S0 straight, S1 left-merge occupancy and S2 no trajectory while
preserving all unrelated protobuf fields. S1 was active only about 12–40 s. Across three matched
S0/S1 pairs it changed Planning and delayed +6 m progress by 5.80, 4.65 and 20.50 s, but all three
S1 runs ultimately overtook and lane-entry timing direction was inconsistent.

Outcome: temporary Prediction→Planning sensitivity established; failed-overtake scene kill not
established. The experiment was closed. Later analysis found the intervention had ended well before
the 58.75–63.10 s S1 overtake outcomes. That is a design limitation, not bad data or permission to
reinterpret v3. V3 raw runs and intermediate audits were removed after this record was consolidated.

## P4-SENS v4/v5 — persistent privileged probe

V4 changed only temporal coverage: the same 3.5 m left-merge semantic over relative prediction
time 2–4 s was renewed from about 12–75 s. The contract was frozen before execution.

Pair A: S0 overtook (+24.783 m max margin); S1 did not (-11.236 m). Both arms passed runtime,
transport, semantic preservation, persistence, matched-manifest and safety checks.

V5 prospectively preregistered Pair A plus confirmation pairs B/C without changing any gate.
Pair B repeated the result: S0 overtook (+23.267 m); S1 did not (-6.253 m), with both arms valid.

The first auditors encoded versions directly and conflated legacy `infrastructure_valid` with
Planning response quality. Cleanup introduced one contract adapter and common core with explicit
`runtime_valid`, `transport_valid`, `semantic_valid`, `behavior_valid` and `admission_valid`.
Regression reproduced Pair A's logical conclusion and Pair B passed. No run data, contract or gate
changed. After repository cleanup, the already completed PZ0_C was audited first and passed every
frozen S0 gate: overtake success, +19.104 m maximum margin, runtime/transport/semantic/behavior
valid. Only then was PZ1_C authorized. Its runtime returned the expected normal-oracle nonzero code
because no overtake occurred; the layered audit showed no runtime or transport failure. S1 remained
at -6.859 m, with 1260 preserved 3.5 m transformations through 74.95 s.

Pair C passed all ten common-core checks. Across A/B/C, S0 overtook 3/3 and S1 did not overtake
3/3. Normalized S0 and S1 manifests were identical across repetitions. Outcome:
`STABLE_PERSISTENT_S1_CANCELLATION_3_OF_3`. Sensitivity tuning is closed.

Supported claim: persistent Prediction semantic occupancy is a reproducible system-level failure
amplifier in this configured scenario. It does not prove that PR826 naturally creates the same
phenotype. Canonical evidence is `reports/P4_PERSISTENT_SENSITIVITY_REPORT.md` and
`reports/aggregate.json`.

## Next natural PR826 gate

Sensitivity confirmation is complete. The frozen semantic port may now be evaluated as:

1. L0 fault activation;
2. L1 candidate-set semantic delta;
3. L2 native Prediction output phenotype;
4. L3 Planning consumes/responds;
5. L4 vehicle-level failed overtake.

If L0/L1 occurs without the required L2 phenotype, the scene–fault pair closes. Fault dose must not
be increased to manufacture L4.

## P4 native-port screen 01 — physical-merge scene rejected at L1

After persistent sensitivity passed 3/3, one matched native-port pair was frozen before execution.
There was no interface interposer; the only behavioral manifest difference was the frozen
Prediction maneuver-domain switch. Fixed QX0_A overtook with +12.089 m margin. Active QX1_A also
overtook with +23.880 m margin; both arms were runtime/transport valid and safe.

Private Prediction telemetry proved L0: domain 1 executed 4588 target eligibility events and
expanded STRAIGHT eligibility 1535 times. L1 did not occur. The expanded candidate overlapped 43
times, but signed distance was always 12.326–14.341 m, never inside the unchanged `(0,10 m)` nearby
guard, so no expanded candidate was disabled. Apparent downstream trajectory/Planning differences
were classified incidental to the physical NPC merge because the causal prerequisite L1 failed.

Outcome: `CANDIDATE_SEMANTIC_DELTA_ABSENT`; this scene–fault pair is closed without changing the
fault. The next permitted search is normal-only and mechanism-derived: move the initial target
geometry closer enough to exercise the existing historical nearby guard, validate the fixed arm
first, then freeze any active screening.

## Cleanup record

The cleanup removed obsolete P1/P2 candidate runs, closed P4B/v3 runs, duplicate state/report
copies, intermediate contracts/audits/ledgers, one-off scripts, caches and temporary logs. Pair A/B
large timelines/telemetry were removed only after compact common audits and normalized manifest
hashes were validated. Pair C raw output was retained through its common audit and aggregate, then
became eligible for the same compact retention policy. Apollo/CARLA/map/build assets remain for the
native mechanism screen.
