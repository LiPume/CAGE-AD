# Apollo 10 多场景 TTC 为空：根因诊断 Prompt

把下面整段粘贴给 AutoDL 服务器上当前执行 Apollo D0 protocol v1 的 Codex。它是一次暂停后的根因诊断任务，不授权继续 CAL-F04、后续 recipe、故障剂量、probe 或 formal generation。

```text
你是 CAGE-AD Apollo 10 protocol v1 的根因诊断 Codex。当前批量校准已经由用户明确暂停。你的唯一目标是用最少的隔离实验回答：连续多个名义场景的 minimum TTC 为 null，究竟是因为车辆没有形成真实几何冲突，还是 actor 身份、坐标、运动、Apollo 执行或 TTC evaluator 出错。

这是一个持续执行任务：在预算和安全边界内自行完成只读审计、最小诊断实现、离线测试、最多 4 次隔离重放、证据分析和报告，直到根因能够归入下面定义的一类，或明确列出仍缺少的唯一证据。不要在中间等待一般性确认；只有需要扩大预算、修改冻结协议、使用 formal seeds、破坏旧数据或发生外部凭据问题时才暂停请求用户。

本任务采用“科研边界固定、工程路径可调整”的原则：不得改变的问题、数据隔离、预算、最低证据和停止条件是硬约束；具体文件拆分、代码复用方式、Apollo 等价 topic/字段、可视化实现和额外的低成本 sanity check 可以根据实际环境调整。任何偏离推荐步骤的调整必须先写入 `$CAGE_TTC_DIAG_ROOT/ADAPTATION_LOG.md`，包括触发证据、原方案为何不可行、新方案、是否改变数据或结论；不得以“更容易得到有限 TTC”为调整理由。

零、不要重新猜问题：下面是已经从源码确认的事实与必须逐项验证的根因候选

已确认源码事实：

1. `run_runtime.py::_actor_box()` 从 CARLA transform、bounding-box local offset/yaw、extent 和当前世界速度构造 OBB；`oriented_box_ttc()` 把双方当前 OBB 以当前恒定线速度外推 10 秒、每 0.05 秒检查一次重叠。
2. `run_runtime.py` 每 tick 确实调用 TTC，但现有 `samples` 只保存 ego x/y、双方 speed 标量、center separation 和 TTC；没有保存 interaction actor x/y、双方 yaw、速度分量、OBB local transform/extent。因此旧 trace 本身不能独立复算 TTC。
3. 当前 infrastructure gate 只要求进程健康、route accepted、actor spawned、clock advanced、planning/control 消息数量和无异常；没有要求 ego 达到最低速度/进度，也没有要求 interaction actor 实际轨迹符合 YAML。自车 32 秒只走 6 米仍会被判 infrastructure valid。
4. `scenario_runtime.py` 在 route response 之前冻结 NPC；一收到 route response 就立即执行 NPC 的 brake/cut-in 运动程序。代码没有等待 ego 达到巡航速度，也没有以 ego 到达某个空间点作为冲突触发条件。
5. lead-brake 的 NPC 在 ego 仍可能处于起步阶段时已经向前行驶并制动。例如 LBM0 从 35 m 前方出发，前 7 秒以 6 m/s 行驶，再以 2.5 m/s² 停车；它在停车前又前进约 `6*7 + 6²/(2*2.5) = 49.2 m`，最终约在初始 ego 前方 84.2 m。若 ego 只前进约 7 m，不可能形成追尾 TTC。
6. cut-in 的实现只让 lateral speed 从 0 加速到上限，没有在进入目标车道后减速或停止横移。以 CIE0 为例，actor 从 lateral offset -3.5 m 开始，约在 cut-in 后 3.42 秒穿过 ego 车道中心，此后仍以最高 1.5 m/s 横向移动，32 秒内会继续穿过多个车道。这是明确的场景运动定义缺口，不得忽略。
7. nominal gate 使用的是“实际闭环当前速度 TTC”。如果 Apollo 提前安全制动并把相对闭合速度降为 0，TTC 会成为 null；这不一定表示场景没有安全相关交互，也可能表示准入指标把“成功提前避险”误当成“无交互”。必须同时检查 Apollo planned trajectory 与 actor future path 的时空冲突，不能只看当前速度 TTC。

必须优先检验以下四个具体假设：

- H1：NPC 在 ego 起步前就完成制动/穿越，二者从未在时空上接近，属于 scenario trigger/design failure。
- H2：Apollo 因看到 obstacle 1001 而主动停车，实际速度 TTC 因成功避险变成 null，属于 nominal admission metric/design failure。
- H3：Apollo planning/control 明确要求前进，但 bridge/gear/brake/同步执行使 ego 没有移动，属于 ego runtime bug，现有 infrastructure gate 漏检。
- H4：真实几何已经闭合，但 actor identity、OBB 坐标/朝向或 TTC 数值实现返回 null，属于 evaluator bug。

如果运行证据出现 H1–H4 无法解释的新现象，可以增加一个 H5，但必须在 `ADAPTATION_LOG.md` 中写出支持它的直接证据、能区分它与 H1–H4 的最小检查、增加的运行成本；不得进行无边界的系统排查。

一、硬性停止线

1. 不继续当前 CAL-F04，不开始 CAL-P01/CAL-C01 等任何后续 recipe，不调用会推进 calibration search state 的命令。
2. 不运行 fault dose、probe、Agent、baseline、formal seeds 或 Autoware；不生成可计入数据集的新样本。
3. 不修改 protocol v1 的 YAML、门槛、候选、32 秒 observation window、旧 decision、旧 ledger、旧 RUN_STATE 或已有 visible/private 数据；不把 rejected 改成 invalid/identifiable。
4. 不删除、覆盖、移动已有运行。旧结论保持为“按当时冻结实现得到的结果”，是否需要 supersede 只能在报告中提出，不自动执行。
5. 所有新 replay 都必须标记 `DIAGNOSTIC_ONLY_NOT_DATASET`，使用 calibration seed 1101；禁止读取 formal seeds。
6. 新增运行上限：最多 4 次 replay、1.5 powered-on hours、5 GiB 持久盘增量。预计超限时先停机、保存证据并报告，不得静默扩展。

二、同步、现状冻结与隔离目录

1. 固定路径，不要搜索或另建副本：

   REPO_ROOT=/root/autodl_apollo10_g0_bundle/project/CAGE-AD
   CAGE_BUNDLE_ROOT=/root/autodl_apollo10_g0_bundle
   CAGE_RUNTIME_ROOT=/root/autodl_apollo10_g0_bundle/runtime
   CAGE_PYTHON=/root/autodl_apollo10_g0_bundle/runtime/envs/cage-ad-py310/bin/python
   CAGE_STATE_ROOT=/root/autodl_apollo10_g0_bundle/runtime_state/d0_protocol_v1
   CAGE_DATA_ROOT=/root/autodl-tmp/cage_ad_data
   CAGE_PRIVATE_ORACLE_ROOT=/root/autodl-tmp/cage_ad_private_oracle

2. 在 `$REPO_ROOT` 依次执行并把输出写进诊断目录的 `precheck.txt`：

   pwd
   git remote get-url origin
   git branch --show-current
   git rev-parse HEAD
   git status --short
   git log -5 --oneline
   ps -eo pid,ppid,pgid,etimes,args | grep -E 'CarlaUE4|mainboard|scenario_runtime|interposer_runtime|run_runtime|calibrate_recipe|run_calibration_once' | grep -v grep || true

   确认 origin 精确为 `git@github.com:LiPume/CAGE-AD.git`。不得输出 SSH key、token 或环境中的秘密。
3. fetch `main` 与 `codex/apollo-d0-protocol-v1`。先用 `git diff`、`git status` 和 runtime state 记录尚未完成的 CAL-F04；不调用 completion 脚本，不伪造 attempt_finished。若 Git 工作树干净，则从当前服务器提交创建 `codex/apollo-d0-ttc-null-diagnosis`；若不干净，先把 diff 和文件清单写入诊断目录，再只提交确属服务器已完成工作的内容。不得 reset、stash、checkout 覆盖用户修改。
4. 确认没有 `CarlaUE4`、Apollo mainboard、scenario/interposer/run runtime 或 calibration 进程；若仍有则优雅停止并验证停机，不得继续已有 attempt。
5. 使用现有 runtime，不重装 Apollo/CARLA/Conda。设置：

   CAGE_TTC_DIAG_ROOT=/root/autodl_apollo10_g0_bundle/runtime_state/diagnostics/ttc_null_<UTC时间>
   CAGE_TTC_DIAG_DATA=/root/autodl-tmp/cage_ad_diagnostics/ttc_null_<UTC时间>

6. `$CAGE_TTC_DIAG_ROOT` 和 `$CAGE_TTC_DIAG_DATA` 必须与 calibration ledger/data 完全隔离。诊断脚本启动时 fail closed：若目标路径落入 `$CAGE_STATE_ROOT/calibration`、原 ledger 或正式数据目录，立即退出。

三、先做只读离线审计，不启动仿真

完整读取 protocol v1 的 scenario/episode/quality YAML、CAL-F01/F02/F03 报告、未完成 CAL-F04 的现有状态，以及以下代码：

- `src/cage_ad/adapters/apollo_d0/scenario_runtime.py`
- `src/cage_ad/adapters/apollo_d0/run_runtime.py`
- `src/cage_ad/protocol_v1/evaluator.py`
- `src/cage_ad/protocol_v1/calibration.py`
- `src/cage_ad/protocol_v1/orchestrator.py`
- `scripts/d0/protocol_v1/run_calibration_once.sh`
- 当前 ledger、private metrics、scenario/interposer stats 和日志。

生成 `$CAGE_TTC_DIAG_ROOT/OFFLINE_AUDIT.md` 和机器可读 JSON，至少回答：

1. 每个已运行 nominal attempt 的 recipe/candidate/seed、simulation seconds、frame 数、route epoch、ego forward progress、ego speed 的 min/median/max、center separation 的 min/start/end、TTC 是否全程 null。
2. 各 attempt 是否唯一找到一个 `ego_vehicle` 和一个 `cage_interaction_actor`；旧产物无法回答时明确写 `not recorded`，不得猜测。
3. actor 是否在 route epoch 前冻结；route epoch 后实际速度和位移是否达到 YAML 的解析运动程序；旧产物不能验证时列入 replay 必采字段。
4. Apollo 是否只是“有 planning/control 消息”，还是确实输出了非零目标速度并被 CARLA ego 执行；检查 localization、planning、control、chassis/bridge 日志中可获得的速度、档位、刹车、油门和交通灯/stop decision。
5. 32 秒窗口是完整仿真 32 秒还是 wall-time 提前结束；是否有 frame gap、时间基准错位或 route epoch 与 evaluator start 不一致。
6. 把连续失败分成两层：`measurement cannot establish TTC` 与 `scenario never establishes interaction`。当前证据不足时不得提前选其中之一。

离线审计必须生成一张每行一个 attempt 的 CSV，列名固定为：

`attempt_id,recipe_id,candidate_id,seed,status,sim_seconds,frame_count,route_epoch_sim,planning_messages,guarded_control_messages,forward_progress_m,ego_speed_min_mps,ego_speed_median_mps,ego_speed_max_mps,separation_start_m,separation_min_m,separation_end_m,finite_ttc_tick_count,minimum_ttc_s,collision_count,missing_fields`

校验：CSV 行数必须等于 ledger 中 `attempt_finished` 且 stage=nominal 的 attempt 数；每个数值都要指向原始 private metrics 路径。不能从公开摘要反推私有映射。

四、推荐实现结构与允许调整的范围

优先使用以下诊断文件结构；如果仓库现有抽象使其他拆分明显更安全，可以调整文件名或合并脚本，但在根因被证实前不得修改生产 evaluator/scenario/calibration，也不得把诊断逻辑混入正式生成路径：

1. `src/cage_ad/diagnostics/__init__.py`
2. `src/cage_ad/diagnostics/ttc_null.py`
3. `src/cage_ad/adapters/apollo_d0/ttc_diagnostic_runtime.py`
4. `scripts/d0/diagnostics/offline_ttc_audit.py`
5. `scripts/d0/diagnostics/run_ttc_diagnostic_once.sh`
6. `scripts/d0/diagnostics/analyze_ttc_diagnostic.py`
7. `scripts/d0/diagnostics/render_ttc_diagnostic.py`
8. `tests/d0/test_ttc_null_diagnostic.py`

诊断模块必须提供以下等价、可单测的能力；函数名可以遵循现有代码风格调整，但不得把核心计算只藏在 shell、notebook 或一次性命令中：

- `world_obb_from_carla_state(state) -> DiagnosticOBB`
- `sat_separation_m(left, right) -> float`
- `fine_step_ttc(left, right, horizon_s=10.0, step_s=0.01) -> float | None`
- `closest_approach(left, right, horizon_s=10.0, step_s=0.01) -> {time_s,separation_m}`
- `relative_state_in_ego_frame(ego, actor) -> {forward_m,right_m,closing_mps}`
- `classify_tick_disagreement(production_ttc, independent_ttc, tolerance_s=0.10)`
- `summarize_trace(trace_path) -> dict`
- `classify_root_cause(summary) -> enum`

诊断 trace 每行必须通过本文件中的 schema/dataclass 验证；缺字段不能静默丢弃。`null` 必须配套 `<field>_missing_reason`。

五、先验证 TTC 算法，再运行 Apollo

1. 为 `oriented_box_ttc` 增加独立、可人工验算的 golden tests：
   - 同车道后车追前车，已知间距和相对速度，TTC 应为已知有限值；
   - 同速同向，TTC 应为 null；
   - 垂直交叉且到达时间相同，TTC 应有限；
   - 轨迹交叉但到达时间不同，TTC 应为 null；
   - 已重叠返回 0，但 run minimum-positive 的处理要被单独验证；
   - CARLA actor bounding-box local offset、actor yaw 与 box yaw 均非零的情况。
2. 实现一个仅用于诊断的第二计算器：使用逐 tick 完整 OBB 状态，计算 10 秒内 predicted closest approach time、minimum OBB/多边形 separation，并用固定 0.01 秒步长独立复核当前 0.05 秒 TTC。第二计算器不得 import 或调用 `oriented_box_ttc()`/`oriented_boxes_overlap()`，避免同源错误。
3. 对 protocol YAML 中 LBC0、LBM0、CIE0、CIL0 做纯解析 sanity check，ego 恒速固定取 `[0, 2, 4, 6, 8, 10]` m/s，从 route epoch 起算 60 秒。输出每个速度下：首次进入 ego lane/冲突区时间、最小 separation、首次 finite TTC、是否进入 `(2.5,6.0]`。同时输出：
   - 每个 lead candidate 的 NPC braking distance 和最终相对初始 ego 的位置；
   - 每个 cut-in candidate 穿过 ego lane center 的时间、32 秒时 lateral displacement；
   - 明确验证 cut-in lateral velocity 是否在穿过目标车道后仍非零。
   它只是诊断，不得作为数据或直接改候选依据。
4. CPU tests 未通过前禁止启动 CARLA。提交一次只含诊断代码/测试的 checkpoint；不要提交运行数据。

六、最小隔离重放：核心对照固定，后续步骤受控自适应

R1/R2 是必须完成的核心对照；R3/R4 根据已获得证据选择，但不得突破 4 次上限：

1. R1：精确重放 `CAL-F02/LBM0/seed 1101`，32 秒，nominal、no fault、no probe。
2. R2：精确重放 `CAL-F03/CIE0/seed 1101`，32 秒，nominal、no fault、no probe。
3. 完成 R1/R2 分析后优先二选一：
   - 若任一 tick 出现 production TTC=null 但 independent TTC 有限，运行 R3=`KNOWN_COLLISION_TTC_SANITY`：不启动 Apollo，用两个 CARLA actor 构造同车道已知闭合速度，验证 production 与 independent TTC；
   - 否则运行 R3=`LBM0_EXTENDED_60S`：精确复用 R1，唯一变化是 diagnostic runner 观察到 60 秒，用来判断冲突只是晚于 32 秒还是永不形成。
4. R4 只在以下任一情况运行：R1/R2 instrumentation 缺失关键字段；lead 与 cut-in 得到互相冲突的分类；R3 仍不能在 H1–H4 中分类。优先使用 `CIE0_EXTENDED_60S`。如果它不能区分当前剩余假设，可以换成一个更有区分力但成本不更高的 replay；必须先在 `ADAPTATION_LOG.md` 写明剩余两个假设、预期观测及不同结果分别支持哪个假设。不得用 R4 调 gap、NPC 速度或切入时机来追求 TTC。

R1–R4 使用新的 diagnostic run ID 和隔离目录；不得调用 `calibrate_recipe.py --execute`，不得写原 calibration ledger。每次启动前写 `planned.json`，结束后写 `finished.json`；中断只恢复 diagnostic run，不得触碰 calibration attempt。

每个 0.05 秒 tick 必须在 private diagnostic trace 保存：

- frame、sim time、wall time、route epoch elapsed；
- ego 与 interaction actor 的 CARLA actor ID、role_name、type、位置 x/y/z、yaw、bounding-box local location/yaw/extent；
- 双方速度 x/y、speed、acceleration、实际逐帧位移；
- interaction actor 的 intended longitudinal/lateral velocity 与实际世界速度、spawn basis、route epoch 前后状态；
- actor 相对 ego 的 forward/right 投影距离、center distance、相对闭合速度；
- 当前 evaluator TTC、独立 TTC/closest-approach time、预测最小 OBB separation；
- ego 的 localization speed、chassis speed/gear、planning target speed/stop reason、control throttle/brake/steer，以及这些消息是否被 bridge 执行；取不到的字段必须写 null 和原因；
- CARLA road/lane/waypoint ID、lane type、traffic-light state，以及双方是否位于预期道路/冲突路径。

此外必须保存 6 个事件时刻，找不到则为 null 并写原因：

1. `route_epoch_s`；
2. `ego_first_speed_above_0_5_mps_s`；
3. `ego_first_speed_above_2_0_mps_s`；
4. `actor_conflict_program_start_s`（brake_start/cut_in_start）；
5. `actor_crosses_ego_lane_center_s` 或 `actor_stops_s`；
6. `minimum_geometric_separation_s`。

必须检查以下 Apollo 链路，不得只采 CARLA speed；若 Apollo 10 的实际 topic 或 protobuf 字段不同，允许使用语义等价来源：

- `/apollo/localization/pose`：linear_velocity、position、heading；
- `/apollo/canbus/chassis`：speed_mps、gear_location、driving_mode、throttle_percentage、brake_percentage；
- `/apollo/planning`：前 3 秒 trajectory points 的 v/a、最近 stop point、decision reason/obstacle id（字段存在时）；
- `/apollo/control_guarded`：throttle、brake、steering_target、gear_location；
- bridge 实际订阅的 control topic 与 bridge log；确认不是 control 命令存在但订阅错 topic。

不要假设 protobuf 字段名。先用 Apollo 10 本地 `.proto`/生成类确认字段，保存字段映射到 `apollo_field_map.json`；字段不存在才记 null。

每次 replay 生成：

- `trace.jsonl`、`summary.json`、完整命令、source/config hashes；
- ego/actor XY 轨迹图；
- center/OBB separation、双方速度、闭合速度、TTC 随时间曲线；
- 1280×720 的 top-down 或固定侧视 MP4，画面显示双方 actor、轨迹、route epoch、速度、距离、TTC/CPA 和 `DIAGNOSTIC ONLY — NOT DATASET`。视频只用于定位问题，不需要制作最终 showcase。

先验证 MP4 可解码、trace 行数与仿真帧数一致、hash 已记录，再清理临时帧。视频和 trace 不进 Git。

七、预注册诊断判据与可调整边界

先计算这些 summary 字段：

- `unique_ego_actor_ids`、`unique_interaction_actor_ids`；
- `trace_frames`、`sim_duration_s`、`non_unit_frame_gaps`；
- `ego_progress_m`、`ego_speed_median/max`；
- `planning_target_speed_median_first_10s`、`control_throttle_fraction`、`control_brake_fraction`；
- `actor_spawn_offset_error_m`、`actor_velocity_rmse_mps`、`actor_conflict_timing_error_s`；
- `min_center_distance_m`、`min_obb_separation_m`、`positive_closing_duration_s`；
- `production_finite_ttc_ticks`、`independent_finite_ttc_ticks`、`finite_null_disagreement_ticks`；
- `planned_path_conflict`、`planned_path_min_separation_m`、`planned_path_conflict_time_s`；
- 上一节定义的 6 个事件时刻。

以下数值是开始查看 R1/R2 结果前声明的诊断判据，用来避免事后凭感觉归因。若实际采样噪声、Apollo 字段语义或 CARLA 物理误差证明某个数值不适用，可以调整一次，但必须在看对应分类结果前用 synthetic test 或上游文档给出依据，在 `ADAPTATION_LOG.md` 保存 old/new value、理由和影响；身份唯一性、有限/null 不一致、数据隔离和“不调场景追 TTC”不可调整。

1. identity 正常：全程恰好 1 个 ego ID 和 1 个 interaction ID，且 ID 不变。否则直接归 A。
2. clock 正常：32 秒 replay 至少 620 个有效 tick、sim duration 位于 `[31.9,32.2]`、non-unit gaps=0；60 秒 replay 至少 1180 个 tick、duration 位于 `[59.9,60.2]`。否则先归 B/runtime timing。
3. actor spawn 正常：spawn offset error ≤0.50 m、yaw error ≤2°；actor execution 正常：conflict timing error ≤0.10 s，除瞬时启动外 intended 与 actual velocity RMSE ≤0.50 m/s。任一超限归 C。
4. evaluator 一致：当 independent TTC 有限时，production 必须有限且绝对差 ≤0.10 s；任何稳定的 finite/null mismatch（连续 ≥3 ticks）归 A。
5. ego execution bug：在连续 ≥5 秒内 planning trajectory 的 1 秒后目标速度中位数 ≥1.0 m/s，且 control brake <5%、throttle >10%，但 CARLA ego speed 中位数 <0.30 m/s；或 control topic/gear/bridge 明确不一致。满足则归 B。
6. Apollo 主动安全停车：planning target speed <0.30 m/s 或 brake >10% 持续 ≥2 秒，并且 stop reason/trajectory 与 obstacle 1001 或其冲突路径相符。这不是 B；继续检查 planned-path conflict，并优先归 D 的 admission metric failure。
7. trigger 过早：`actor_conflict_program_start_s < ego_first_speed_above_2_0_mps_s`，且 actor 在 ego 达到 2 m/s 前已经停止或穿过 ego lane center；同时 actor/evaluator 正常。归 D 的 trigger/scenario design failure。
8. cut-in 无终点：actor 穿过 ego lane center 后 lateral speed 仍 >0.30 m/s 持续 ≥1 秒，且与 YAML/代码一致。归 D；这是 v1 定义问题，不得作为 runtime bug 修补。
9. TTC gate 与安全规划错位：production current-velocity TTC 全程 null，但 Apollo planned path 与 actor future path 曾预测 min separation <1.0 m；随后 Apollo 制动/停车使实际路径安全。归 D 的 admission metric failure。
10. 若 R1/R2 在 32 秒无交互而同配置 60 秒进入 finite TTC，只能结论为 v1 observation window/design failure；不得把 60 秒结果回填 v1。

八、按证据归因，禁止含糊总结

必须把根因归入以下一类；允许“主因 + 次因”，但每项都要有逐帧证据：

A. `TTC_EVALUATOR_OR_IDENTITY_BUG`
实际几何正在闭合，独立计算得到有限 TTC，但现 evaluator 始终 null；或选错 actor、OBB 坐标/朝向/速度转换错误。

B. `EGO_EXECUTION_OR_RUNTIME_BUG`
Apollo 规划/控制本应前进但 ego 没执行，或档位、制动、bridge、同步时钟、route epoch 导致自车异常慢；现有 infrastructure gate 把它误当成有效运行。

C. `INTERACTION_ACTOR_EXECUTION_BUG`
NPC 的实际出生位置、方向、速度、制动/切入时序与 YAML 候选不一致，导致场景没有按声明执行。

D. `PROTOCOL_SCENARIO_OR_ADMISSION_DESIGN_FAILURE`
ego、NPC 和 evaluator 均按声明工作，但冲突触发早于 ego 起步、cut-in 没有目标车道停止条件、冻结候选/道路/32 秒窗口不能形成交互，或 actual-current-velocity TTC 把 Apollo 成功提前避险判成无交互。

E. `INSUFFICIENT_EVIDENCE`
只有在已执行上述最小检查后仍无法区分时使用，并写出唯一缺失证据和取得它所需的一次最小实验；不得用“可能有很多原因”结束。

处置边界：

- A/B/C：提出最小实现修复、回归测试、受影响 attempt 范围和完整重跑成本；可以在诊断分支实现并测试修复，但不得恢复批量校准，等待用户审查。
- D：不得修改 v1。创建 `PROTOCOL_V2_CHANGE_PROPOSAL.md`，给出新候选/窗口如何通过独立 pilot 预注册、会使哪些结论失效、预计运行数；不得直接运行 v2。
- 如果 B 说明 infrastructure gate 不充分，同时报告旧 F01–F04 为“门控实现可能误判”，但不覆盖旧记录。

九、最终交付与停止条件

在 Git 中提交并推送以下小型、无私有标签泄漏的产物到 `codex/apollo-d0-ttc-null-diagnosis`：

- 诊断脚本与单元测试；
- `artifacts/d0/diagnostics/TTC_NULL_ROOT_CAUSE_REPORT.md`；
- `artifacts/d0/diagnostics/TTC_NULL_ROOT_CAUSE_REPORT.json`；
- `artifacts/d0/diagnostics/TTC_DIAGNOSTIC_MANIFEST.example.json` 或去标识的小型 manifest；
- 若适用，最小修复及其测试，或 `PROTOCOL_V2_CHANGE_PROPOSAL.md`，二者不要混为一谈。

报告必须用中文，结论先行，并包括：

1. 最终根因分类与置信度；
2. 3–5 条最关键的逐帧证据；
3. 为什么当前 TTC 为 null；
4. 已有 F01–F04 数据还能做什么、不能做什么；
5. 是实现 bug 还是协议设计失败；
6. 最小修复/最小 v2 改动；
7. 修复后必须重跑哪些 runs，预计小时和空间；
8. 可以和不可以宣称的结论；
9. 诊断图和视频在持久盘的绝对路径；
10. 明确写 `CALIBRATION_REMAINS_PAUSED`。

报告必须包含四张固定表，不能用散文替代：

- 表 1：F01–F04 每个 candidate 的 runs、progress、separation、finite TTC 统计；
- 表 2：R1–R4 的 6 个事件时刻；
- 表 3：production TTC、independent TTC、planned-path conflict 三者对照；
- 表 4：H1–H4 的证据、反证、结论和对应处置。

报告首页第一段必须使用下面模板填值，不能换成模糊语言：

`结论：主要根因是 <A/B/C/D/E + 名称>，置信度 <高/中/低>。现有 TTC 为 null 的直接原因是 <一句可观察事实>。旧 F01–F04 <是否需要重跑>；protocol v1 <可以继续/必须修实现后重跑/必须停止并提出 v2>。校准仍暂停。`

运行固定验证命令：

1. `$CAGE_PYTHON -m pytest -q`
2. `$CAGE_PYTHON -m compileall -q src scripts tests`
3. `bash -n scripts/d0/diagnostics/run_ttc_diagnostic_once.sh`
4. `shellcheck scripts/d0/diagnostics/run_ttc_diagnostic_once.sh`
5. `$CAGE_PYTHON tools/source_audit.py`
6. 现有 protocol v1 storage isolation、repository secret/large-file audit、diagnosis-visible leakage scan；报告实际扫描文件数。
7. 对每个 trace 验证 `line_count == summary.trace_frames`；对每个 MP4 用 `ffprobe` 验证 codec、width、height、duration；对全部诊断产物记录 SHA-256。
8. `git diff --check`、`git status --short`，确认没有 MP4/trace/private config 被 staged。

关闭所有 Apollo/CARLA/诊断进程，确认没有 pending diagnostic attempt 后再提交推送。推荐拆成 `test(d0): add isolated TTC null diagnostics` 与 `docs(d0): report TTC null root cause` 两个 commit；如果实际改动很小可以合并，但诊断实现、报告和可能的生产修复必须在 diff 中清楚分开。若有实现修复，使用独立 `fix(d0): <具体根因>` commit，不得把协议修改伪装成 fix。

最终停在这里：不自动继续 CAL-F04 或后续 recipe。向用户只汇报根因、证据、修复建议、Git commit、诊断视频路径和“是否值得继续 v1”；等待用户作出恢复、修实现后重跑、创建 v2 或停止项目的决定。

现在开始：先做进程停机核验和只读离线审计，不启动 CARLA。
```
