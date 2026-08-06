# D0 terminal reproduction runbook

This runbook reproduces the completed `d0_a0_repaired_v3` execution and its
terminal evaluation. It uses the existing G0-approved persistent runtime; it
does not reinstall Apollo or CARLA.

## Fixed roots and revisions

```bash
export CAGE_BUNDLE_ROOT=/root/autodl_apollo10_g0_bundle
export CAGE_RUNTIME_ROOT=${CAGE_BUNDLE_ROOT}/runtime
export CAGE_STATE_ROOT=${CAGE_BUNDLE_ROOT}/runtime_state/d0
export CAGE_DATA_ROOT=/root/cage_ad_data
export CAGE_PRIVATE_ORACLE_ROOT=/root/cage_ad_private_oracle
export CAGE_REPO=${CAGE_BUNDLE_ROOT}/project/CAGE-AD
export CAGE_BATCH=d0_a0_repaired_v3
export CAGE_EXECUTION_COMMIT=edf09c6af0a1de2e6d68c35ce0abbebc0f2a9df8
```

The existing batch was generated and run at `CAGE_EXECUTION_COMMIT`. The later
`fc0b09a` checkpoint adds only dataset documentation and public result indexing.
Do not regenerate the existing batch under a different commit or config.

## Verify the source and frozen identity

```bash
cd "$CAGE_REPO"
git rev-parse "$CAGE_EXECUTION_COMMIT"
sha256sum \
  "$CAGE_STATE_ROOT/${CAGE_BATCH}_plan.json" \
  "$CAGE_STATE_ROOT/${CAGE_BATCH}_execution.json" \
  "$CAGE_STATE_ROOT/evidence/${CAGE_BATCH}_evaluation.json"
```

Expected SHA-256 values are, in order:

```text
b496234a10871cf7d26dc52219bac8164a25a5e905308d1c7540b942c08a2112
1aa5de1cae27da1b60999c0b59479d6a2ddbb2b794735a032c3505a303b7cc5c
956b3f65833aced0104734d3011c1d5ad53e3d53fc4883db6034f396f002055a
```

## CPU and source audits

```bash
cd "$CAGE_REPO"
"$CAGE_RUNTIME_ROOT/envs/cage-ad-py310/bin/python" -m pytest -q
"$CAGE_RUNTIME_ROOT/envs/cage-ad-py310/bin/python" tools/source_audit.py
```

## Resume semantics

The following command skips a run only when its PASS status, private metrics,
scenario stats, interposer stats, and retained semantic capture all exist. It is
safe for crash recovery, but should not be run merely to manufacture a new
outcome. The completed batch currently skips all 84 runs.

```bash
cd "$CAGE_REPO"
"$CAGE_RUNTIME_ROOT/envs/cage-ad-py310/bin/python" scripts/d0/run_smoke_batch.py \
  --repo-root "$CAGE_REPO" \
  --bundle-root "$CAGE_BUNDLE_ROOT" \
  --runtime-root "$CAGE_RUNTIME_ROOT" \
  --state-root "$CAGE_STATE_ROOT" \
  --data-root "$CAGE_DATA_ROOT" \
  --private-oracle-root "$CAGE_PRIVATE_ORACLE_ROOT" \
  --batch-id "$CAGE_BATCH"
```

## Re-evaluate without rerunning simulation

```bash
cd "$CAGE_REPO"
"$CAGE_RUNTIME_ROOT/envs/cage-ad-py310/bin/python" scripts/d0/evaluate_smoke.py \
  --state-root "$CAGE_STATE_ROOT" \
  --data-root "$CAGE_DATA_ROOT" \
  --private-oracle-root "$CAGE_PRIVATE_ORACLE_ROOT" \
  --batch-id "$CAGE_BATCH"
```

Expected output is `d0_a0_evaluation=FAIL pass=2/12` and exit code 1. That exit
code is the registered scientific result, not a command malfunction.

## Rebuild release inventory and result files

Install the optional result writer exactly once in the isolated evaluation env:

```bash
"$CAGE_RUNTIME_ROOT/envs/cage-ad-py310/bin/python" -m pip install \
  --disable-pip-version-check pyarrow==21.0.0
```

```bash
cd "$CAGE_REPO"
"$CAGE_RUNTIME_ROOT/envs/cage-ad-py310/bin/python" scripts/d0/build_public_manifest.py \
  --repo-root "$CAGE_REPO" \
  --state-root "$CAGE_STATE_ROOT" \
  --data-root "$CAGE_DATA_ROOT" \
  --batch-id "$CAGE_BATCH" \
  --output "$CAGE_STATE_ROOT/evidence/${CAGE_BATCH}_public_manifest.json"

"$CAGE_RUNTIME_ROOT/envs/cage-ad-py310/bin/python" scripts/d0/export_smoke_results.py \
  --evaluation "$CAGE_STATE_ROOT/evidence/${CAGE_BATCH}_evaluation.json" \
  --plan "$CAGE_STATE_ROOT/${CAGE_BATCH}_plan.json" \
  --csv "$CAGE_STATE_ROOT/RESULTS.csv" \
  --parquet "$CAGE_STATE_ROOT/RESULTS.parquet" \
  --svg "$CAGE_STATE_ROOT/evidence/${CAGE_BATCH}_summary.svg"
```

Expected result checksums:

```text
RESULTS.csv      0eeb779175eb80057ce3022f55ceccaf3b964578c1badd3e7246ceba2e9a191b
RESULTS.parquet  85f62c29be0809901dc738f9e5ee6b359417beccc185c693963ad564642a023c
summary.svg      5fecf7de07aff6b79c7ba2918474298ff16057191eb2e8ab363a0747303e6842
```

## Isolation checks

The diagnosis path may read only an episode's `visible/` subtree. Never grant it
access to `CAGE_PRIVATE_ORACLE_ROOT`, evaluation JSON, semantic labels, or run
linkage. Confirm the private roots remain mode 0700 and that Apollo/CARLA are
stopped when running CPU tests or evaluation.
