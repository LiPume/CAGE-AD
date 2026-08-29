# Apollo 10 + CARLA failed-overtake reference — final report

## Final decision

**STABLE_REFERENCE_ADMITTED**

The configured Apollo 10 + CARLA 0.9.15 normal reference passed all frozen gates in three
consecutive formal repetitions. No fault injection, PR826 semantic port, diagnosis Agent, or
animation was created in this phase.

This is accurately labeled **Apollo 10 configured reference**, not unmodified stock Apollo 10.
Stock Prediction and Planning execute normally; the reference uses a metadata-corrected Apollo
map, a checksum-locked CARLA-Lincoln Control calibration, and a deterministic scripted NPC policy.

## Frozen scene and runtime

| Item | Frozen value |
|---|---|
| CARLA map | Town04 |
| Road/lane sequence | road 46 lane -2 → road 1072 lane -2; ego route ends on road 47 lane -1 |
| Ego spawn (CARLA) | `(9.356113, 186.451248, 0.281942)`, yaw `-90.289116°` |
| NPC spawn (CARLA) | `(9.229000, 161.274002, 0.281942)`, yaw `-90.289116°` |
| Initial nominal gap | 25.0 m |
| Apollo route | `(9.356113, -186.451248)` → `(5.199275, -56.292660)` |
| Route intent | lane `-2` → lane `-1`; approximately 130.18 m |
| Success region | road 47, lane -1, center `(5.199275, 56.292660)`, radius 15 m |
| NPC nominal speed | 1.10 m/s |
| Ego target speed | No external target is imposed; Apollo Planning/Control is sole ego controller. During passing, Control debug shows a roughly 2.08 m/s reference/actual speed. |
| Observation window | 80.0 s |
| Weather | ClearNoon |
| Camera/sensors | No camera; bridge sensor list is empty and frozen |
| Seed | 82601 |
| World timing | synchronous, fixed delta 0.05 s, substepping on, max substep 0.01 s × 10 |
| Reload | deterministic world reload before every run, settings verified after reload |
| Traffic Manager | not used in admitted candidate |
| Background actors | zero vehicles, zero pedestrians |

The NPC uses CARLA's local constant-velocity primitive for longitudinal motion. Once per observed
frame, one batched no-tick command aligns only its yaw to the **current** nearest driving-lane
tangent. Current position is preserved; it is not projected or advanced from future waypoints.
This policy reads no future ground truth and no Apollo output. It exists because raw constant
velocity drifted off the mildly curved lane, while CARLA TM and BasicAgent low-speed controllers
failed the pre-frozen Prediction trajectory gate.

## Apollo and bridge configuration

- Prediction: installed Apollo 10 stock Prediction pipeline. The target appears as obstacle 1001
  and receives real predicted trajectories.
- Planning: installed Apollo 10 Planning behavior. No PR826 or Prediction patch exists.
- Apollo map: `carla_town04_road_width_v1`. It adds only missing Apollo road-width samples on the
  three target lane segments; the map audit preserves all other geometry/routing semantics.
- Control: V17 low-speed CARLA-Lincoln calibration, SHA-256
  `2693818651d7799eac5f206b88af0c0fb86f38b34443c1b14b4ccd45ffe482aa`.
  It changes nonnegative low-speed table entries at speeds <=2.0 m/s and remains identical in all
  formal runs. Native Control logs in all 3 runs name the absolute generated table path.
- Bridge conversion: throttle gain 1.5, brake gain 1.0, steering gain 0.419643, localization
  acceleration alpha 0.15. These values are frozen across all repeats.
- Startup order: CARLA server → RPC readiness → deterministic bridge reload/ego spawn → Apollo
  Routing/Prediction/Planning/Control → 45 s Prediction model initialization → route/NPC runner.

The map and Control changes are compatibility configuration, not a hidden Prediction fix. A future
matched faulty arm must use exactly the same map, Control table, bridge, route, target policy and
oracle; only the Prediction fault may differ.

