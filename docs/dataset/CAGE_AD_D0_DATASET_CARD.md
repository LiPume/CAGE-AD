# CAGE-AD D0 数据集说明书

状态：**工程试验数据，尚不具备公开发布为正式 benchmark 的条件**

文档版本：0.2

运行环境：Apollo 10 主机模式 + CARLA 0.9.15

任务范围：完美感知条件下的规划与控制（PnC）主动诊断

最新试验结论：`d0_a0_repaired_v3` 的 84/84 个当前配套运行均有效，但预注册的组合科学 gate 只有 2/12 个 episode 通过，终态为
`D0_MODIFY_INFRA`。这批数据不能被宣传为已经验证的 benchmark；在明确标注“失败的工程 pilot”时，它仍可用于研究数据生成器、故障注入和诊断协议。

本文解释 D0-A0 中每一种场景、故障、配套运行、诊断动作和字段的含义，同时给出未来公开数据集所需的发布检查表。文件已经生成并不代表数据集可以发布；重复性、泄漏、故障稳定性、反事实选择性、许可证和校验和检查必须全部完成。

## 1. 数据集要研究什么

CAGE-AD D0 研究模块化自动驾驶系统中的**动作感知、成本感知序贯诊断**。诊断策略只从有限的初始失败证据开始，在预算内选择合法的观察或受控干预，支付每一步的实际成本，更新责任域后验，最后输出诊断或选择弃权。

适合研究的问题包括：

- 在相同预算下比较固定诊断策略和自适应策略；
- 衡量累计证据成本与 selective risk 的关系；
- 检查不使用 GT 的安全干预能否改善责任域定位；
- 审计弃权、错误单一诊断以及责任域概率校准。

它不是感知、传感器融合、端到端驾驶、自动修复或开放道路安全 benchmark。仿真器真值只能由特权适配器用于构造完美感知的栈输入，诊断进程严禁读取仿真器真值。

## 2. 样本单位和规模

一个**诊断 episode**对应一个不透明的“场景 × 故障 × seed”组合。与它关联的 nominal、故障重复和 probe 仿真只是为这个 episode 生成初始证据和反事实证据，不是额外独立样本。

| 阶段 | 场景模板 | 责任域 | 每域机制数 | seed 数 | 独立诊断 episode |
|---|---:|---:|---:|---:|---:|
| D0-A0 smoke | 2 | 3 | 2 | 1 | 12 |
| D0-A1 原目标 | 2 | 3 | 2 | 3 | 36 |

每个 D0-A0 episode 有 7 个配套运行：1 个 nominal、3 个相同故障确认重复、1 个正确责任域 probe 和 2 个错误责任域 probe。因此 12 个 episode 一共需要 84 次仿真，但科学样本量仍然是 12，不能写成 84。

D0-A1 必须在查看正式 test 结果前冻结 registry 和 split。同一 `semantic_fault_template + scenario_parent` 下的 seed 或参数变体不得跨 split。由于 D0-A0 未通过，D0-A1 没有生成。

## 3. 两个场景共有的驾驶环境

当前两个场景都在 CARLA Town01 的同一条向东直线路线上运行：

- Apollo 坐标起点：`(202.550003, -59.330017)`；
- Apollo 坐标终点：`(288.237488, -59.330009)`；
- 观察窗口：路由 epoch 后 32 个仿真秒；
- 被测栈：Apollo 10 routing、planning 和 control，主机模式；
- 交互车辆：`vehicle.audi.tt`，相对于 ego 确定性生成；
- 栈输入：特权完美感知适配器发布置信度为 1.0 的车辆障碍物和 5 秒语义预测；
- 预测轨迹：每 0.2 秒一个点，共 26 个点，包含时间零点。

路由请求到达时刻定义场景 epoch。在 epoch 之前，交互车辆保持静止，避免 Apollo 启动时延改变 nominal、fault 和 probe 的初始条件。

当前 smoke 的任务失败条件是以下任一项发生：至少一次碰撞、最小 TTC 小于 2.5 秒、路由失败，或者 32 秒内前向进度小于 5 米。这些是 D0-A0 工程阶段预先登记的阈值，不能在查看正式结果后调节。

