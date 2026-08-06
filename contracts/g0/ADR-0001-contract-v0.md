# ADR-0001: Freeze CAGE-AD G0 contract v0

- Status: Accepted for the Autoware G0 port
- Date: 2026-08-06
- Evidence: `runtime_state/evidence/a2/checkpoint.yaml`

## Context

Apollo G0 must hand off platform-neutral observation and action semantics without turning Apollo topic or module names into diagnosis labels. A2 also requires one L1 query, one non-GT semantic intervention, explicit cost/provenance, and physical oracle isolation.

## Decision

Freeze seven functional responsibility domains in `responsibility_contract_v0.yaml`. The exercised A2 slot is `tracking_execution`, composed of `control_target` and `vehicle_response`. O1 queries one bounded slot window. I2 replaces one contract output with a declared fixed probe and must disclose duration, side effects, and whether ground truth was used.

Freeze JSON Schema Draft 2020-12 documents for semantic windows, diagnostic actions, and run manifests. Apollo native names live only in `apollo_native_mapping.yaml`; an Autoware adapter must implement the same functional fields and units without copying those names.

Fault labels, oracle records, injector configuration/state, source code, and undeclared simulator truth are forbidden at the diagnosis entry. The evaluator remains a distinct root-only path.

## Consequences

- Autoware may change only its native mapping, not responsibility IDs, slot meanings, units, action classes, or no-leakage rules.
- Any contract change requires a new schema version, an ADR, updated golden artifacts, and renewed Apollo conformance.
- I2 is a privileged R2 action, not an L1 observation and not a low-cost perfect-state replacement.
- This freeze proves Apollo conformance only; cross-stack transfer remains untested.

## Verification

`scripts/validate_contracts.py` validates all three schemas, four real Apollo A2 runs, and one platform-neutral golden input/output pair. Guardian tests independently validate the same artifacts.
