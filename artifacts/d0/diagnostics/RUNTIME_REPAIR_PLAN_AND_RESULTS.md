# Apollo 10 D0 运行链修复计划与结果记录

状态：**修复前计划已冻结；尚未实施修复**

用途：本文件先记录发现的问题、拟议改动、预期结果和成功判据。开始修改 bridge/Apollo 后，事前部分不得改成迎合结果；实际命令、结果、偏差和结论只追加到“测试后结果”。

基线源码：`66198e79792a6f4598f7b84100042ea3c69efe89`（最后一次有效 replay 所绑定提交）

基线诊断状态：`/root/autodl_apollo10_g0_bundle/runtime_state/diagnostics/ttc_null_20260807T074356Z`

## 一、修复前已经确认的问题

### P1：chassis gear 反馈缺失

- 直接证据：有效 60 秒 trace 的 1200/1200 帧中，`/apollo/control_guarded` 要求 `GEAR_DRIVE=1`，`/apollo/canbus/chassis` 回报 `GEAR_NEUTRAL=0`。
- 源码证据：bridge `carla_bridge/actor/ego_vehicle.py::send_vehicle_msgs()` 设置 speed、throttle、brake、steering、parking brake 和 driving mode，但没有设置 `vehicle_chassis.gear_location`。
- 影响：Apollo 收到的档位反馈与控制请求不一致；旧 infrastructure gate 只计消息数量，无法发现该问题。

### P2：Apollo lane-follow 配置缺失并反复 fallback

- 直接证据：诊断 stack log 重复出现 `modules/planning/scenarios/lane_follow/conf/lane_follow_stage/*.pb.txt is not found`、path optimizer failure、empty path 和 planning fallback。
- 环境证据：Apollo 10 安装包实际提供 `modules/planning/tasks/*/conf/default_conf.pb.txt` 和 lane-follow `pipeline.pb.txt`，但日志请求的是另一套 stage-local 文件名。
- 影响：planning 虽偶尔发布 trajectory，但目标速度低且反复重规划/停车，不能把“有 planning 消息”视作正常规划。

### P3：实际执行跟踪异常，但旧 gate 不检查

- 直接证据：有效 60 秒中 control 93.25% 时间给油，自车速度中位数仅 0.082 m/s、最大 0.821 m/s，60 秒只前进 10.528 m。
- 影响：旧 F01–F04 被记为 infrastructure valid，却不具备生成交互场景的基本运动条件。

### P4：cut-in actor 未按 recipe 执行

- 直接证据：CIE0 actor velocity RMSE 2.576 m/s，未穿过 ego lane center；解析 recipe 则预期约 6.6 秒穿过。
- 影响：即使 ego 修好，现有 cut-in parent 仍不能直接进入数据生成。

### P5：v1 触发与准入设计不充分

- 直接证据：LBM0 在 route epoch 后 7 秒开始制动、9.3 秒停止，而 ego 从未达到 2 m/s；延长到 60 秒仍无有限 TTC。
- 影响：这是 protocol v2 问题，不得伪装成 bridge 小修复，也不得修改旧 v1 YAML 后覆盖历史结果。

## 二、拟实施的修复

修复分层进行，前一层未通过不得进入后一层。

### R1：bridge chassis 状态修复

1. 根据 CARLA `VehicleControl.reverse`、hand brake 和最近一次合法 control gear 显式填充 chassis gear。
2. 正向行驶回报 `GEAR_DRIVE`，倒车回报 `GEAR_REVERSE`，停车制动状态按 Apollo 语义处理；禁止依赖 protobuf 默认值。
3. 增加纯 CPU 映射测试以及 control request—chassis feedback—CARLA reverse 一致性检查。
4. 将实际 bridge 改动保存为 source-only textual patch/provenance，不提交 runtime 或二进制。

### R2：Apollo 10 planning 配置修复