## Formal 3/3 results

| Metric | Repeat 1 | Repeat 2 | Repeat 3 | Frozen gate |
|---|---:|---:|---:|---:|
| Result | PASS | PASS | PASS | 3/3 PASS |
| Prediction trajectory coverage | 0.9839 | 0.9870 | 0.9870 | >=0.90 |
| Planning channel coverage | 0.9926 | 0.9913 | 0.9938 | >=0.95 |
| Planning valid ratio | 0.9477 | 0.9551 | 0.9415 | >=0.90 |
| Control channel coverage | 0.9984 | 0.9998 | 1.0011 | >=0.95 |
| Max pass margin | 25.507 m | 26.457 m | 23.625 m | >=6.0 m |
| Max lateral excursion | 3.953 m | 3.731 m | 3.471 m | >=2.0 m |
| Minimum 2-D body clearance | 0.757 m | 0.727 m | 0.820 m | report-only; collision gate=0 |
| Overtake latency | 39.00 s | 38.75 s | 44.45 s | report-only |
| Success-region latency | 70.55 s | 67.30 s | 68.70 s | must be reached |
| Collision count | 0 | 0 | 0 | 0 |
| Illegal lane invasion | 0 | 0 | 0 | 0 |
| Target heading command errors | 0 | 0 | 0 | 0 |
| Target lane IDs | `[-2]` | `[-2]` | `[-2]` | exactly `[-2]` |

All lane-invasion events were `Broken|White|Both`, the only pre-frozen legal crossing signature.
Prediction mechanism counts were 1591/1617, 1595/1616, and 1596/1617.

## Repeat variance and timing

Across the three runs:

- Prediction coverage: mean 0.98598, population SD 0.00146.
- Planning valid ratio: mean 0.94808, SD 0.00555.
- Max pass margin: mean 25.196 m, SD 1.177 m; minimum 23.625 m remains far above the 6 m gate.
- Max lateral excursion: mean 3.719 m, SD 0.197 m.
- Minimum body clearance: mean 0.768 m, SD 0.039 m.
- Overtake latency: mean 40.73 s, SD 2.63 s.
- Success latency: mean 68.85 s, SD 1.33 s.
- NPC run-mean speed: 1.09920 m/s with between-run SD 0.000042 m/s.

Planning latency mean/p95/max was respectively 35.53/44.47/313.67 ms,
35.38/45.04/311.72 ms, and 35.60/44.87/295.40 ms. Prediction input-age means were
37.17, 37.36, and 37.51 ms; p95 remained below 50 ms in every run.

## Optimizer and fallback audit

| Native log count | Repeat 1 | Repeat 2 | Repeat 3 |
|---|---:|---:|---:|
| PiecewiseJerk speed optimizer failures | 144 | 126 | 124 |
| Fallback path optimizer failures | 0 | 0 | 22 |
| Speed fallback events | 133 | 125 | 165 |
| Reference-line creation failures | 0 | 0 | 0 |

These events are not hidden. They occur in recoverable clusters, and all runs still exceed the
frozen Planning-valid gate, maintain safe/valid trajectories, complete the pass, and reach the
route region. Their variability is a known limitation for future diagnosis experiments and should
remain visible as incidental/recovered anomalies rather than being mislabeled as the source fault.

## Integrity and hashes

- Formal contract:
  `reference_repeat_contract_v2.yaml`, SHA-256
  `163f523d2d552cc5627efcce67df01d074db7ea6d52d28c6ea99831f1946dfe2`.
- Candidate canonical SHA-256:
  `756aa657d74638b40c23036affb7db616064e756a63f0ed4dab50609b578a4a4`.
- Ordered three-manifest set SHA-256:
  `c7c7d8dd90861e994dd5565007b8433a45670f09b1129da5ad6f6a041af3c8de`.