## 4. 场景逐项说明

### 4.1 `lead_vehicle_deceleration`：前车减速停车

**代表什么。** Ego 与同车道前车纵向交互。前车先匀速行驶，随后刹停。这个场景检查预测模块能否表达减速、规划模块能否遵守逐渐收紧的安全包络，以及控制执行是否存在过大延迟或增益错误。

**初始条件。** 交互车辆生成在 ego 正前方 30 米，横向偏移为 0，朝向与 ego 一致。收到路由 epoch 后开始运动。

**车辆运动程序。** 场景时间 0–6 秒以 5 m/s 行驶；6 秒后以 3 m/s² 减速到 0。提供给栈的特权 5 秒预测使用同一运动程序。

**科学含义。** 这是纵向跟车和停车场景。预测、规划、控制三个不同边界故障都可能造成相似的表面结果，例如危险接近或进度不足。诊断器必须依据合法证据区分责任，不能读取运动程序或注入标签。

**不包含什么。** 不包含感知不确定性、多前车、遮挡、交通灯策略和真实人类驾驶行为。

### 4.2 `cut_in_or_crossing_actor`：邻车切入或横穿 ego 路径

**代表什么。** 一辆最初位于 ego 车道侧方的车辆逐渐向 ego 路径切入或横穿。这个场景检查转向/动作预测、规划器对变化中横向冲突的处理，以及执行层能否实现安全响应。

**初始条件。** 交互车辆生成在 ego 前方 25 米、左侧 3.5 米，朝向与 ego 一致。收到路由 epoch 后开始运动。

**车辆运动程序。** 纵向速度恒为 3 m/s。场景时间 0–3 秒横向速度为 0；3 秒后横向速度以 0.6 m/s² 增长，最高 1.5 m/s，并向 ego 路径移动。语义预测采用相同的运动学程序。

**科学含义。** 相比前车场景，这个场景更依赖预测的朝向和动作形状，但责任仍可能位于预测、规划或控制域。必须保留错误责任域 probe，防止策略仅靠执行所有保守干预取得表面成功。

**不包含什么。** 不包含协商、转向灯、行人、自行车、路口优先权和感知遮挡。

## 5. 三个责任域和六种故障

公开 taxonomy 可以说明故障机制，但盲测期间每个不透明 episode ID 与具体机制之间的映射必须保存在 evaluator-private 区域。

### 5.1 交互预测域 `interaction_forecasting`

`forecast_stale_or_delayed` 表示格式正常但内容大约滞后 2 秒的预测流。运行时维护有状态预测队列并释放旧预测，研究的是时间新鲜度，而不是消息完全丢失。

`forecast_heading_or_maneuver_bias` 将预测轨迹朝向旋转 75 度，并从障碍物当前起点重新构造路径，代表幅度较大但语法合法的朝向或动作判断错误。

### 5.2 运动规划域 `motion_planning`

`planning_constraint_omitted` 将每个规划点强制为至少 10 m/s、加速度至少 1.5 m/s²，代表交互安全约束被遗漏或被严重低估。

`planning_unsafe_cost_or_speed_bias` 将速度变换为 `min(18, 3 × 原速度 + 3)` m/s，并增加 1.5 m/s² 加速度，代表规划目标或代价存在危险偏置，同时保留原轨迹结构。

### 5.3 跟踪与执行域 `tracking_execution`

`control_command_transport_delay` 将控制消息排队 3.5 个仿真秒后再释放，代表传输、调度或执行命令延迟。

`control_gain_saturation_tracking_bias` 将油门变换为 `min(100, 2.5 × 原油门 + 20)`%，完全抑制刹车，并将转向缩放为原值的 0.6、限制在 ±35%，代表增益、饱和与跟踪偏差的组合。

这些机制是为了科学实验而设计的边界扰动，不表示真实世界同类故障只能以这种方式出现。

## 6. 每个 episode 的 7 个配套运行

- `nominal`：相同场景和 seed，不注入故障，用于确认基本场景可运行并提供配对参照。
- `fault_repeat_0..2`：相同故障机制重复 3 次；冻结判据要求至少 2/3 同时满足机制激活和任务失败。
- `probe_interaction_forecasting`：暂时把预测替换为恒速外推。
- `probe_motion_planning`：沿现有路径施加 2.5 秒单调减速的安全包络。
- `probe_tracking_execution`：施加 0% 油门、60% 刹车、0% 转向的有界控制命令。