1. 先确认 `APOLLO_CONF_PATH` 和 Apollo 10 `pipeline.pb.txt` 的任务名/默认配置解析规则。
2. 让 lane-follow task 使用安装包中真实存在的 Apollo 10 配置；不复制旧 Apollo 9 配置，不屏蔽错误日志，不降低规划/安全门槛。
3. 增加启动前配置存在性检查；任何 pipeline 引用缺失都 fail closed。

### R3：execution gate

1. 新增无 NPC 跟踪 smoke，逐帧采 planning target、control、chassis、CARLA actual。
2. gate 不再只看消息数；必须检查 gear 一致、规划有效覆盖率、实际速度/进度和控制跟踪。
3. gate 失败立即停止，不启动 scenario calibration。

### R4：protocol v2 scenario

1. NPC 保持冻结，直到 ego 稳定巡航并到达预注册空间锚点。
2. cut-in 使用“进入—减速—目标车道保持”的完整横向速度剖面，并检查实际轨迹 RMSE/终端位置。
3. 使用新状态目录、bundle SHA 和 run ID；旧 v1 ledger/YAML/data 只读。

## 三、修复前冻结的预期结果与成功判据

### Stage A：CPU/静态检查

| 指标 | 预期/通过标准 |
|---|---|
| 全量 CPU tests | 100% 通过 |
| bridge gear 映射 tests | drive/reverse/parking/transition 全覆盖 |
| planning config preflight | pipeline 引用的配置 100% 存在 |
| source/secret/large-file/leakage audit | 全部 PASS；runtime/private/video 不进 Git |

### Stage B：无 NPC execution smoke

最多运行 3 次；任何一次出现同类确定性配置缺失，先停止修复，不重复烧预算。

| 指标 | 预期/通过标准 |
|---|---|
| 时钟 | 20 Hz；无 frame gap；有效窗口达到预注册时长 |
| gear | control 请求 drive 时，chassis drive；允许至多 3 个启动转换帧 |
| planning | 不出现 lane-follow config missing；有效 trajectory 覆盖率 ≥95% |
| control topic | bridge 明确订阅 `/apollo/control_guarded` |
| 跟踪 | 在 planning target ≥1.0 m/s 的连续 5 秒窗口，CARLA actual 中位速度不低于 target 中位数的 70% |
| 进度 | 不再出现“持续给油但 20 秒进度不足 10 m” |

Stage B 需 3/3 通过才称“运行链修复成功”。若只有 gear 一致而速度跟踪仍失败，只能称“gear 修复成功、运行链修复失败”。

### Stage C：fail-fast nominal pilot

| 指标 | 预期/通过标准 |
|---|---|
| actor execution | spawn ≤0.50 m、yaw ≤2°、timing ≤0.10 s、velocity RMSE ≤0.50 m/s |
| TTC evaluator | production 与 independent 无连续 3 帧 finite/null 分歧 |
| nominal exposure | 5 seeds 中至少 4 次 minimum positive TTC 位于 `(2.5, 6.0]` |
| 安全 | nominal collision=0，身份/route/clock 全部有效 |
| fail-fast | 第一个 null 立即审计；同一候选第 2 个 TTC-band 失败即停；连续 2 个 null 停止全部构建 |

只有 Stage B 和 Stage C 都通过，才能称“已恢复构建正确、有用实验数据的条件”。这仍不等于 fault identifiable 或数据集完成。

## 四、计划修改范围

| 范围 | 允许 | 不允许 |
|---|---|---|
| bridge source | gear feedback 和必要的可观测性修复 | 修改 CARLA 物理参数追求 TTC |
| Apollo config | 对齐 Apollo 10 已安装配置和 fail-closed preflight | 复制 Apollo 9 配置、屏蔽 planner error |
| gate | 增加 execution/actor/时钟检查 | 放宽 TTC、RMSE 或安全门槛 |
| protocol | 新建 v2 开发/校准版本 | 修改 v1 YAML、旧 decision/ledger/data |
| 数据 | 新隔离 pilot，全部标版本和用途 | 把诊断 replay 或旧 F01–F04 冒充数据集 episode |

