# D0-A0 Apollo smoke runbook

This runbook uses the existing G0-approved Apollo 10 host-mode and CARLA 0.9.15 runtime. It does not install, move, or replace that runtime.

## Roots

```bash
export CAGE_BUNDLE_ROOT=/root/autodl_apollo10_g0_bundle
export CAGE_RUNTIME_ROOT=${CAGE_BUNDLE_ROOT}/runtime
export CAGE_STATE_ROOT=${CAGE_BUNDLE_ROOT}/runtime_state/d0
export CAGE_DATA_ROOT=/root/cage_ad_data
export CAGE_PRIVATE_ORACLE_ROOT=/root/cage_ad_private_oracle
export CAGE_D0_BATCH_ID=d0_a0_formal_v1
```

The diagnosis process may read only each episode's `visible/` subtree. Root-only injector configuration, run linkage, labels, and evaluation remain under `CAGE_PRIVATE_ORACLE_ROOT`.

## Prepare and execute

Run preparation only after committing the D0-2 implementation, and pass that exact commit as `--source-commit`.

```bash
python scripts/d0/prepare_smoke.py \
  --repo-root . \
  --state-root "${CAGE_STATE_ROOT}" \
  --data-root "${CAGE_DATA_ROOT}" \
  --private-oracle-root "${CAGE_PRIVATE_ORACLE_ROOT}" \
  --source-commit "$(git rev-parse HEAD)" \
  --batch-id "${CAGE_D0_BATCH_ID}"

python scripts/d0/run_smoke_batch.py \
  --repo-root "$PWD" \
  --bundle-root "${CAGE_BUNDLE_ROOT}" \
  --runtime-root "${CAGE_RUNTIME_ROOT}" \
  --state-root "${CAGE_STATE_ROOT}" \
  --data-root "${CAGE_DATA_ROOT}" \
  --private-oracle-root "${CAGE_PRIVATE_ORACLE_ROOT}" \
  --batch-id "${CAGE_D0_BATCH_ID}"

python scripts/d0/evaluate_smoke.py \
  --state-root "${CAGE_STATE_ROOT}" \
  --data-root "${CAGE_DATA_ROOT}" \
  --private-oracle-root "${CAGE_PRIVATE_ORACLE_ROOT}" \
  --batch-id "${CAGE_D0_BATCH_ID}"
```

There are 12 diagnosis episodes. The 84 runtime invocations are companion evidence: one nominal, three repeated fault confirmations, and one probe in each of the three responsibility domains per episode. They must not be counted as 84 independent diagnosis samples.

The batch runner checkpoints after every invocation and skips only a run whose status and private metrics both show completion. It stops Apollo/CARLA at batch completion. Failed runs and engineering attempts are retained; they are never silently removed.
