# PR826 灰盒诊断 Demo TODO

> 当前状态：STABLE_REFERENCE_ADMITTED — P2 configured reference 已通过冻结的 3/3 门槛
> 详细设计：PR826_GREYBOX_DIAGNOSIS_DEMO_PLAN.md

## P0 — 计划、来源与边界

- [x] 读取 bundle、研究合同、存储合同、Guardian adapter/schema 和 runtime state。
- [x] 核验 HINT、PR826、修复 commit、Apollo 10 Prediction/AEM/buildtool。
- [x] 只读审计 Zenodo HINT.zip 中央目录，不下载整包。
- [x] 确认 scene1 record/yaml/README 公开存在。
- [x] 记录 paper 与 artifact 的 failed-overtake / collision-cut-in 不一致。
- [x] 冻结核心输出为模块 + 接口 + 信号 + 证据链 + 成本 + 停止理由。
- [x] 将代码定位和自动修复移出核心范围。
- [x] 完成 DeepSeek 43-token JSON 连通性测试，key 保持在 workspace 外。
- [x] 恢复并验收一个现有 Apollo 场景烟测；按合同记录 FAIL。
- [x] 修复 speed-optimizer evaluator 假阴性并新增回归测试。
- [x] 用户审核并冻结设计文档第 12 节的 6 个决策点。
- [x] 冻结四维 raw cost 与预注册 scalar cost function。
- [x] 将 I2-K minimal-field diff、identity、wrong-domain、side-effect checks 提升为 admission gate。
- [x] 要求所有 normal-only reference screening attempt 进入 append-only 失败账本。

## P1 — Artifact 与 Apollo 10 Prediction bring-up

- [x] 完成 scene1.record 单条目的 range 下载、SHA256 和 Cyber record info。
- [x] 记录 37 个 channels、46.218074 秒区间及 map/route 缺失项。
- [x] 原生抽样 Perception/Prediction/Planning/Localization，确认 obstacle 100 的 cut-in/lane-transition 特征。
- [x] 记录 Apollo 10 Python RecordReader ABI 错误和原生 replay 非 TTY 输出问题。
- [x] 审计公开 Google Drive scenario 目录；只下载每个 scene 的 README/YAML 小文件。
- [x] 未发现 PR826 failed-overtake scenario/port patch；标记 exact port patch unavailable in audited public files。
- [x] 运行 stock Apollo 10 Prediction smoke：PerceptionObstacles -> PredictionObstacles。
- [x] 验证 obstacle IDs、timestamps、trajectory probabilities、channel rates 和 map lookup。
- [x] 增加 Prediction semantic-slot adapter 与 schema tests。
- [x] 通过 oracle/fault-label leakage scan。

## P2 — Normal-only failed-overtake 场景

- [x] 在 Town01/Town04 枚举可用直路，不写 fault patch。
- [x] 每次 attempt 预先分配 screening_id 并追加 reference_screening_ledger.jsonl。
- [x] 保存所有 REJECT manifest、指标、reject code 和 evidence path，不覆盖失败记录。
- [x] 冻结 spawn、route、seed、physics 和 success region。
- [x] 跑 1 次短 reference screening。
- [x] reference 不超车时定位 Planning 接口/能力并换场景，不降低 success oracle。
- [x] screening PASS 后预注册 3-repeat contract。
- [x] 永久保留 RF01 首个预注册 repeat 的失败证据，不修改其冻结 oracle。
- [x] 完成 P2-D first-divergence、Planning/Prediction timing 与 CARLA determinism 调查。
- [x] 证明完全静止 RF01 主要属于 Planning static-obstacle 路径，不满足 Prediction trajectory gate。
- [x] 通过 small sweep 找到 Town04、1.10 m/s 的 Prediction-aware configured reference。
- [x] 在正式结果前冻结 80 s v2 contract、candidate/config/artifact hashes 和 success oracle。
- [x] 完成 3/3 fixed formal runs：三次均完成超越、到达 success region，且 Prediction
  trajectory coverage 分别为 0.9839、0.9870、0.9870。