## 五、测试后结果（实施后只追加此节）

尚未实施。完成每层后填写：

| 阶段 | source commit / config SHA | 精确命令 | 实际结果 | 与预期偏差 | 是否成功 |
|---|---|---|---|---|---|
| Stage A CPU/静态 | `231a4a0a27ce9de878d428eb3975adcc34e81a3c`；installed Neo pipeline 由 `PLANNING_PREFLIGHT.json` 记录 | `python -m pytest -q`；`verify_bridge_gear_mapping.py`；`preflight_apollo10_planning.py`；compile/secret/large-file/diff checks | 全量 `148 passed`；真实 bridge 方法映射 drive/reverse/parking=`1/2/3`，转换序列=`[1,2,1,3]`；Apollo 10 task plugin/default config `12/12 PASS`；其余静态审计 PASS | 第一次验证使用的 `cage-ad` Python 未安装 CARLA，第二次使用 `guardian` 又缺 protobuf；最终仅组合服务器已有只读 Python 路径并启用旧 pb2 兼容模式后成功，未安装/下载依赖。另确认 stage-local 文件是可选覆盖，不能按原先猜测复制配置；插件默认配置本身完整 | **Stage A 成功** |
| Stage B no-NPC #1 | `c2724728e1435123629f8c506667ad8aa94b531e` | `run_execution_smoke_once.sh NO_NPC_01 ...` | **FAIL**；400/400 连续帧、路由成功、NPC=0、gear mismatch=0，但 planning/control 消息均为 0、进度 0 m、轨迹覆盖 0%；powered-on 64.049 s | 烟测封装遗漏 D0 的 nominal identity interposer：真实 stack 输出 `/apollo/planning_raw`、`/apollo/control`，而 gate 读取 `/apollo/planning`、`/apollo/control_guarded`；同时 11 个可选 stage override 缺失仍以 error 打印。因此本次不能检验速度跟踪，但失败记录保留并计入一次 smoke | **失败；停止重复运行，允许一次明确基础设施修复** |
| Stage B no-NPC #2 | `aa5c97093803ddfebde422a4ebd0d3bfa214e91e`；protocol bundle `382567248f7cc03bda2c65ac8da90b6e0b2ea7c0ff7aa158e802f1d7390ba1a8` | `run_execution_smoke_once.sh NO_NPC_02 ...` | **FAIL**；400 连续帧、route PASS、NPC=0、gear mismatch=0、配置缺失=0；identity interposer prediction `756/756`、planning `729/729`、control `3103/3103`；20 秒进度 4.421 m，速度中位 0.117、最大 0.784 m/s；最佳 5 秒 tracking ratio `0.356<0.70`；powered-on 69.635 s | 原始 coverage 被 planning 的 wall-clock header 与 CARLA simulation clock 直接比较，错误记成 0；离线按“当前有效轨迹”重算为 `0.94<0.95`，仍不通过。该测量实现已离线修正但未用重算结果覆盖旧 evidence。Apollo 仍有 13 次 planner failure/fallback | **失败；gear/identity/config 子修复成功，但整条运行链修复失败** |
| Stage B no-NPC #3 | 不运行 | 不运行 | `SKIPPED_FAIL_FAST` | 唯一一次明确基础设施修复已用于 `NO_NPC_01→02`；#2 仍在真实 tracking、进度和 trajectory coverage 上失败，继续跑不能改变结论 | **未运行** |
| Stage C nominal pilot | 不运行 | 不运行 | `NOT_ADMISSIBLE` | Stage B 要求 3/3；当前 0/2，且 #3 按 fail-fast 取消 | **未运行；数据构建保持暂停** |

最终结论固定使用以下之一：

- `REPAIR_SUCCESS_DATA_PILOT_ADMISSIBLE`
- `REPAIR_PARTIAL_RUNTIME_NOT_READY`
- `REPAIR_FAILED`
- `REPAIR_BLOCKED_EXTERNAL`

