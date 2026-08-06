# Apollo 10 D0 持续实现 Prompt（粘贴到 AutoDL Codex）

下面代码块中的内容是一条完整 Prompt。使用前，将本目录下三个设计文件上传到服务器 bundle 的 `docs/d0/`。新仓库已创建为 `git@github.com:LiPume/CAGE-AD.git`；服务器 Codex 负责 clone、初始化必要的 `main`、建立工作分支，并在每个 gate 后提交和推送源码。

```text
你是本项目 Apollo 10 D0 主动诊断实验的持续执行 Codex。你的任务不是提出方案后停下，而是在现有 G0=APOLLO_GO 的持久盘环境上持续实现、测试、运行、记录和 checkpoint，直到得出诚实、可复现的 D0_GO、D0_MODIFY 或 D0_NO_GO。正常工程选择自行依据设计合同决定，不向用户反复提问；只有缺少外部凭据、预算授权、许可证或发生可能破坏既有数据的操作时，才写 USER_ACTION_REQUIRED.md 并暂停受影响步骤。不得为了得到正结果修改标签、split、预算或评价标准。

一、先定位和保护现有环境

1. 定位包含 runtime_state/RUN_STATE.yaml 且 status=APOLLO_GO 的 bundle；确认它位于持久盘。不要移动或重装已通过 G0 的 Apollo/CARLA 环境。
2. 完整读取：
   - runtime_state/RUN_STATE.yaml
   - runtime_state/APOLLO_G0_REPORT.md
   - runtime_state/G0_REPRODUCTION_RUNBOOK.md
   - runtime_state/BRIDGE_INTEGRATION_AUDIT.md
   - docs/d0/D0_ACTIVE_DIAGNOSIS_SYSTEM_DESIGN.md
   - docs/d0/GITHUB_HANDOFF_SPEC.md
   - docs/d0/CODEX_D0_IMPLEMENTATION_PROMPT.md
   - 服务器上的实际 scripts/、coordination/、runtime/apollo_g0/ 和修改过的 bridge/Apollo/G0 源码
   - 不读取、不扩展、不复制旧 project/Zhijia-Guardian；CAGE-AD 是独立科学任务和独立代码库
3. 将大体量 runtime 与源码仓库分离。默认：
   CAGE_RUNTIME_ROOT=<现有 bundle>/runtime
   CAGE_STATE_ROOT=<现有 bundle>/runtime_state/d0
   CAGE_DATA_ROOT=<持久盘>/cage_ad_data
   CAGE_PRIVATE_ORACLE_ROOT=<持久盘>/cage_ad_private_oracle
4. 不删除 G0 文件，不覆盖既有 evidence，不重新下载已经存在且校验通过的依赖。
5. 默认新增实验上限：30 powered-on hours、100 GiB incremental storage。每个 gate 记录用量；接近上限时安全停机、保存状态，并请求用户授权增加预算。

二、新 CAGE-AD 仓库与 source-only checkpoint 是第一 gate

1. 固定 remote 为 `git@github.com:LiPume/CAGE-AD.git`，目标路径为现有持久 bundle 下的 `project/CAGE-AD`。不得更改或复用旧 `project/Zhijia-Guardian`。
2. 若目标路径不存在，执行 `git clone git@github.com:LiPume/CAGE-AD.git <bundle>/project/CAGE-AD`。若目标路径已存在，先验证它是 Git root 且 origin 精确匹配；不匹配时停止，绝不覆盖。
3. 若远端已有 `main` 和 README，切换 `main` 并 `git pull --ff-only origin main`。若远端为空，在新 clone 中创建内容为 `# CAGE-AD` 的 README.md，提交 `first commit`，将分支命名为 main 并 `git push -u origin main`。
4. 从 main 创建 `codex/apollo-d0-active-diagnosis` 并 push upstream。全部 D0 工作只在该分支进行。
5. 如果 SSH 认证失败，写 USER_ACTION_REQUIRED_GITHUB.md，明确缺少的是服务器 GitHub SSH key/授权；继续所有不依赖 push 的源码整理。绝不能把 token 或 private key 写进仓库。
6. 按 GITHUB_HANDOFF_SPEC.md 从服务器实际 G0 bundle 收集源码、配置、contracts、UPSTREAM provenance 和 textual patches。不要从旧 Zhijia-Guardian 复制代码。大文件、runtime、raw data、private oracle、secret 不得进入 Git。
7. 将 docs/d0 下三个设计文件复制进新仓库的 docs/d0/，保留其内容和校验和。
8. 运行 secret scan、large-file scan、patch/provenance 检查和 CPU tests；提交：
   chore(g0): checkpoint Apollo 10 reproducible source
