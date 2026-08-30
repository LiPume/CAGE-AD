# P4 persistent Prediction-interface sensitivity report

Status: `STABLE_PERSISTENT_S1_CANCELLATION_3_OF_3`

Date: 2026-08-30 UTC

## Scope and frozen contract

This is a privileged, non-admission causal sensitivity probe under
`P4_SENS_V5_CONFIRMATION_CONTRACT.yaml` (SHA256
`eb7fa709edea9f2e0710dcb9707e9a18eccace85953165e93148c7d622672e61`). It keeps the configured
CARLA/Apollo scene fixed and changes only the target obstacle semantic at the Prediction→Planning
interface.

- S0: byte-exact straight Prediction.
- S1: 3.5 m left-normal smoothstep over relative trajectory time 2–4 s.
- Intervention renewal window: elapsed 12–75 s.
- Observation deadline: 80 s.
- Target obstacle: ID 1001.

This experiment is not a natural PR826 execution and is not golden-case admission evidence.

## Three-pair result

| Pair | S0 result | S0 max margin | S1 result | S1 max margin | First Planning delta |
|---|---:|---:|---:|---:|---:|
| A | overtake | +24.783 m | no overtake | -11.236 m | 12.05 s |
| B | overtake | +23.267 m | no overtake | -6.253 m | 12.10 s |
| C | overtake | +19.104 m | no overtake | -6.859 m | 12.00 s |

S0 max-margin mean was +22.385 m (sample SD 2.940 m). S1 max-margin mean was -8.116 m
(sample SD 2.719 m). All S0 arms reached the success region; all S1 arms remained below the
pre-frozen +6 m pass threshold and did not reach the success region.

Pair C quality metrics were:

| Arm | Planning-valid ratio | Prediction trajectory coverage | Active rows | Active window |
|---|---:|---:|---:|---:|
| S0 | 0.9436 | 0.9496 | 1260 | 12.00–74.95 s |
| S1 | 0.9850 | 0.9496 | 1260 | 12.00–74.95 s |

For every arm, the common audit found:

- runtime valid;
- transport valid, including route and channel coverage;
- semantic valid, including identity/transform, field preservation and persistence;
- behavior valid under the pre-frozen arm-specific gate;
- no collision or illegal lane invasion.

Every pair changed exactly the six allowed manifest fields. The normalized repeat hashes were
identical across all three repetitions:

- S0: `7f6bee3fda0eb7d082630ab3d8e5ce3e4b929a66659bbea80d740565aa8418bf`
- S1: `5ddc327d1b1bed20f8b91a18e76dd96ab221d9e9c4243a86d81d5948f49e6790`

The S1 runner's nonzero exit is expected because the reused normal-reference runtime reports
"did not overtake" as failure. The layered audit, rather than that legacy exit code, verified that
S1 had no runtime or transport failure.

## Supported conclusion

> Persistent Prediction semantic occupancy is a reproducible system-level failure amplifier in
> this configured scenario.

The evidence order is: the interface transform is active and preserved, Planning consumes its
output, a Planning state/horizon delta appears at approximately 12 s, and the S1 arm does not
complete the pass by the frozen deadline while the matched S0 arm does.

## Explicit non-claims

- This does not establish that PR826 naturally produces the same phenotype.
- This is not fixed/faulty golden-case admission.
- It does not identify a source-code root cause or validate a diagnosis Agent.
- It does not justify changing the S1 dose or continuing sensitivity tuning.

## Canonical machine evidence

- `aggregate.json`
- `P4_SENS_PAIR_A.json`
- `P4_SENS_PAIR_B.json`
- `P4_SENS_PAIR_C.json`

Closed raw runs may be removed after these compact records validate. The next experiment must use
the already frozen native PR826-family semantic port and record L0 activation, L1 candidate delta,
L2 native Prediction phenotype, L3 Planning response and L4 vehicle outcome separately.
