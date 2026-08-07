# CAGE-AD D0 数据生成协议：从候选 recipe 到可诊断 episode

状态：**v1 规范已冻结；正在 Apollo 10 服务器逐条校准，不代表数据已通过**

适用环境：Apollo 10 host mode + CARLA 0.9.15，perfect-perception PnC

规范目录：`benchmarks/apollo_d0/protocol_v1/`

## 1. 先给结论

下一轮不再生成“2 个场景 × 6 个故障 × 若干 seed”的全笛卡尔积。现有 v3 已证明这种做法会产生大量
fault 有注入信号、却没有系统退化，或任意保守 probe 都能避免碰撞的低质量数据。

新的样本单位是一个**经过校准并冻结的 episode parent**。它必须同时满足：

1. nominal 可重复、基础设施有效且不发生安全失败；
2. 指定场景会暴露指定 fault，而不是仅能成功写入一条消息；
3. fault 相对同 seed nominal 造成可重复的安全退化；
4. fault effect 在系统退化之前出现；
5. 正确责任域 probe 的配对改善显著超过错误域 probe，或者该 case 被诚实标成 ambiguous；
6. policy 可见数据没有 scenario recipe、fault、GT、companion linkage 或 simulator truth 泄漏。

任何一项不满足，都不能把该运行称为“正确标注的诊断数据”。扩大 seed 之前，先让 recipe 通过 gate。

## 2. 论文到底教会了我们什么

| 来源 | 原工作怎么建数据 | 本协议采用的硬规则 |
|---|---|---|
| HINT | reference 通过、faulty 失败才保留；每例至少 3 次；开发者复核 fault 行为 | pass→fail 配对、至少 3 次、显式 trigger-to-failure window |
| Minimal Grey Box | artifact 写明 inject frame、fault frames、fault type、fault params，并删除 crash/startup-invalid 数据 | 每条注入必须精确到边界、字段、时刻、时长、剂量；infra invalid 不算安全失败 |
| ADSDx | 只留 fault-free 安全、可重放、事故特征可区分的 collision；加入 non-ADS controls | collision identity、多次重放、non-ADS 对照、错域也能修复时不得硬归因 |
| ACAV | fault 对应具体函数语义；记录 causal event 及持续区间 | 每种机制有自己的 activation signature，不能共用一个粗代理量 |
| ROCAS | counterfactual 要消除事故，同时保持事故前轨迹相似，并最小化变化 | probe 必须检查 pre-intervention similarity；“直接刹停”不是自动有效证据 |
| MoDitector | 同时检查 module error、system failure 和 effect window 内其他模块错误 | 三层 gate 分开；多域重叠进入 ambiguous，不改成单一标签 |

精确文献事实与哪些数值属于本项目推导，见 `literature_provenance.yaml`。论文中的 Apollo/VTD/LGSVL
版本和参数不能机械搬到 Apollo 10 + CARLA 0.9.15；本协议只继承构造逻辑，数值使用预声明网格校准。

## 3. 五类对象，不能再混为一个布尔值

一个 run 必须分别输出：

- `infrastructure_valid`：Apollo 模块健康、route 接受、actor 成功生成、仿真时钟推进、所需流存在、injector 无异常；
- `mechanism_activated`：fault 专属 signature 是否满足；
- `safety_outcome`：collision、minimum TTC、collision object/position/angle/relative speed；
- `task_outcome`：route completion、forward progress、timeout；
- `attribution_outcome`：正确域与错误域干预的 paired effect、相似性和选择性。

Apollo 未启动、route 失败、actor 没生成、planning stream 缺失一律是 `infrastructure_invalid`。它们不得再被
并入 `task_failure=true`，更不得给 fault 投票。

## 4. 每条数据具体怎么做

下表的 12 行就是第一轮全部 calibration items。不得自动增加组合，也不得临时换场景。每行先按
`scenario_recipes.yaml` 的 `candidate_order` 从第一个候选开始，再按 `fault_recipes.yaml` 的 `dose_grid`
从弱到强搜索。选择第一个通过全部 gate 的组合；若所有候选或剂量都失败，该 recipe 记为 rejected。

