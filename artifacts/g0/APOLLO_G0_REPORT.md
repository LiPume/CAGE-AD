# Apollo 10 G0 report

## Verdict

`APOLLO_GO`

Apollo 10 host mode plus CARLA 0.9.15 passed A0, A1, A2, strict three-repeat verification, physical oracle isolation, clean-shell replay, contract conformance, and final audit. No Docker route, GT replacement, fabricated evidence, or relaxed gate was used.

## Gate results

| Gate | Status | Primary evidence | Result summary |
|---|---|---|---|
| PRECHECK | PASS | `runtime_state/preflight.md` | Ubuntu 22.04, 4090D Vulkan/EGL, root/APT, 30 GiB shm, storage/network available |
| INSTALL | PASS | `runtime_state/versions.lock.yaml` | Apollo 10 AEM host, core build/runtime, CARLA 0.9.15, Guardian Python 3.10 |
| A0 CARLA | PASS | `runtime_state/evidence/repeatability/checkpoint.yaml` | Three 1,800-second rendered synchronous RGB/LiDAR runs |
| A1 closed loop | PASS | `runtime_state/evidence/a1/checkpoint.yaml` | Three clean-start Town01 Apollo PnC–CARLA closed loops |
| A2 diagnostic actions | PASS | `runtime_state/evidence/a2/checkpoint.yaml` | Three control-delay/O1/I2 repeats with measured evidence and costs |
| Oracle isolation | PASS | `runtime_state/evidence/a2/isolation_{1,2,3,4}.json` | Diagnosis UID denied label, injector config, and injector environment |
| Repeatability | PASS | `runtime_state/evidence/repeatability/checkpoint.yaml` | A0/A1/A2 each have three successful controlled repetitions |
| Clean-shell replay | PASS | `runtime_state/evidence/a2/manifest_4.json` | Full A2 chain replayed under `env -i` |
| Final audit | PASS | `runtime_state/evidence/final/audit.json` | Evidence, schema, tests, static checks, security, whitespace, residuals |

## Environment and pinned versions

- Platform: AutoDL Pro outer container, Ubuntu 22.04.1, kernel 5.15.0-78, 16-vCPU quota, 60 GiB cgroup RAM, 30 GiB `/dev/shm`.
- GPU: NVIDIA RTX 4090 D 24,564 MiB, driver 580.105.08, compute capability 8.9. Apollo CUDA Toolkit is 11.8; the driver's CUDA capability string is recorded separately and was not presented as the toolkit version.
- Apollo: release 10.0; `application-pnc` commit `d994e55fb3c3cf88222f8b4813fa5425cc7c1f56`; AEM `10.0.0-rc1-r4`; buildtool `10.0.0-rc1-r1`.
- CARLA: prebuilt 0.9.15 archive, SHA-256 `7b2f432ce74b251593f95dcc8dee6d99ad9625c2a71a2d6d48f24d879de19ef7`.
- Bridge: guardstrikelab commit `b0c2e088fb703ec5c601cd20616112b46150b180`; patched diff SHA-256 `6e52f4524635a317433a2c29a18a56486f9d4545e79aee737631e7a4df0890ef`.
- Guardian: source snapshot commit `4b3b741fa41a4bcfe6c6294ae7e4a7d019168711`, Python 3.10.20, Pydantic 2.x, JSON Schema validator 4.26.0.
- Complete machine/package decisions and hashes are in `runtime_state/versions.lock.yaml`; Guardian environment locks are `guardian-conda-explicit.lock.txt` and `guardian-pip-freeze.txt`.

Apollo/CyberRT/AEM remained outside Conda. Conda was used only for Guardian/offline validation; the canonical CARLA client wheel was installed under `runtime/bridge/python` for the host bridge.

## A0: rendered CARLA repeatability

All three runs used Town01, `-RenderOffScreen -nosound -quality-level=Low`, synchronous mode, `fixed_delta_seconds=0.05`, and `no_rendering_mode=false`.

| Run | Measured wall time | Frames | Tick mean / p99 ms | RGB/LiDAR discards | Max timestamp error | SHA-256 |
|---|---:|---:|---:|---:|---:|---|
| 1 | 1800.011 s | 123,982 | 14.37 / 19.73 | 0 / 0 | 0.0 s | `a939a723...3f58` |
| 2 | 1800.010 s | 124,959 | 14.22 / 18.15 | 0 / 0 | 0.0 s | `d7130c98...bd9` |
| 3 | 1800.012 s | 125,713 | 14.13 / 17.89 | 0 / 0 | 0.0 s | `e8913e25...3889` |

