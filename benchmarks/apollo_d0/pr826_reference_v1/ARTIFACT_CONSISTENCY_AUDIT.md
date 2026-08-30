# Artifact consistency audit

This is a cleanup-oriented audit, not a permanent forensic index.

## Real contradictions found

| Conflict | Resolution |
|---|---|
| `P2_REFERENCE_CHECKPOINT.md` says `CASE_NOT_ADMITTED`, while the later final report says `STABLE_REFERENCE_ADMITTED`. | The checkpoint applies only to rejected RF01 and is obsolete as project state. Its rationale moves to `RESEARCH_LOG.md`; the file is deleted. |
| Some historical text shortened the reference to “stock Apollo”. | Canonical wording is **Apollo 10 configured reference**: stock Prediction/Planning behavior plus frozen map, Control, bridge and deterministic-NPC compatibility configuration. |
| Legacy `summary.metrics.infrastructure_valid=false` occurred in runs with accepted route, healthy channels and no runtime exception. | New audits preserve the legacy field only as telemetry and decide `runtime_valid`, `transport_valid`, `semantic_valid`, `behavior_valid`, and `admission_valid` separately. |
| v4 and v5 wrapper auditors encoded exact contract versions and duplicated gates. | Replaced for current interpretation by `p4_sensitivity_audit_core.py` plus a schema adapter and a version-independent writer. Frozen runs/contracts are unchanged. |
| Two independently editable state files existed. | `run_state.yaml` becomes the sole machine state; the runtime mirror is deleted. |

## Apparent contradictions that are not contradictions

| Observation | Explanation |
|---|---|
| v3 S1 overtook 3/3, while v4 A and v5 B S1 did not. | v3 altered output only through about 40 s and was closed as temporary sensitivity evidence. Persistent v4/v5 renews the same semantic through about 75 s. They are different preregistered temporal interventions, not reinterpretations of one result. |
| v4/v5 S1 creates failed overtake, while PR826 reproduction is not admitted. | S1 is a privileged interface intervention. Natural PR826 must independently prove L0 activation → L1 candidate delta → L2 native output phenotype → L3 Planning response → L4 vehicle failure. |
| Planning optimizer/fallback events coexist with valid reference and sensitivity runs. | They occur in the configured baseline and are response/incidental metrics unless differential evidence links them to Prediction. They are not automatically source-fault evidence. |

## Current truth after cleanup

- `CURRENT_STATUS.md`: only human-readable current status.
- `run_state.yaml`: only machine-readable current state.
- `reports/FINAL_REFERENCE_REPORT.md`: configured-reference authority.
- `P4_SENS_V5_CONFIRMATION_CONTRACT.yaml`: active frozen sensitivity contract.
- Common-core Pair A/B JSON: only A/B inputs required for later aggregation.
- `RESEARCH_LOG.md`: text history for deleted experiments.

Everything else is either an execution dependency kept temporarily until v5 closes or is removed
after its conclusion is represented in the research log.