| ID | 场景 | 故障 | 这条数据必须暴露的现象 | 禁止替代 |
|---|---|---|---|---|
| CAL-F01 | close lead brake | forecast content delay | 前车开始制动后，prediction content age 达到所选 delay，安全 margin 配对下降 | 丢消息、改 header 但不延迟内容 |
| CAL-F02 | moderate lead brake | forecast content delay | 换一组 headway/braking 后仍出现相同 stale signature | 复制 F01 原始轨迹 |
| CAL-F03 | early cut-in | maneuver attenuation | 保持 actor 当前 pose，逐级削弱 future lateral displacement 并重算 heading | 固定旋转 75°、改 actor GT |
| CAL-F04 | late cut-in | maneuver attenuation | 更晚更快横向侵入下复现相同 semantic error | 改成 lead-brake 场景 |
| CAL-P01 | close lead brake | braking constraint attenuation | nominal 本来存在制动 suffix；只衰减负加速度并重积分 `v/s/x/y/t` | 直接把每点速度设为 10 m/s |
| CAL-P02 | moderate lead brake | braking constraint attenuation | 第二组停车 margin 下仍产生可重复退化 | 删除 NPC 或修改 prediction |
| CAL-P03 | early cut-in | unsafe temporal cost | 保留几何 path，压缩 post-trigger 时间并一致变换 `v/a` | 只改 `v/a` 不改时间 |
| CAL-P04 | late cut-in | unsafe temporal cost | 第二组横向冲突下复现同一时间压缩 signature | 改 path geometry |
| CAL-C01 | close lead brake | whole-command delay | control request 与 release 的实测延迟达到剂量并损失停车 margin | 3.5 s 固定超强延迟、乱序命令 |
| CAL-C02 | early cut-in | whole-command delay | 横向命令序列上复现相同 delay，检验跨 outcome geometry | 只延迟 brake 字段 |
| CAL-C03 | close lead brake | actuator effectiveness scalar | 保持命令符号与互斥，等比例降低 actuator effect | throttle 加 bias 且 brake 清零 |
| CAL-C04 | early cut-in | actuator effectiveness scalar | 同一 scalar 同时作用于 steering/braking demand | 为此 case 单独发明另一控制 fault |

### 4.1 当前校准进度（2026-08-07）

| ID | 通俗场景含义 | 已执行内容 | 当前终态 | 为什么没有继续生成 fault 数据 |
|---|---|---|---|---|
| CAL-F01 | 近距离跟车，前车制动；检查旧预测是否会让自车反应太晚 | LBC0/LBC1/LBC2 各 5 个名义种子，共 15 次 | `rejected_no_causal_dose` | 15/15 基础设施有效且无碰撞，但 15/15 没有进入要求的 TTC 敏感区间 |
| CAL-F02 | 中等距离跟车，前车制动；检查同一预测延迟现象能否换一组车距复现 | LBM0/LBM1/LBM2 各 5 个名义种子，共 15 次 | `rejected_no_causal_dose` | 15/15 基础设施有效且无碰撞，但 15/15 没有进入要求的 TTC 敏感区间 |

这两条终态的意思是：当前冻结场景没有把 Apollo 带到足够接近风险边界的位置，所以协议不允许继续注入故障。
它们不是“预测延迟无害”的证据，也不是可供训练或正式评价的独立诊断 episode。失败样本及资源用量保留在持久盘账本中，
公开仓库只保存不泄漏私有 oracle 的分子/分母摘要。其余 recipe 尚未运行，不提前填写结果。

每行的执行步骤完全相同：

1. 对 candidate 0 分别用 calibration seeds `1101–1105` 各跑 1 次 nominal；5/5 runtime valid、5/5 无碰撞、5/5 route accepted，且至少 4/5 的
   minimum TTC 位于 `(2.5, 6.0]` 秒，才继续；否则按列表试 candidate 1、2。
2. `conflict_onset` 直接取被选 candidate 声明的 `brake_start_s` 或 `cut_in_start_s`。注入固定从
   `conflict_onset - 1 s` 开始，到 `conflict_onset + 3 s` 结束。该时间只写 private oracle，不得由运行者另算。