所有 probe 从场景时间 6 秒开始，持续 10 秒。probe 是确定性的，不读取 GT 故障标签。与故障责任域相同的 probe 是**正确域反事实**，另外两个是必须保留的错误域对照。正确域 probe 并不被预设为一定能修复故障，它必须在冻结 evaluator 中实际显示出修复效果。

## 7. 九个诊断动作

| 动作 ID | 含义 | 类型 |
|---|---|---|
| `O0_failure_summary` | 获取允许公开的聚合失败摘要。 | 观察 |
| `O1_forecast_window` | 查看受限语义预测窗口。 | 观察 |
| `O1_motion_plan_window` | 查看受限运动规划窗口。 | 观察 |
| `O1_tracking_window` | 查看请求与执行层的跟踪证据。 | 观察 |
| `O2_timing_metadata` | 获取允许的时间戳、新鲜度和时延元数据。 | 观察 |
| `O3_semantic_replay` | 在不访问原生 topic 的前提下重放受限语义证据。 | 观察 |
| `I2_F_constant_velocity` | 执行不使用 GT 的恒速预测 probe。 | 干预 |
| `I2_P_safety_envelope` | 执行不使用 GT 的保守规划包络 probe。 | 干预 |
| `I2_C_bounded_brake` | 执行有界刹车 probe。 | 干预 |

只有 central gate 可以真正执行动作。普通 policy 或 LLM 只能提交有类型的 proposal，不能直接读取私有文件或调用运行时工具。每个动作都必须把实际成本、验证后的新增证据、后验更新和 stop decision 追加到 event log。

## 8. 目录结构和字段字典

大文件与私有评测材料不进入 Git：

```text
CAGE_DATA_ROOT/<batch_id>/<episode_id>/
  visible/episode.json
  visible/evidence/*.json
  visible/evidence_index.json
  retained/<opaque_run_id>.json

CAGE_PRIVATE_ORACLE_ROOT/<batch_id>/
  episode_<episode_id>.json
  <opaque_run_id>/scenario.json
  <opaque_run_id>/injector.json
  <opaque_run_id>/run_metrics.json
  <opaque_run_id>/interposer_stats.json
  <opaque_run_id>/scenario_stats.json

CAGE_STATE_ROOT/
  <batch_id>_plan.json
  <batch_id>_execution.json
  evidence/<batch_id>_evaluation.json
```

`visible/episode.json` 是诊断器初始可见的 manifest：

| 字段 | 含义 |
|---|---|
| `episode_id` | 稳定的不透明 ID，不编码标签。 |
| `scenario_template` | 不透明场景模板 ID。 |
| `failure_type` | 可公开的高层失败类型。 |
| `failure_window` | 证据窗口起止时间。 |
| `observable_regime` | 该 episode 允许的最高访问层级。 |
| `allowed_action_ids` | central gate 可以接受的准确动作集合。 |
| `budget_profile` | 冻结的成本、token 和动作预算配置。 |
| `seed` | 公开的确定性 seed。 |
| `stack` | 被测 ADS 栈和主版本。 |
| `initial_evidence_refs` | 指向初始可见证据的引用。 |

`retained/<opaque_run_id>.json` 保存经过 allowlist 的语义轨迹。预测样本包含相对时间、预测末端位移和预测末端速度；规划样本包含相对时间、点数和最大/最小速度；控制样本包含相对时间、油门、刹车、转向和排队目标数。`native_topics_disclosed=false` 和 `oracle_fields_present=false` 是必须成立的安全断言，不是标签。

`retained/` 是生成器和 evaluator 的输入，不属于 policy 的初始诊断视图。evaluator 在 `visible/evidence/` 中生成经过 allowlist 的动作证据；central gate 只在动作被合法执行并计费后暴露对应 payload。公开归档可以列出 retained 文件的校验和，但不能因此改变 benchmark 的访问协议。

