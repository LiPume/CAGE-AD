# Apollo G0 handoff status

Status: `APOLLO_GO` as of 2026-08-06T03:27:41Z.

## Frozen inputs for the Autoware port

- Responsibility and semantic contract: `coordination/contracts/responsibility_contract_v0.yaml`
- Semantic-window schema: `coordination/contracts/semantic_slots.schema.json`
- Action schema: `coordination/contracts/actions.schema.json`
- Run-manifest schema: `coordination/contracts/run_manifest.schema.json`
- Golden conformance fixtures: `coordination/conformance/`
- Apollo provenance mapping: `coordination/handoffs/apollo_native_mapping.yaml`
- Contract decision: `coordination/decisions/ADR-0001-contract-v0.md`

## Apollo evidence available

- A0: rendered synchronous CARLA 0.9.15 RGB/LiDAR stability for 1,800 seconds.
- A1: three clean-start Apollo 10 PnC–CARLA closed-loop runs on Town01.
- A2: three formal repeats plus one `env -i` replay of a 2-second control-delay fault, O1 `tracking_execution` query, and non-GT I2 control-target probe.
- Oracle isolation: diagnosis UID 1001 cannot read evaluator labels, injector configuration, or injector environment.

## Port requirements

1. Preserve contract IDs, units, regimes, action classes, negative permissions, and schema versions.
2. Implement an Autoware native-to-semantic mapping separately; native component names are provenance only.
3. Recreate the golden delayed-response result before running a simulator episode.
4. Record adapter LOC/manual mappings, native private fields, action side effects, and measured cost.
5. If the contract cannot represent a required Autoware semantic, write a new ADR and rerun Apollo conformance before changing it.

## Claim boundary

Apollo-only success does not prove Apollo-to-Autoware transfer, action equivalence across stacks, or the paper's final comparative hypothesis. No Autoware installation or D0 work was started here.