3. 对 fault 剂量从弱到强，每档分别用 seeds `1101/1102/1103` 各跑 1 次。要求 3/3 runtime valid、
   3/3 mechanism activated，至少 2/3 相对同 seed nominal 的 safety risk 增加不小于 0.20，且 fault effect
   先于退化、间隔不超过 5 s。
4. 选择第一档满足条件的最小剂量；立即停止该 recipe 的 candidate/dose search，更强剂量与后续 candidate
   都不再尝试。若当前 candidate 所有 dose 都不满足 pre-probe gate，才试下一个 candidate。将 candidate、dose、trigger window 和实现
   SHA-256 写入 calibration decision。
5. 在同一 candidate/dose 上，用 seeds `1101/1102/1103` 分别跑 no-probe、forecasting probe、planning
   probe、control probe，每个 seed/condition 各 1 次。任何 probe 在开始前都必须与同 seed no-probe
   保持轨迹 MSE ≤ 0.25 m²。
6. 正确域 median risk improvement 至少 0.20，且比最佳错误域严格多于 0.10，才标为 `identifiable`。
   多个域效果接近、多个 module errors 重叠，或正确域效果不足但注入因果成立时，标为 `ambiguous`。
7. 完整分类优先级为：infra/nominal/transform/leakage/collision identity 失败 → `rejected`；所有 candidate/dose
   都无因果退化 → `rejected_no_causal_dose`；probe 的轨迹相似性、regression harm 或输出不变量失败 →
   `rejected_probe_invalid`；effect window 多域错误 → `ambiguous_multi_domain`；正确域改善不足 →
   `ambiguous_insufficient_correct_effect`；正确域领先最佳错误域不超过 0.10 → `ambiguous_nonselective`；其余才是
   `identifiable`。不得删除，也不得人工改成通过。
8. 只有 `identifiable` recipe 才冻结后运行 formal seeds `2101/2102/2103`。每个 formal seed 的每个
   condition 都跑 repeat indices `0/1/2`，即每个正式 episode 有 15 个 companion executions。formal run
   不允许调 scenario、fault、probe、threshold 或 split。

## 5. 三个 probe 必须是什么，不是什么

精确 probe 参数和不变量以 `probe_recipes.yaml` 为准。

### 5.1 Forecasting probe

输入仅限最近 1 s policy-legal actor history；使用同一套 constant-acceleration / constant-turn-rate 运动学
候选，根据过去残差选择或加权，不读取 CARLA future truth。输出必须从当前 actor pose 开始、时间单调、速度
有界。原来的 constant-velocity probe 对“前车减速”和“车辆切入”天然错误，不能再用作正确域反事实。

### 5.2 Planning probe

输入为 policy-legal ego state、当前 semantic obstacle state 和当前参考 path。独立生成一个动力学可行的
safety trajectory，`x/y/s/v/a/relative_time` 必须一起生成并通过一致性检查。它可以保守，但 intervention
前不能改变已经发生的轨迹，也不能简单把车冻结。

### 5.3 Control probe

输入为当前 motion target 与 ego tracking state；由独立、冻结参数的 tracking controller 产生 actuator
command。它不能读取 fault ID，不能固定施加 60% brake，也不能为了每个场景单独调参。先在 fault-free
regression set 上证明副作用/false repair or harm rate ≤ 5%。

probe 的目的是受控改变一个责任域 contract，不是保证避免任何碰撞。正确域 probe 也可能因下游错误而无法
完全修复；错误域 probe 也可能通过过度保守掩盖下游 fault。protocol 正是用 paired effect 和 margin 区分这些情况。

## 6. 事故同一性与可重复性

发生 collision 时，至少 2/3 repeats 必须满足：

- 同一 counterpart actor；
- collision position 相差不超过 2 m；
- collision angle 相差不超过 15°；
- relative speed 相差不超过 2 m/s。

只要 `collision_count > 0` 相同不够。若 probe 改成了另一个更早的碰撞，不能算“原事故未修复”或“产生新修复”，
必须单列 `collision_identity_changed=true`。

