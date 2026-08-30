# Cleanup plan

This plan was frozen before deleting project or runtime artifacts. No Apollo/CARLA run is allowed
during cleanup.

## KEEP

- Human entry points: `README.md`, `CURRENT_STATUS.md`, concise `RESEARCH_LOG.md`, and
  `REPRODUCTION_BEST_PRACTICES.md`.
- One machine state: `run_state.yaml`.
- Current configured-reference contract/report/audit.
- P3 semantic mapping and fixture report plus the source/fixture/build tools required for the later
  natural PR826 mechanism screen.
- Current v5 contract, common audit core/CLI/aggregate, tests, interposer, preparer, runner,
  renderer, runtime collector, and contract-referenced tools needed until v5 closes.
- Compact Pair A/B common-audit JSON. These contain all final metrics, validity layers, artifact
  hashes, allowed pair-delta results, and normalized repeat-manifest hashes needed by aggregation.
- `PZ0_C` raw directory temporarily, until its S0 arm is audited after cleanup; `PZ1_C/manifest.json`
  until the authorized S1 execution.
- One compact source-scene manifest copied from `SN_N01_A/manifest.json` for later mechanism work.
- Minimal ledgers: fix/tooling, P4 sensitivity, and fault experiment.
- Installed Apollo/CARLA/map/Control assets required to execute the current case.

## TEXT_ONLY_THEN_DELETE

- P2 exploratory candidate contracts, audits and per-candidate ledgers after their accepted/rejected
  rationale is summarized in `RESEARCH_LOG.md`.
- P4-SENS v1/v2/v3 contracts/audits and v3 raw runs after the temporary-window result and design
  limitation are summarized.
- Legacy P4 pair auditors and outputs after common-core regression is recorded. Contract-referenced
  script snapshots remain only until v5 closes if deleting them would break current checks.
- Old checkpoints, debug reports, duplicate state copies, duplicate report copies, historical TODOs
  and plans.
- Stable-reference raw formal runs after final report/audit/config are copied to canonical project
  files.
- Pair A/B raw run payloads after common audits are validated: Planning timelines, telemetry,
  native logs, generated configs and runtime dumps. Their compact common audits remain.
- All closed P1/P2/P4B/P2M–P2O and v3 run directories once their conclusions are in the research
  log.

## DELETE

- `__pycache__`, compiled Python cache, temporary render output, abandoned zero-byte output, and
  unreferenced temporary logs.
- Runtime-state mirror `runtime_state/pr826_greybox_demo_v1/RUN_STATE.yaml`; no current project code
  reads it. `run_state.yaml` is the only source after cleanup.
- Duplicate benchmark/runtime copies after the canonical copy is validated.

## Runtime run-directory whitelist during cleanup

Only these current dependencies survive the first runtime cleanup:

- `PZ0_C/` — full, pending post-cleanup S0 arm audit.
- `PZ1_C/manifest.json` — prepared prospective S1 arm, not executed.
- `SN_N01_A/manifest.json` — copied into canonical config, then the run directory may be removed.

Pair A/B raw directories (`PY0_A`, `PY1_A`, `PZ0_B`, `PZ1_B`) are deletable only after both common
audits parse, regression passes, and normalized repeat-manifest hashes match across A/B.

No file is deleted merely to make a result look cleaner. Deletion changes storage only, never the
frozen v5 contract, run data interpretation, or gate.
