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
- Persistent privileged S1 (about 12–75 s) passed Pair A and Pair B:

  | Pair | S0 | S1 | Common-core audit |
  |---|---|---|---|
  | A | overtake, max margin +24.783 m | no overtake, -11.236 m | PASS |
  | B | overtake, max margin +23.267 m | no overtake, -6.253 m | PASS |

  All four arms are runtime-valid, transport-valid, and semantic-valid under the frozen gates.
  They are explicitly not admission evidence.

## Not established

- Persistent sensitivity is not yet confirmed 3/3; Pair C is incomplete.
- No evidence yet shows that the frozen PR826 semantic port naturally emits the persistent S1
  phenotype in this scene.
- No PR826 L0→L4 causal chain or golden case is admitted.
- No diagnosis Agent, probability claim, repair, or animation is in scope yet.

## Current gate

`CLEANUP_COMPLETE_AWAITING_PAIR_C_CONFIRMATION`

The v5 contract is frozen and must not change. Pair B passed the version-independent common audit.
`PZ0_C` finished immediately before the cleanup instruction arrived; it is retained but not yet
counted. `PZ1_C` has only a prepared manifest and has not run.

## Only next action

After user confirmation of the simplified repository, use the common audit core to check `PZ0_C`
against the frozen S0 arm gate. Only if it passes may `PZ1_C` run. After a 3/3 aggregate, stop
sensitivity tuning and proceed to the separate natural PR826 L0→L4 mechanism screen.

## Active contract and canonical reports

- Active contract: `P4_SENS_V5_CONFIRMATION_CONTRACT.yaml`
- Canonical configured-reference report: `reports/FINAL_REFERENCE_REPORT.md`
- Canonical Pair A/B metrics: `reports/P4_SENS_PAIR_A.json` and
  `reports/P4_SENS_PAIR_B.json`
- Canonical machine state: `run_state.yaml`

## Explicit non-claim

Persistent Prediction semantic occupancy has shown a repeatable failure-amplification signal in
two pairs, but the final claim is withheld until Pair C. Even a 3/3 result will mean only:

> Persistent Prediction semantic occupancy is a reproducible system-level failure amplifier in
> this configured scenario.

It will **not** establish that PR826 naturally produces the same phenotype.