- Repeat manifest SHA-256 values:
  `2f9cb9f6c63a9a40d82d998d49fc5380110b35909b9f811ea2395cb410c558fc`,
  `1368d1d82fbe2f114f90f499f5ca626c908f253be18504585a64cd6fb833c49d`,
  `ef29a44b484882ff79266ff870ef2bbc7db7971649cdb0e1cdfb1327ffda0b61`.
- Derived `base_map.bin` SHA-256:
  `fac6d39f94c82796fe71c86269c74d663d9ca6bf89dbef85523b338258ab5372`.
- Formal preparation verifies all 11 frozen artifact hashes before starting a run.
- Machine-readable result: `FORMAL_REPEAT_V2_AUDIT.json`.

There is no fault patch, future faulty result, external ego controller, ego teleportation, or
future-GT feed into Planning. The existing identity relay copies Planning protobuf bytes unchanged;
all formal runs report `planning_raw == planning_relayed` and zero identity mismatches. Perfect
perception publishes only the target's current CARLA pose/velocity, intentionally removing the
Perception module from this Prediction-focused reference. The credential-pattern scan found zero
workspace hits, and cleanup left no CARLA/Apollo/reference-runner process.

## Rejected candidates retained in the ledger

1. Town01 RF01 static case: one provisional pass did not repeat; first formal repeat stayed behind,
   and both runs had zero target predicted trajectories. Rejected as nonrepeatable/static-Planning.
2. Town04 1.10 m/s raw target: Prediction coverage passed (~0.93), but stock lane-borrow did not
   engage for a moving obstacle. Raising a Planning static threshold did not change the relevant
   Prediction-provided classification.
3. Route-driven lane change on the original bridge map: missing Apollo road-width metadata caused
   infeasible LaneChangePath bounds. The metadata-only derived map removed this failure.
4. Early intermediate lane-change waypoint: the current-lane route passage expired before physical
   lane entry, producing prolonged reference-line failure. Rejected; long two-waypoint route used.
5. Raw constant-local-velocity NPC: longitudinal speed/Prediction coverage passed but spawn-tangent
   motion drifted off the curved road. Rejected.
6. CARLA ConstantVelocityAgent: its hazard logic made NPC speed ego-dependent; coverage alternated
   around 0.50. RPC reordering occasionally raised aggregate coverage but did not remove the
   semantic dependence, so the policy was rejected.
7. Synchronous Traffic Manager: integrated target stayed at 0 m/s; a same-client probe moved but
   low-speed bang-bang control placed only 35.3% of steady frames above the 0.99 m/s Prediction
   threshold. Rejected.
8. BasicAgent PID sweep: stable settings undershot the Prediction threshold; higher gains oscillated
   and could not reach the 0.90 gate. Rejected.
9. Stock Control with the final target policy: Prediction mechanism repeated at ~0.972, but ego
   remained too slow to pass. This localized the compatibility issue to Control/CARLA calibration.
10. First V17 screen: the table was rendered but the installed relative Control DAG shadowed it;
    native logs proved V17 was not loaded. The run is permanently rejected and not used as V17
    evidence.
11. Corrected 45 s V17 screen: legally passed by 6.721 m but had not reached the unchanged route
    region. It motivated only a pre-frozen duration extension, not an oracle change.

Every planned/result event remains append-only in `reference_screening_ledger.jsonl`; every change
and failed attempt remains in `FIX_LEDGER.jsonl` and `RESEARCH_LOG.md`.

## Suitability for later Prediction → Planning work

The target is present in stock Apollo Prediction with valid trajectories in at least 98.39% of
formal frames, and Planning consumes that channel while controlling the ego through an actual legal
lane change and pass. The fixed/current mechanism is therefore suitable as a normal arm for a later
matched Prediction fault experiment: an intervention can change Prediction semantics while holding
the world, actor policy, route, map, Planning, Control, bridge and oracle constant.

This report does **not** claim that a future PR826 semantic fault will necessarily suppress this
route-driven overtake; that remains a separate fault-admission experiment explicitly outside the
current authorized scope.