9. remote 可用时立即 push。以后每个 D0 gate 都独立 commit/push。

三、数据策略不可更改

主 benchmark 必须在当前 Apollo 10 + CARLA 0.9.15 环境中受控生成，因为评估对象是 action-aware、cost-aware sequential diagnosis。先生成 12 个 D0-A0 smoke episodes，再冻结 registry/split，最后生成 36 个 D0-A1 Apollo episodes。不要把 ADSDx/ACAV/HINT 静态数据混入主 train/test；它们只作为 fault taxonomy、adapter/protocol smoke 或单独外部复现。旧 Zhijia-Guardian 的数据与结果不进入新仓库的默认回归或主指标。不要开始 Autoware。

每个 episode 必须区分：
- diagnosis-visible initial evidence；
- legal unexecuted actions；
- 每一步新增 evidence、measured cost、posterior 和 stop decision；
- evaluator-private fault config/GT；
- nominal/fault/wrong-domain probe/counterfactual linkage。

主数据规模：
- D0-A0：3 domains × 2 mechanisms × 2 scenarios × 1 seed = 12 fault episodes；
- D0-A1：3 × 2 × 2 × 3 seeds = 36 fault episodes；
- nominal、fault confirmation、counterfactual runs 是配套运行，不冒充额外独立诊断样本。

四、按以下 gates 顺序持续执行

Gate D0-1 — Contracts/state/budget/verifier
- 建立 Python package、Pydantic/JSON Schema：EpisodeSpec、DiagnosticState、ActionProposal、VerifiedEvidence、DiagnosisResult。
- 建立 ActionCatalog、BudgetLedger、EvidenceLedger、BeliefState、append-only event log、crash resume 和 intervention idempotency。
- central gate 是唯一工具执行入口；policy/LLM 只能提出 typed proposals。
- 建立 evaluator-private 独立进程/权限边界和 forbidden-key/path tests。
- 先用 synthetic fixtures 完成 CPU unit/property tests。
- commit/push: feat(d0): add diagnosis contracts and state engine

Gate D0-2 — 12-episode benchmark smoke
- 实现两个可重复交互场景：lead_vehicle_deceleration、cut_in_or_crossing_actor。
- D0 限定为 perfect-perception PnC benchmark；simulator truth 可构造 stack input，但不能进入 diagnosis view。
- 实现六个 fault mechanisms：
  interaction_forecasting: stale/delayed forecast；heading/maneuver bias
  motion_planning: constraint omitted；unsafe cost/speed bias
  tracking_execution: command transport delay；gain/saturation/tracking bias
- 实现 O0/O1/O2/O3 和非 GT 的 I2-F/I2-P/I2-C；wrong-domain probes 必须存在。
- 完成 12 episodes 的 nominal、fault confirmation、counterfactual、泄漏扫描、重复性和副作用审计。
- 任一 fault 不稳定时，最多进行一次明确的基础设施修复；保留失败记录，不静默删样本。
- commit/push: feat(d0): add benchmark generators and semantic tools

Gate D0-3 — 冻结并生成 36-episode Apollo pilot
- 在看到正式 test 结果前冻结 scenario_registry.yaml、fault_registry.yaml、action_catalog.yaml、split_registry.yaml、failure thresholds 和 budget profiles B0–B4。
- group key=semantic_fault_template+scenario_parent；seed/参数变体不得跨 split。
- 生成 36 个 fault episodes；每个有 opaque ID、visible manifest、private oracle、checksums、cost 和 provenance。
- raw sensor/record 留在 CAGE_DATA_ROOT，private oracle 留在 CAGE_PRIVATE_ORACLE_ROOT；Git 只收 generator、registry、small semantic fixtures、manifest index。
- 输出 invalid/retry/failure ledger 和资源用量。