当前状态：`PRE_REPAIR_PLAN_FROZEN`。

实施进度（追加）：`REPAIR_PARTIAL_RUNTIME_NOT_READY`。Stage A 成功；Stage B 的 gear、identity interposer 和显式 no-op config 子项已修好，但车辆跟踪和规划稳定性没有达到冻结门槛。Stage C 与数据集构建不得启动。

## 六、测试后的最终判断

### 6.1 哪些修复成功了

1. **chassis gear 修复成功**：`NO_NPC_01` 和 `NO_NPC_02` 共 800 个采样帧，control 请求 drive 时 chassis 未出现一次稳定错档；原先 1200/1200 neutral 的确定性缺陷已消失。
2. **D0 identity/guarded 工具边界恢复成功**：修复后的 prediction、planning、control 全部一进一出，`fault_applications=0`，不是通过绕过 verifier 得到结果。
3. **Apollo 10 stage 配置语义已澄清**：11 个空 textproto 仅声明“无用户覆盖”，插件默认配置未改变；缺失日志从 22 条降为 0。
4. **时钟、route、actor identity 成功**：两个运行窗口均为 400 帧、20 Hz、0 frame gap；第二次 route 成功且全程只有一个 ego、没有 NPC。

### 6.2 哪些问题仍未修好

1. **实际速度跟踪失败**：最佳 5 秒窗口实际/目标中位速度比只有 35.6%，小于冻结的 70%；20 秒仅前进 4.421 m，小于 10 m。
2. **规划仍不稳定**：第二次 run 中 408 条观测到的 planning 里 382 条有效；按逐帧最新有效状态离线重算覆盖率为 94.0%，仍低于 95%，并保留 13 次 planner failure/fallback。
3. **Apollo 与 CARLA 时钟域不一致**：planning header 是 wall clock，chassis/CARLA 是 simulation clock。第一版 coverage 实现因此错误为 0；此错误已修正源码但没有篡改历史 result。
4. **控制标定仍不可信**：当前 bridge 把 Apollo 常见 `15.7%` throttle 乘 1.5 后作为 CARLA `0.2355`；installed Apollo calibration table 是通用车辆表，不是这台 CARLA Lincoln 的实测表。在相同油门下速度反复降到接近 0，不能声称 actuator mapping 已校准。
5. **加速度反馈被配置为恒零**：bridge 的 `localization_accel_alpha=0.0` 使滤波状态从零开始后永远为零；Apollo longitudinal controller 因而看不到 CARLA 实际加速度。这是下一轮新协议必须单独验证的高价值基础设施根因候选，但本轮不得再改参数后重跑。

### 6.3 资源、证据与终态

- 实际 CARLA/Apollo powered-on：`64.049071581 + 69.634910779 = 133.683982360 s`（约 `0.03714 h`）。
- repair data：`1,721,061 bytes`，远低于 2 GiB 修复预算。
- `NO_NPC_01 result.json` SHA256：`9ceb06dcbcb1901245afb85680bf5094f4bd721da03736477fd364d9cab1e47e`。
- `NO_NPC_02 result.json` SHA256：`303819b5a3ed1aa9254c043f587d8bf4bc994df3926b92f35a692e5fb8c48cb7`。
- 旧 protocol-v1 calibration ledger/YAML/decision/data 未写入；两个 run 均标记 `RUNTIME_REPAIR_SMOKE_NOT_DATASET`，不得开源为数据 episode。
- 没有启动 nominal TTC pilot，因此本阶段既没有制造新的 TTC 空值，也没有资格声称 TTC 问题已修复。

最终结论：**`REPAIR_PARTIAL_RUNTIME_NOT_READY`**。对应 D0 决策为 **`D0_MODIFY_INFRA`**：修复方向有明确证据，但当前 Apollo 10 + CARLA 运行链仍不能生成满足冻结门槛的有用实验数据。`CALIBRATION_REMAINS_PAUSED`，不得恢复数据集构建。
