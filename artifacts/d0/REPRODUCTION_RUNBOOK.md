# D0 终态复现手册

本文用于复现 `d0_a0_repaired_v3` 的执行和最终评估。它直接使用已经通过 G0 的持久盘环境，不重新安装 Apollo 或 CARLA。

## 1. 固定路径和版本

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

现有 batch 是用 `CAGE_EXECUTION_COMMIT` 生成和执行的。后续 commit 只增加数据集文档、结果导出和终态 provenance。不要用另一个 commit 或配置重新生成并覆盖现有 batch。

## 2. 检查源码和冻结配置身份

```bash
cd "$CAGE_REPO"
git rev-parse "$CAGE_EXECUTION_COMMIT"
sha256sum \
  "$CAGE_STATE_ROOT/${CAGE_BATCH}_plan.json" \
  "$CAGE_STATE_ROOT/${CAGE_BATCH}_execution.json" \
  "$CAGE_STATE_ROOT/evidence/${CAGE_BATCH}_evaluation.json"
```

预期 SHA-256 依次为：

```text
b496234a10871cf7d26dc52219bac8164a25a5e905308d1c7540b942c08a2112
1aa5de1cae27da1b60999c0b59479d6a2ddbb2b794735a032c3505a303b7cc5c
956b3f65833aced0104734d3011c1d5ad53e3d53fc4883db6034f396f002055a
```

## 3. 运行 CPU 测试和源码审计

```bash
cd "$CAGE_REPO"
"$CAGE_RUNTIME_ROOT/envs/cage-ad-py310/bin/python" -m pytest -q
"$CAGE_RUNTIME_ROOT/envs/cage-ad-py310/bin/python" tools/source_audit.py
```

## 4. 崩溃恢复规则

下面的命令只有在某个 run 同时具有 PASS status、private metrics、scenario stats、interposer stats 和 retained semantic capture 时才跳过它。它可用于真正的中断恢复，但不能为了制造新结果而重复运行。当前 batch 会跳过全部 84 个已 PASS run。

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

## 5. 不重跑仿真，直接复现评估

```bash
cd "$CAGE_REPO"
"$CAGE_RUNTIME_ROOT/envs/cage-ad-py310/bin/python" scripts/d0/evaluate_smoke.py \
  --state-root "$CAGE_STATE_ROOT" \
  --data-root "$CAGE_DATA_ROOT" \
  --private-oracle-root "$CAGE_PRIVATE_ORACLE_ROOT" \
  --batch-id "$CAGE_BATCH"
```

预期输出为：

```text
d0_a0_evaluation=FAIL pass=2/12
```

预期退出码是 1。这里的 1 是预注册科学结果“没有通过”，不是程序运行故障。

## 6. 重建公开 manifest 和结果文件

Parquet 导出需要隔离评估环境中的固定版本：

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

文档翻译会改变 public manifest 中的数据集卡 SHA，因此最终文件校验值统一以 `runtime_state/d0/FINAL_ARTIFACT_CHECKSUMS.sha256` 为准。

## 7. 隔离要求

诊断进程只能读取每个 episode 的 `visible/` 子目录。绝不能向诊断进程开放 `CAGE_PRIVATE_ORACLE_ROOT`、evaluation JSON、语义标签或 run linkage。CPU 测试和离线评估期间应确认 Apollo/CARLA 已停止，private oracle 权限应保持 `0700`。