Run 1 peak resource use was 29.24% of the 16-core quota, 45.09 GiB cgroup RAM, 41% GPU, and 6,025 MiB VRAM. New isolated runs remained below 30% CPU and 44% GPU; peak RAM was 12.16 GiB. RGB and LiDAR payloads were non-empty in every run. The Xvfb/llvmpipe route was tested only after an early direct-render diagnosis and was not used to pass A0.

## A1: Apollo–CARLA closed loop

Town01 uses CARLA spawn 9 at `(202.550003, 59.330017)`, mapped to Apollo `(202.550003, -59.330017)` and 0.156318 m from lane `road_10_lane_0_-1`. The route ends at Apollo `(288.237488, -59.330009)`.

| Run | Forward progress | Valid planning ratio | Max lateral error | Sim/wall | Result |
|---|---:|---:|---:|---:|---|
| 1 | 11.264 m | 94.19% | 0.594 m | 1.0445 | PASS |
| 2 | 10.094 m | 94.09% | 0.435 m | 1.0445 | PASS |
| 3 | 11.092 m | 94.83% | 1.084 m | 1.0445 | PASS |

Each run observed 901 consecutive CARLA frames over about 45 seconds, one successful route, live planning/control, and continuous perception/prediction semantic heartbeats. The scenario is declared empty road: the heartbeat consumes only `/clock` and publishes typed empty obstacles. CARLA actor truth and the bridge's pseudo-GT sensors are disabled.

Apollo launches routing, old-routing adaptation, prediction, planning/external-command, and standard control from `runtime/apollo_g0/a1_pnc.launch`. Startup/health/cleanup managers left no Apollo or bridge residual process.

## Bridge audit and modifications

The selected upstream is `https://github.com/guardstrikelab/carla_apollo_bridge.git`, pinned at the commit above. The repository root is Apache-2.0; individual inherited files retain Intel/CARLA MIT notices. Upstream documented CARLA 0.9.14 and Apollo 8.0 with Docker; no Docker instruction was executed.

The local audit is `runtime_state/bridge_audit.md`. The 12-file compatibility patch:

- maps Apollo 8 Python/message imports to Apollo 10 and lazily avoids disabled camera dependencies;
- uses the managed Python 3.10 CARLA 0.9.15 wheel;
- publishes integer-nanosecond Cyber clock and simulator-stamped localization/chassis/TF;
- preserves CARLA-to-Apollo `x`, negates `y`, and converts degrees to radians;
- avoids a CARLA same-map reload crash and fixes deterministic spawn/map selection;
- adds real-time pacing, explicit throttle/brake gains, and the documented localization acceleration policy;
- makes the bridge control input configurable so A1 stays direct and A2 can insert the guarded control boundary;
- removes pseudo obstacle/traffic-light GT sources for this gate.

The bridge is an adapter, not a detector. Its upstream empirical steering ratios and A1-only acceleration stabilization are recorded limitations; they are not generalized as production calibration.

## A2 observation/intervention audit

The benchmark fault is a deterministic 2.0-second delay at the `control_target` transport boundary before CARLA actuator conversion. The injector reads a root-only numeric configuration but no simulator state or oracle label.

O1 queries one bounded L1 `tracking_execution` semantic slot composed of control target and vehicle response. Diagnosis runs as UID 1001 and creates Guardian evidence `obs_tracking_lag_001`. It receives no native topic names, module graph, fault label, injector state, CARLA actors, or oracle.

I2 is an explicit `R2_non_GT_semantic_replacement`: a fixed 60% brake target for two seconds at the guarded control output. It is not perfect-state replacement. Declared side effects are temporary nominal-target suppression, stale delayed-target queue clearing, and vehicle braking.

| Run | Observed fault lag | I2 application latency | O1 bytes | O1 parent runtime | Result |
|---|---:|---:|---:|---:|---|
| 1 | 2.044194 s | 0.007088 s | 222,192 | 0.2080 s | PASS |
| 2 | 2.037914 s | 0.030475 s | 222,097 | 0.1840 s | PASS |
| 3 | 2.044009 s | 0.022372 s | 222,185 | 0.1933 s | PASS |

Each formal run captured 466 consecutive tick callbacks with zero gaps. The action artifact was about 1.3 KiB and the intervention duration was 2.0 seconds; human cost was zero and one R2 intervention was counted. Run 4 replayed the same chain from an empty shell environment and passed.

