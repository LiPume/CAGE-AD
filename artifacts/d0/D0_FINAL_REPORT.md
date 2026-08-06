# Apollo 10 D0 final report

Final status: **D0_MODIFY_INFRA**  
Terminal gate: D0-2 benchmark smoke  
Finalized: 2026-08-06  
Formal repaired batch: `d0_a0_repaired_v3`

## Outcome

The experiment did not proceed to D0-A1 or policy comparisons. The repaired
D0-A0 generator completed all 84 required companion simulations, but only 2 of
12 diagnosis episodes passed the preregistered combined scientific gate. The
single allowed mechanism-level repair had already been used after the preserved
0/12 v2 result. Changing the labels, split, budget, failure thresholds, probe
criterion, or injection strength again would invalidate the registered test.

The honest terminal outcome is therefore `D0_MODIFY_INFRA`: the Apollo/CARLA
execution infrastructure is reproducible enough to run and isolate the study,
but the present semantic-boundary faults and counterfactual probes do not create
a stable, domain-identifiable active-diagnosis benchmark.

## Gate disposition

| Gate | Result | Evidence |
|---|---|---|
| Source-only G0 checkpoint | PASS | `1fa6fb1`; remote source branch pushed |
| D0-1 contracts/state/verifier | PASS | `51f7ba0`; typed gate, ledgers, resume, isolation tests |
| D0-2 benchmark implementation | PASS | `9ae1bfa`; two scenes, six faults, O0-O3 and I2-F/P/C |
| D0-2 runtime lifecycle repair | PASS | `a08859d`; fresh server/run and resumable 84-run batch |
| D0-2 formal v2 science | FAIL | 84/84 runtime-valid; 0/12 combined gate; preserved |
| D0-2 one allowed mechanism repair | EXECUTED | `edf09c6`; labels/split/budget/thresholds unchanged |
| D0-2 repaired v3 runtime | PASS | 84/84 current runs valid after one archived transient-invalid retry |
| D0-2 repaired v3 science | FAIL | 2/12 combined gate; zero visible leakage token hits |
| D0-3 through D0-6 | NOT RUN | Invalid main benchmark; downstream comparisons would be meaningless |

## Repaired v3 protocol identity

- execution source: `edf09c6af0a1de2e6d68c35ce0abbebc0f2a9df8`;
- documentation/export checkpoint: `fc0b09a579fe08677b7bf35d4e24bcb49f24c7b1`;
- configuration SHA-256:
  `6bfe98a2611b44cfc8d8a4504a44397853ec97f09ba36d30884e1d08eb6e526a`;
- plan SHA-256:
  `b496234a10871cf7d26dc52219bac8164a25a5e905308d1c7540b942c08a2112`;
- execution SHA-256:
  `1aa5de1cae27da1b60999c0b59479d6a2ddbb2b794735a032c3505a303b7cc5c`;
- evaluation SHA-256:
  `956b3f65833aced0104734d3011c1d5ad53e3d53fc4883db6034f396f002055a`;
- public manifest file SHA-256:
  `42a22209f7f5b2f132be3c4c15fd510643008f2c92ba9a24e1c34f611c7d52c0`.

## Quantitative result

| Check | Result |
|---|---:|
| Diagnosis episodes | 12 |
| Current companion runs valid | 84/84 |
| Nominal episodes valid | 12/12 |
| Fault repeats runtime-valid | 36/36 |
| Fault repeats with confirmed mechanism signal | 33/36 |
| Fault repeats satisfying mechanism + task-failure vote | 16/36 |
| Episodes with at least 2/3 combined repeat votes | 5/12 |
| Correct-domain probe repairs | 2/12 |
| Wrong-domain false repairs | 1 |
| Visible oracle token hits | 0 |
| Episodes passing the complete gate | 2/12 |

The two passing episodes were the cut-in scene with
`planning_unsafe_cost_or_speed_bias` and the cut-in scene with
`control_gain_saturation_tracking_bias`. The planning episode also had one
wrong-domain false repair, which further limits causal specificity even though
the implemented combined evaluator did not make that a hard-fail condition.

Forecast heading bias showed the registered mechanism delta in 6/6 repeats but
produced zero task failures. Stateful forecast delay produced the mechanism
delta in only 3/6 repeats and zero task failures. Control transport delay showed
the mechanism delta in 6/6 repeats and zero task failures. Both
`planning_constraint_omitted` episodes produced 3/3 combined repeat votes, but
neither correct planning probe removed the failure. Lead-scene control gain
bias also produced 3/3 votes without a correct-probe repair.

## Runtime invalid/retry accounting

One v3 forecasting-probe attempt completed a 32.05-second CARLA window but
Apollo never initialized route/planning (`route.count=0`, zero progress). It is
recorded as `D0-2-RUNTIME-007`, not as a scientific negative. Before an exact
retry, its status, execution checkpoint, private metrics, scenario/interposer
stats, and semantic capture were checksum-archived under `invalid_attempts/`.
The retry used the same run ID, source, and config and passed. No completed PASS
intervention was re-executed.

## Resource use

- powered-on estimate at termination: 7.28 h of the 30 h cap;
- incremental filesystem use: 19,024,654,336 bytes (17.72 GiB) of the 100 GiB cap;
- Apollo, CARLA, bridge, and batch processes stopped at termination;
- evaluator-private batch root remained mode `0700`.

## Why downstream gates were stopped

D0-3 requires freezing and expanding a scientifically valid smoke generator.
Here, most injected mechanism signals either did not cause the registered task
failure or were not reversed by their correct-domain counterfactual. Generating
36 episodes would replicate an invalid identification problem. Running fixed,
greedy, Single-Agent, or Multi-Agent policies on it could reward artifacts and
would not test the registered hypothesis. This is a scientific dependency
stop, not a missing credential, provider, or budget authorization.

## Required scope of a future modification

Any future attempt must be a newly registered infrastructure version, not an
in-place continuation of v3. It should redesign the causal scene/fault/probe
envelopes so that domain-local interventions have stable, selective effects;
freeze new criteria before formal results; and retain v2/v3 as failed pilots.
It must not relabel these episodes or reinterpret their frozen outcomes.