private oracle 保存真实场景、责任域、故障机制、配套运行链接、运行指标、source commit 和配置摘要。评估期间目录权限为 root-only，绝不能挂载到诊断进程。未来公开标签时，应在盲测结束后用独立压缩包发布，或者明确规定访问政策。

## 9. Provenance 和复现要求

每个可发布 batch 必须绑定：

- 准确的 CAGE-AD source commit；
- Apollo、CARLA、bridge、地图和主机运行时版本；
- scenario、fault、action、threshold、budget 和 split registry 的 SHA-256；
- 每个可见 manifest 和数据对象的 SHA-256；
- prepare、execute 和 evaluate 命令；
- append-only 的 invalid/retry/failure ledger；
- powered-on hours 和增量存储消耗。

可复现单元是完整的关联 episode，而不是单独一条轨迹。发布 manifest 要保留 nominal/fault/probe 的逻辑关系，但不能让这种关系向 policy 泄露答案。

batch 运行状态为 `PASS` 后，`scripts/d0/build_public_manifest.py` 会只使用 `CAGE_DATA_ROOT`、恢复 checkpoint 和本仓库生成确定性、内容寻址的公开索引。接口故意不接受 private-oracle root；它会拒绝未完成 batch、缺失 companion、符号链接和公开 JSON 中的 evaluator-only 字段。

## 10. 公开发布前必须通过的检查

1. 所有必要运行都有 metrics、semantic capture、scenario stats 和 interposer stats；
2. 每个故障在冻结判据下稳定激活；
3. nominal 运行满足冻结 envelope；
4. 正确域和错误域 probe 都存在并经过评估；
5. 重复运行满足声明的语义校验和或数值容差；
6. forbidden key/path、oracle token、secret 和 native-topic 扫描均无泄漏；
7. clean-shell replay 可以复现聚合结果；
8. 每个文件都有字节数、媒体类型和 SHA-256；
9. 由人工维护者检查依赖许可和再分发权利；
10. 无效和失败尝试保留记录，不得静默删除。

当前 v3 没有通过第 2 和第 4 项，因此不能作为正式公开 benchmark。

## 11. 隐私、伦理和安全

当前数据完全来自仿真，预期不包含真实人员、生物特征、个人身份信息或公开道路录像。但这不等于安全认证。所有干预只是仿真中的有界研究 probe，不能用于证明真实车辆上的自动修复或自动干预是安全的。

## 12. 许可证与再分发

当前尚未选择数据集许可证，仓库也没有许可证授权。因此在维护者添加明确的代码许可证和数据许可证前，不能把 pilot 或仓库称为“已经开源”。

Apollo、CARLA、地图、bridge、车辆模型等第三方材料继续受其各自许可证约束。除非人工检查确认允许再分发，否则 source-only 仓库和未来语义数据包不得包含第三方二进制、地图、原始 record 或资产；不能再分发时应提供校验和与获取说明。

## 13. 当前 D0-A0 的已知限制

- 只有两个确定性交通场景和一个 seed；
- 完美感知排除了感知和跟踪不确定性；
- 只有一条 Town01 直线路径；
- 边界扰动是较强的工程 probe；
- 12 个 episode 只能支持 pilot 描述，不能夸大统计显著性；
- companion 共享语义 parent，不是独立样本；
- v3 只有 2/12 通过完整科学 gate；
- 33/36 次虽出现机制信号，但只有 16/36 次同时造成任务失败；
- 只有 2/12 个正确域 probe 修复失败，其中一个还出现错误域 false repair；
- 即使 smoke 通过，也只能验证生成器，不能证明现实世界外部有效性。

## 14. 未来引用与联系信息

真正公开发布时必须补充版本化 DOI 或归档 URL、作者、维护者联系方式、发布日期、许可证标识和 citation 文件。在这些信息存在前，只能引用准确 Git commit 和 batch manifest SHA，不能引用未版本化的数据集名称。

## 15. 版本历史原则

每次公开修订必须写明新增或删除的语义组、生成器代码变化、失效的校验和以及与旧 split 的兼容性。失败的工程 batch 继续保留在 private/state provenance ledger 中，并在 release notes 中汇总；不得通过重新标注或删除失败样本来改善结果。