- [x] 生成 normal-only checkpoint：`runtime_state/pr826_greybox_demo_v1/P2_REFERENCE_CHECKPOINT.md`。
- [x] 生成最终报告、机器审计、append-only screening/fix/research ledgers 并纳入版本控制。

P3–P9 均未执行：本轮授权范围只到 normal/reference admission。当前结果只证明正常臂稳定，
不声称未来 PR826 semantic fault 一定能抑制该 route-driven overtake。

## P3 — PR826 semantic-port fixture

- [ ] 为现代 FilterLaneSequences 构造最小 candidate lane graph fixture。
- [ ] stock fixture 保留正确高置信 candidate。
- [ ] faulty guard 只改变 nearby lane-sequence filtering 语义。
- [ ] 私有 telemetry 记录 before/after candidate set 和最终 trajectory。
- [ ] 单元测试验证 exact delta、无越界副作用和 patch 可回滚。
- [ ] 在 CARLA faulty 结果前冻结 patch SHA 和 mechanism oracle。

## P4 — Matched fixed/faulty runs

- [ ] 1 次 faulty screening；只有 mechanism 激活才继续。
- [ ] reference 3/3 PASS、faulty 3/3 failure、mechanism 3/3 activation。
- [ ] activation-to-failure <= 5 s。
- [ ] 除 build/patch ID 外 matched manifests 一致。
- [ ] visible 目录零 fault/oracle/injector/PR826/commit 泄漏。
- [ ] 任一门槛失败则 CASE_NOT_ADMITTED，选择下一 scene–fault pair。

## P5 — 灰盒 observation tools

- [ ] O0 failure-window/realized-motion query。
- [ ] O1-C control tracking residual。
- [ ] O1-P planning consistency/propagation check。
- [ ] O1-F Prediction ADE/FDE/heading/maneuver fidelity。
- [ ] O2-T timing/rate/drop/age query。
- [ ] 每个 tool 输出 evidence ID、provenance、cost、side effects 和 status。
- [ ] wrong-module、missing-signal 和 tool-failure tests。

## P6 — Intervention controls

- [ ] I2-K constant/zero-velocity model probe，不读取 future GT。
- [ ] field-diff verifier 只允许 trajectory semantics 白名单字段变化。
- [ ] identity probe 3/3 序列化等价且无行为差异，否则不准入。
- [ ] wrong-domain probe 3/3 不改变目标 failure，否则不准入。
- [ ] I2-K 3/3 rate/age/count/ID/timestamp/非目标对象 side-effect audit，否则不准入。
- [ ] 可选 I3-GT upper bound，单独权限和成本报告。
- [ ] 若只有 I3 有效，触发 low-access warning。

## P7 — Controller 与报告

- [ ] 定义 hypotheses 和 likelihood source。
- [ ] 先实现 fixed/rule/greedy Bayesian selector。
- [ ] Agent 只提 typed actions；central gate 唯一执行。
- [ ] verifier 拒绝缺 provenance、非法权限和重复 evidence。
- [ ] 使用 calibration set，或输出 prediction set/uncalibrated score。
- [ ] 实现 diagnose/abstain/tool_failure stop states。
- [ ] report JSON/MD 中所有 claim 引用 evidence ID。

## P8 — 双栏动画 Demo

- [ ] 从 frozen records 渲染 fixed/faulty/probe 左栏。
- [ ] 生成 diagnosis_trace.jsonl 和 overlay_timeline.json。
- [ ] 绘制 candidate/action/cost/evidence/verifier/stop cards。
- [ ] optional L3 用虚线显示，不能提前泄漏答案。
- [ ] 合成 1920x1080、30 fps、60–90 秒 H.264。
- [ ] 人工逐帧核对关键 timestamp 和报告内容。
- [ ] 保存视频 SHA256、渲染命令和 run IDs。

## P9 — Final audit

- [ ] fixed/faulty/probe repeatability。
- [ ] schema/JSON/YAML/Markdown checks。
- [ ] secret scan、oracle isolation、diagnosis UID permission test。
- [ ] clean-shell replay。
- [ ] resource/cost/version/failure ledgers 完整。
- [ ] 对外 claim 不超过一个 Apollo 10/CARLA 0.9.15 受控黄金案例。