Gate D0-4 — 先完成全部非 Agent baselines
- 在同一 DiagnosticPolicy 接口上实现 fixed_full、fixed_minimal、random_legal、rule_tree、greedy_bayesian、evaluator-only oracle_ig。
- 所有 policy 共用相同 deterministic feature extractor、belief engine、posterior update、tool executor 和 evaluator。
- 输出 B0–B4 的 selective risk vs cumulative evidence cost、cost at matched risk/coverage、wrong-singleton、correct-abstain、Top-1/MRR 和资源指标。
- grouped bootstrap/cross-validation 以 fault-template/scenario group 为单位；样本少时只报告 pilot interval，不写夸大显著性结论。
- commit/push: feat(d0): add non-agent diagnostic policies

Gate D0-5 — Single-Agent 后再 structured Multi-Agent
- 只有 D0-4 完成后才接 LLM provider。若缺 API key/provider，先完成并报告全部非 LLM 结果，再写精准的 USER_ACTION_REQUIRED_LLM.md。
- Single-Agent 接收完整 shared state 和有限 catalog，只输出 typed ActionProposal。
- Multi-Agent 仅包含 Forecasting、Planning、Control/Integration specialists；共享 posterior、evidence、总 token/API/action budget，由 deterministic coordinator 选一个动作。禁止自由辩论和多数投票当 posterior。
- same model、temperature、timeout、total token/API/action budget；按 Agent 数分摊而不扩容。
- 实现 static-vs-pruned、without-gate、without-verifier、non-LLM specialists 消融。
- commit/push: feat(d0): add single-agent policy
- commit/push: feat(d0): add structured multi-agent policy

Gate D0-6 — Calibration、审计和终态
- 用 calibration groups 冻结 abstention/stop threshold；实现 never-abstain、max-prob、temperature-scaled、prediction-set/action-aware stop。
- 输出 risk–coverage、AURC、Brier、ECE、prediction-set coverage/size、matched-risk cost。
- 执行 equal-budget audit、oracle leakage audit、secret/large-file audit、clean-shell replay 和完整 checksum/provenance audit。
- 运行预注册 kill criteria。不能因 greedy ≥ Agent 把工程任务判失败；应诚实选择：
  D0_GO_FULL：adaptive>fixed/greedy 且 Multi>Single
  D0_GO_ACTIVE_ONLY：adaptive>fixed/greedy，Multi≈Single
  D0_GO_NON_LLM：greedy≥Agent，但 adaptive>fixed
  D0_NO_GO_H1：fixed≥adaptive
  D0_NO_GO_LOW_ACCESS：只有 I3/full L2 有效
  D0_MODIFY_INFRA：注入/重放不稳定且仍有一次明确修复价值
- commit/push: test(d0): freeze pilot protocol and audit results
- 生成 D0_FINAL_REPORT.md、RUN_STATE.yaml、REPRODUCTION_RUNBOOK.md、RESULTS.csv/parquet、图表源码、CLAIMS_ALLOWED.md 和 LIMITATIONS.md。

五、持续执行与报告规则

1. 用 runtime_state/d0/RUN_STATE.yaml 维护 gate、状态、预算、commit、运行 ID、失败和下一动作；每完成一个 gate 立即更新。
2. 任何长跑都可恢复；不要重复执行有副作用的 intervention，不要重复计费。
3. 编码和离线测试时关闭 Apollo/CARLA，节省 GPU/计费；从 12 smoke 起步，不直接批量跑 36。
4. 每个结果必须绑定 source commit、runtime version、config SHA、data manifest SHA 和 command。
5. 实验成功的定义是完成无泄漏、可比较的检验并得到诚实终态，不是让 LLM 或 Multi-Agent 赢。
6. 不开始 Autoware、不扩大到 perception/end-to-end、不自动修复代码、不调用 evaluator oracle 帮助诊断。
7. 直到所有不依赖用户新授权的 gate 均完成前，不要以“给出下一步建议”作为终止。若发生阻塞，先穷尽安全的本地修复和替代路径，再写单一、精确的 USER_ACTION_REQUIRED 文件。

现在开始：先定位 APOLLO_GO bundle，clone/验证全新的 CAGE-AD 仓库，读取全部指定文件，做 source-only G0 checkpoint 和 Gate D0-1。持续向下执行。
```