Physical isolation uses root-only mode-0700 evaluator directories and a diagnosis-owned visible directory. In all four runs, UID 1001 was denied reads of the oracle label, injector configuration, and injector process environment. Only after diagnosis exited did the root evaluator match the observed effect to the oracle and generate the run manifest.

## Contracts and conformance

The platform-neutral responsibility contract, semantic slot schema, action schema, and run-manifest schema are frozen under `coordination/contracts/`. Apollo native topic names appear only in `coordination/handoffs/apollo_native_mapping.yaml` as provenance, never as responsibility answers.

`scripts/validate_contracts.py` validates three Draft 2020-12 schemas, four real A2 runs, and one golden platform-neutral input/output. The Guardian suite collected 61 tests: 56 passed and 5 declared conditional skips. Contract change control is recorded in `coordination/decisions/ADR-0001-contract-v0.md`.

## Reproduction and final validation

The executable runbook is `runtime_state/APOLLO_G0_RUNBOOK.md`. Principal commands are:

```bash
scripts/manage_carla_server.sh start
scripts/run_a1_repetition.sh RUN_INDEX
scripts/run_a2_repetition.sh RUN_INDEX
runtime/envs/guardian-py310/bin/python scripts/validate_contracts.py \
  --bundle-root "${CAGE_BUNDLE_ROOT}"
```

The clean-shell replay used `env -i` with only HOME, identity, locale, PATH, and TERM. Final audit passed JSON/YAML parsing, all gate evidence, oracle isolation, schema/golden conformance, Guardian tests, `bash -n`, Python compilation, ShellCheck, Git whitespace checks for the Apollo/bridge worktrees, credential pattern scan, `.env` scan, and managed-process residual scan. The authoritative checksum is recorded in `runtime_state/evidence/final/checkpoint.yaml`.

## Failures and final fixes

Every unsuccessful route is preserved in `runtime_state/failure_ledger.jsonl`. The complete groups are:

- Download/install: slow CARLA/Bazel/OpenH264 routes were changed to verified segmented or source/cache routes; TensorRT package naming was verified; blocked Qt/ShellCheck/Patchelf caches and transient pypcd TLS were repaired without changing versions.
- A0 startup: CARLA's root refusal led to a dedicated UID 1001 launcher; direct Vulkan sensor timing was repaired with explicit sensor cadence. Xvfb failed with Vulkan surface creation and remained only a documented fallback.
- Apollo host mode: inconsistent AEM marker location, ignored noninteractive rcfile, provider profile strict-mode behavior, a transient Apollo package proxy failure, and one interrupted retry were individually recorded and resumed idempotently.
- Cyber runtime: missing host protobuf, wrapper discovery, and incompatible system `libprotobuf` caused successive import failures/segfault; the unified launcher now selects the installed Apollo native wrapper and `libprotobuf.so.3.14.0.0`.
- Bridge/A1: Apollo 8 imports, eager optional sensors, same-map CARLA reload crash, routing system-vs-sim timestamp mismatch, and an optional empty response-module observer field were each isolated and fixed. Failed observer evidence was retained.
- A2/contracts: a foreground frame-acquisition gap was fixed with independent `on_tick` sampling; missing JSON Schema dev dependency, an overbroad no-leakage assertion, and Guardian's project-root test assumption were corrected and retested.
- Final repeatability: the first rerun command exposed the host wrapper's cwd change before any A0 sampling began; the runbook now uses the absolute canonical script path.

No identical error was repeated three times without a route change, and no hard blocker or hard-budget condition was reached.

## Resource and storage outcome

Estimated powered-on time at completion is 18.9 hours, below the 30-hour limit and within 24 elapsed hours of the five-day budget. The workspace uses 53 GiB of the 226 GiB overlay (24%), leaving about 173 GiB; neither storage warning threshold was approached. Detailed chronological values are in `runtime_state/resource_ledger.csv`.

## Modified deliverables and remaining boundary

Implementation changes are contained in `scripts/`, `runtime/apollo_g0/`, the pinned bridge worktree, the Guardian conformance test/dev dependency, and `coordination/`. Runtime evidence and resumable state are under `runtime_state/`; managed binaries/data remain under `runtime/` according to the storage contract.

There is no unfinished Apollo G0 gate. Autoware installation, D0, full Multi-Agent/LLM policy, bulk baselines, and production vehicle claims remain intentionally out of scope. Apollo-only success does not prove cross-stack transfer, semantic action equivalence on Autoware, or the paper's final comparative hypothesis.
