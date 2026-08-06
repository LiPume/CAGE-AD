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

The engineering-pilot dataset semantics, including the meaning of every current
scene, fault mechanism, companion run, and public/private field boundary, are
documented in [`docs/dataset/CAGE_AD_D0_DATASET_CARD.md`](docs/dataset/CAGE_AD_D0_DATASET_CARD.md).
The card is deliberately marked non-release-ready until the preregistered smoke,
leakage, reproducibility, checksum, and licensing gates pass.
