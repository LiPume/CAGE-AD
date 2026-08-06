# CAGE-AD

Cost-aware, contract-grounded active diagnosis for modular autonomous-driving systems.

This repository is the source-only control plane. Apollo, CARLA, maps, generated episodes, and evaluator-private oracle records remain outside Git. Runtime entry points resolve these locations from `CAGE_RUNTIME_ROOT`, `CAGE_STATE_ROOT`, `CAGE_DATA_ROOT`, and `CAGE_PRIVATE_ORACLE_ROOT`.

The initial checkpoint records the verified Apollo 10 + CARLA 0.9.15 G0 sources and textual third-party patches. It is not a binary environment snapshot and does not depend on the historical Zhijia-Guardian project.

Run CPU-only checks with:

```bash
python -m pip install -e '.[dev]'
pytest -q
python tools/source_audit.py
```

工程 pilot 的中文数据集说明书位于
[`docs/dataset/CAGE_AD_D0_DATASET_CARD.md`](docs/dataset/CAGE_AD_D0_DATASET_CARD.md)，
其中逐项解释了每个场景、故障机制、配套运行以及公开/私有字段边界。当前数据只通过
2/12 个完整科学 gate，因此文档明确标记为尚不可正式发布。
