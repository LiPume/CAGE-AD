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

## P4B gap-12.25 screen 02 — native propagation recovered before L4

One normal-only candidate moved the same physical NPC exactly 4.0 m closer, from 16.25 m to
12.25 m nominal gap, based solely on the prior measured distance-guard miss. Screening passed and
three formal fixed repeats passed with margins +18.861/+12.843/+20.353 m, matched normalized
manifests, valid channels and no safety event.

Only after that 3/3 admission, a matched native pair was run. The frozen fault reached L0→L3:
1513 expanded STRAIGHT eligibility events, 24 erroneous candidate disables, 67 active lateral
output frames versus 43 fixed, 59 changed headers consumed by Planning and 28 response-delta
frames. Nevertheless the active arm recovered and overtook at +18.501 m.

Outcome: `SCENE_FAULT_PAIR_NOT_ADMITTED`. The native fault is causal through Planning but transient
at roughly elapsed 8.9–14.7 s and does not create L4 in this scene. No faulty repeats were run. The
next mechanism-derived normal-only search may reduce relative speed to extend time inside the same
guard; the fault predicate and oracle remain unchanged.

## P4B speed-1.50 normal screen — rejected before active testing

The first temporal-persistence candidate kept the admitted 12.25 m geometry and changed only the
physical NPC target speed from 1.10 to 1.50 m/s. The manifest and normal-only contract were frozen
before the run, with SHA256 values `2c29b8eb...647a7419` and `507b080d...24cb200`. No active
Prediction fault was enabled or observed for this geometry.

`RN_V150_S1` was runtime/route/channel valid, safe, entered the legal adjacent lane, reached the
success region, and retained target Prediction trajectory coverage 0.9478. It nevertheless reached
only +5.556 m maximum pass margin, below the unchanged +6.0 m gate, so the frozen normal oracle
returned `STOCK_REFERENCE_NO_OVERTAKE`. Planning-valid ratio was 0.9018 and is retained only as a
response metric, not reclassified as an infrastructure failure.

Outcome: `NORMAL_CANDIDATE_REJECTED`; no fixed repeats and no active run are authorized. This
rejects 1.50 m/s as a normal reference at the frozen 80 s horizon. The result does not say anything
about PR826 propagation. Raw runtime artifacts were removed after the compact machine audit was
written. A subsequent normal-only candidate, if attempted, must remain between the stable 1.10 m/s
reference and this rejected upper speed and must be frozen before execution.

## P4B speed-1.30 normal reference — stable 3/3

The midpoint normal-only screen changed only physical NPC speed from 1.10 to 1.30 m/s and passed
at +11.912 m margin. Its contract then froze three fixed repeats before any active execution.
`RN_V130_F1/F2/F3` all passed the unchanged gate with margins +11.630/+7.937/+13.487 m,
Prediction trajectory coverage 0.9425/0.9367/0.9478, Planning-valid ratios
0.9226/0.9148/0.9172, and identical normalized manifests. All three were route/runtime/channel
valid with zero collision and zero illegal lane invasion.

Minimum bbox clearances were 0.531/0.942/0.968 m. These values are retained because the first run
has limited geometric margin; they were not introduced as post-result admission gates. Outcome:
`STABLE_NORMAL_REFERENCE_3_OF_3`. One matched native fixed/active screen is now permitted under a
new contract; this result alone contains no active PR826 evidence.

## P4B speed-1.30 native screen — modern polygon guard compensates

After fixed 3/3, one matched pair was frozen. `QZ0_A` fixed passed at +14.272 m; only then was
`QZ1_A` active authorized. Active also passed at +13.185 m. Both were valid and safe, and the only
behavioral manifest difference was the frozen maneuver-domain switch.

Private trace showed L0 but not L1. Active evaluated 1,532 expanded STRAIGHT candidates; 43
overlapped the ADC trajectory and ten were inside 9.455–9.969 m. Every one of those ten had
`polygon_in_own_lane=0`, stayed enabled, and therefore produced zero erroneous candidate disables.
The target reached the nearby-distance condition only after leaving its own lane, so Apollo 10's
modern polygon guard compensated the PR826-family domain expansion.

The generic detector also observed 38 active versus 36 fixed lateral-signature frames and 35
Planning consumptions with nine response deltas. Because L1 never occurred, those differences are
not causally attributed to the port. Outcome: `CANDIDATE_SEMANTIC_DELTA_ABSENT`; the pair is closed
without fault or oracle changes. The next normal-only hypothesis may delay physical merge onset so
the unchanged distance and own-lane guards overlap, but it must independently pass fixed screening
and fixed 3/3 before any active run.

## Cleanup record

The cleanup removed obsolete P1/P2 candidate runs, closed P4B/v3 runs, duplicate state/report
copies, intermediate contracts/audits/ledgers, one-off scripts, caches and temporary logs. Pair A/B
large timelines/telemetry were removed only after compact common audits and normalized manifest
hashes were validated. Pair C raw output was retained through its common audit and aggregate, then
became eligible for the same compact retention policy. Apollo/CARLA/map/build assets remain for the
native mechanism screen.

The rejected `RN_V150_S1` raw directory (about 27 MB) was removed after its frozen hashes, gate
result and minimum machine metrics were preserved in
`reports/P4B_SPEED150_NORMAL_SCREEN_AUDIT.json`.

The speed-1.30 screening and three fixed-repeat raw directories were removed after the compact
screen/repeat audits and the clearance metrics above were preserved. The canonical manifest and
frozen contracts remain because the next matched native screen consumes them.

The `QZ0_A/QZ1_A` raw pair and private audit views were removed after the L0/L1 guard evidence,
matched outcomes and compact machine audit were preserved in the speed-1.30 native report.
