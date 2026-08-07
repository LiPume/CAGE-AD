# CAGE-AD Apollo D0 protocol v2 变更提案

状态：提案；不得把 v1 数据回填为 v2，不得从 formal test 调参。

## 1. 为什么需要 v2

v1 把 route response 当作 actor 动作起点，但没有验证 ego 已进入稳定巡航。LBM0 的 actor 在 9.3 秒已停止，而 ego 始终没有达到 2 m/s；CIE0 的实际 actor 也没有按声明穿过目标车道。延长 LBM0 到 60 秒仍无有限 TTC，说明仅改 observation window 不能解决问题。

## 2. 先修运行链，再冻结 v2

v2 pilot 前必须通过独立的无 NPC execution smoke：

- planning、control、chassis 和 CARLA actual 的 gear 一致；
- lane-follow task 配置无缺失和持续 fallback；
- 在预注册连续窗口内，实际速度/进度跟踪规划目标；
- bridge topic、油门、刹车、方向、reverse/gear 反馈一致。

这些是基础设施修复，不是场景调参。未通过时禁止运行 v2 场景。

## 3. 场景 epoch

不再以 route response 单独触发 NPC。使用两阶段 epoch：

1. `route_ready`：routing、planning、control 流健康；NPC 冻结。
2. `interaction_ready`：ego 在无 NPC 基线预注册的巡航目标及跟踪容差内稳定一段时间，并到达声明的空间锚点；此时才启动 actor program。

巡航目标、容差、稳定时长和空间锚点先在独立 development seeds 上冻结。formal seeds 不得用于选择这些数值。

## 4. actor 轨迹定义

### Lead brake

recipe 必须显式声明 interaction epoch 下的相对 headway、actor 速度、制动时刻/空间点、减速度和停车位置。每帧审计 intended/actual，RMSE、timing 和最终位置必须通过。

### Cut-in

轨迹改成完整的横向速度剖面：加速进入、在目标车道中心附近减速、横向速度归零并保持。必须声明目标 lane/road、终端横向偏差、最大横向速度和收敛时限；持续横穿多个车道不再是合法 cut-in。

## 5. nominal admission 与 fail-fast

每个候选最多 5 个 calibration seeds：

- runtime/execution/actor gate 全部通过；
- 5 次中至少 4 次 minimum positive TTC 位于 `(2.5, 6.0]`；
- collision=0，route accepted，身份和时钟稳定；
- production TTC 与独立 TTC 无稳定分歧；
- planned path 与 actor future path 作为解释性辅助指标，不替代 TTC gate。

第一个 null 立即审计。同一候选出现第 2 个 TTC-band 失败后，数学上不可能达到 4/5，立即停止候选。连续 2 个 null 时暂停全部构建并重新做根因诊断，不自动切换 seed/candidate。

## 6. 独立 pilot 和预计运行数

阶段 0：最多 3 次无 NPC execution smoke。

阶段 1：四个 scenario parent 各最多 5 次 nominal，共最多 20 次；先逐 family 执行，前一 family 未通过不自动展开后一 family。

阶段 2：只有 nominal admission 通过才恢复对应 recipe 的 fault dose/probe。首次 v2 pilot 不运行 formal seeds、Agent 或 baseline。

按当前启动开销估计，阶段 0+1 powered-on 小于 0.7 小时，语义增量小于 0.6 GiB。实际 gate 必须继续记录用量。

## 7. 版本和结论边界

- v1 YAML、decision、ledger、RUN_STATE、visible/private 数据保持只读。
- v2 使用新目录、新 protocol bundle SHA、新 run ID 和新 Git commit。
- v1 的 `rejected_no_causal_dose` 仍是“旧实现下的历史结果”，不能改写；它不预测 v2 的结果。
- v2 pilot 通过只能说明场景可进入预注册风险区，不能提前宣称 fault identifiable、Agent 有效或数据集已经完成。