## 7. 生成数据在服务器放哪里

Git 只保存源码、声明式 recipe、schema、小 fixtures、汇总 manifest；Apollo/CARLA 和生成数据继续留在持久盘：

```bash
export CAGE_RUNTIME_ROOT=<现有G0 bundle>/runtime
export CAGE_STATE_ROOT=<现有G0 bundle>/runtime_state/d0_protocol_v1
export CAGE_DATA_ROOT=/root/autodl-tmp/cage_ad_data
export CAGE_PRIVATE_ORACLE_ROOT=/root/autodl-tmp/cage_ad_private_oracle
```

建议目录：

```text
$CAGE_STATE_ROOT/
  calibration/decisions/<recipe_id>.json
  ledger/attempts.jsonl
  manifests/
  logs/

$CAGE_DATA_ROOT/<batch_id>/<opaque_episode_id>/
  visible/episode.json
  visible/evidence/
  retained/

$CAGE_PRIVATE_ORACLE_ROOT/<batch_id>/<recipe_id>/
  recipe_snapshot/
  nominal/<candidate>/<seed>/<repeat>/
  dose_search/<candidate>/<dose>/<seed>/<repeat>/
  probes/<domain>/<seed>/<repeat>/
  formal/<opaque_episode_id>/
```

`recipe_id`、candidate、dose、fault/domain label 和 companion linkage 只存在 private oracle/state。policy 只看到
opaque episode ID 和 gate 允许的 visible evidence。

## 8. 服务器 Codex 的实现顺序

服务器收到本仓库后按以下顺序工作，不可直接批量跑数据：

1. 实现 protocol loader 和 schema/cross-reference validation；先让本仓库离线 tests 全过。
2. 把 scenario 参数从 Python hard-code 迁移为 `scenario_recipes.yaml`；一次只实现并验证一个 scenario family。
3. 把六类 fault 分别实现为独立 transformer；每类先做 protobuf fixture 单元测试和 kinematic consistency test。
4. 把 outcome evaluator 拆成 infrastructure/mechanism/safety/task/attribution 五层。
5. 实现 append-only calibration ledger；任何 attempt 开始前记录计划，结束后写 status/hash/metrics。
6. 只跑 `CAL-F01` candidate 0 nominal 5 次；核对 replay、TTC、事故字段和私有/公开隔离。
7. 通过后只完成 `CAL-F01` 的 dose search 和 probes，生成一份完整 calibration decision。
8. 人工审查一条完整 recipe 的 raw metrics、transform invariants 和 leakage scan；没有问题再按 ID 顺序扩到 F02…C04。
9. 冻结通过的 parent 后才运行 formal seeds。formal 结果不好也不得回到同版本调参；修改需新建 protocol v2。

每完成一个 recipe，服务器必须提交：decision JSON、attempt ledger 摘要、每个 gate 的 numerator/denominator、被拒原因、
selected hashes 和精确复现命令。不能只报告 “PASS” 或 “碰撞了”。

## 9. 正式数据集不再预设必须是 36 条

原来的“36 episodes”只是工程规模目标，不是科学约束。最小论文数据应包含：

- 每个通过的 fault archetype 至少 3 个 held-out identifiable episodes；
- 独立的 non-ADS/unavoidable controls；
- 足够的 ambiguous cases 用于评价 abstention，而不是把它们删掉或强行单标。

如果 6 个 archetype 全通过，identifiable core 是 18 条。ambiguous 和 non-ADS 数量由预注册的获取流程决定，不能
为了凑 36 条随意复制。若最终没有可靠 ambiguous cases，论文不能宣称验证了不可辨识时的校准拒答。

## 10. 当前可以和不可以说什么

可以说：本协议把已有论文中的配对筛选、重复验证、事故同一性、最小反事实和单模块可归因规则，转成了
Apollo 10 上逐 recipe、机器可审计的数据生成合同。

不可以说：这 12 条已经是 benchmark、这些数值已经在 Apollo 10 通过、任一 probe 能精确识别根因、36 条数据
已经足够支持跨栈或现实车辆结论。
