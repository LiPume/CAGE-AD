# Apollo 10 protocol v1 连续 TTC=null 根因报告

结论：主要根因是 B `EGO_EXECUTION_OR_RUNTIME_BUG`，置信度高。现有 TTC 为 null 的直接原因是实际闭环中自车始终异常缓慢，NPC 在远处完成动作，双方从未形成几何冲突。旧 F01–F04 必须在修复后重跑；protocol v1 必须停止并提出 v2。校准仍暂停。

`CALIBRATION_REMAINS_PAUSED`

## 1. 最关键证据

1. 唯一满足完整时钟门槛的 `R4/R3_LBM0_SEED1101_60S` 有 1200 帧、0 个 frame gap、59.95 秒有效仿真。自车 60 秒只前进 10.528 m，速度中位数 0.082 m/s、最大值 0.821 m/s。
2. 同一有效回放中，Apollo control 93.25% 的采样给出大于 10% 的油门，前 10 秒 planning 一秒后目标速度中位数为 0.833 m/s；但 CARLA 自车仍长期接近静止。逐帧后审计还发现 1200/1200 帧 control 要求 `GEAR_DRIVE=1`，chassis 却回报 `GEAR_NEUTRAL=0`。源码确认 bridge 发布 chassis 时没有设置 `gear_location`，protobuf 因而使用默认空挡值。
3. LBM0 前车在 route epoch 后 7.0 秒开始制动、9.3 秒停止；自车从未达到 2 m/s。最近 OBB 距离出现在 0.05 秒，为 30.742 m，之后先增大到约 78 m；延长到 60 秒后仍为 68.881 m。production 与独立 0.01 秒计算器均为 0 个有限 TTC tick。
4. CIE0 诊断中 actor 的实际速度相对 recipe 的 RMSE 为 2.576 m/s，且没有穿过自车车道中心；解析 recipe 却预期约 6.6 秒穿过，并在 32 秒仍以 1.5 m/s 横移。这说明 cut-in 执行与定义本身也不适合作为数据 parent。
5. 只读审计覆盖 ledger 中全部 75 个 nominal `attempt_finished`；其中 61 个有完整旧 metrics，61/61 的 finite TTC tick 都为 0。旧 trace 没有 actor ID、完整 OBB、速度分量或 Apollo 命令值，不能独立复算 TTC。

## 2. 为什么 TTC 会是 null

TTC 计算器回答的是“从当前完整 OBB 和当前世界速度开始，未来 10 秒内两个矩形是否会重叠”。本次有效 LBM0 中，前车先以约 6 m/s 远离自车，随后在约 84.2 m 的初始相对位置附近停住；自车最高不足 1 m/s。因此双方当前速度外推不会重叠，返回 null 是正确行为，不是把已有碰撞漏掉。

独立计算器不导入正式 evaluator，使用 0.01 秒步长；golden tests 覆盖已知追尾、同速、同时/错时垂直相交、初始重叠和非零 bounding-box local transform/yaw。它与 production 在所有诊断 tick 上没有一次 finite/null 分歧。H4 因而被反证。

## 3. 表 1：F01–F04 候选只读统计

`runs` 同时给出 ledger 行数和有完整 metrics 的 completed 数；LBC0 的多余失败/中断来自早期基础设施重试，均保留。progress 是 completed run 的前进距离范围；separation 是旧 trace 的最小 center separation。旧产物没有完整 OBB，不能把这里的 center separation 当 OBB separation。

| recipe | candidate | runs（ledger/completed） | progress m（min–median–max） | min center separation m | finite TTC ticks |
|---|---:|---:|---:|---:|---:|
| CAL-F01 | LBC0 | 20 / 6 | 5.745–7.645–24.760 | 30.239 | 0 |
| CAL-F01 | LBC1 | 5 / 5 | 5.832–6.422–7.838 | 27.239 | 0 |
| CAL-F01 | LBC2 | 5 / 5 | 5.883–7.029–7.657 | 30.288 | 0 |
| CAL-F02 | LBM0 | 5 / 5 | 6.326–7.169–7.837 | 35.288 | 0 |
| CAL-F02 | LBM1 | 5 / 5 | 6.498–7.078–15.216 | 32.288 | 0 |
| CAL-F02 | LBM2 | 5 / 5 | 6.863–7.239–7.970 | 35.337 | 0 |
| CAL-F03 | CIE0 | 5 / 5 | 5.816–6.407–8.124 | 25.384 | 0 |
| CAL-F03 | CIE1 | 5 / 5 | 5.537–6.503–8.013 | 22.416 | 0 |
| CAL-F03 | CIE2 | 5 / 5 | 6.069–6.949–7.642 | 25.369 | 0 |
| CAL-F04 | CIL0 | 5 / 5 | 6.232–7.178–34.349 | 30.393 | 0 |
| CAL-F04 | CIL1 | 5 / 5 | 5.902–7.449–8.480 | 27.415 | 0 |
| CAL-F04 | CIL2 | 5 / 5 | 6.250–6.797–7.172 | 27.378 | 0 |

注：持久 ledger 显示 CAL-F04 已在暂停消息到达前完成 15 个 nominal run 并写入终态；旧公开进度文档来不及反映这一事实。本报告不修改旧 ledger、decision 或 RUN_STATE。

## 4. 表 2：4 次物理 replay 的六个事件时刻

由于前两次 R1 instrumentation 漏帧，4 次物理 replay 依次编号为 R1–R4；R3 是 CIE0 核心对照，R4 是合同规定的无 evaluator 分歧时 LBM0 60 秒分支。事件除 route epoch 外均为 route epoch 相对秒。

| replay | 场景/时长 | route epoch（sim s） | ego >0.5 m/s | ego >2.0 m/s | actor program start | actor cross/stop | min geometry |
|---|---|---:|---:|---:|---:|---:|---:|
| R1 | LBM0 / 32 s，instrumentation invalid | 15.487 | 2.150 | null（从未达到） | 7.000 | stop 9.400 | 0.050 |
| R2 | LBM0 / 32 s retry，instrumentation invalid | 15.497 | 2.100 | null（从未达到） | 7.000 | stop 9.300 | 0.050 |
| R3 | CIE0 / 32 s，instrumentation invalid | 13.501 | 2.050 | null（从未达到） | 3.000 | null（未穿过） | 0.050 |
| R4 | LBM0 / 60 s，有效 | 13.081 | 2.050 | null（从未达到） | 7.000 | stop 9.300 | 0.050 |

R1/R2/R3 分别只有 308、414、534 帧且存在 307、218、106 个 gap；它们仅作辅助观测。R4 有 1200 帧、0 gap，是根因结论的主证据。

## 5. 表 3：三种冲突证据对照

| replay | production finite ticks | independent finite ticks | stable finite/null mismatch | planned-path conflict | planned min separation m | 证据资格 |
|---|---:|---:|---:|---|---:|---|
| R1 | 0 | 0 | 0 | 否 | 33.017 | 辅助；漏帧 |
| R2 | 0 | 0 | 0 | 否 | 33.139 | 辅助；漏帧 |
| R3 | 0 | 0 | 0 | 否 | 21.901 | 辅助；漏帧且 actor 执行失败 |
| R4 | 0 | 0 | 0 | 否 | 33.028 | 有效主证据 |

因此 H2“规划路径原本冲突，只因 Apollo 成功避险才让实际 TTC 变 null”没有得到支持。Apollo decision 中出现 obstacle 1001/stop 信息，但规划路径与 actor future path 的最小距离仍大于 21 m。

## 6. 表 4：H1–H4 归因

| 假设 | 支持证据 | 反证/限制 | 结论 | 对应处置 |
|---|---|---|---|---|
| H1 NPC 在 ego 起步前完成动作 | LBM0 在 7 s 开始制动、9.3 s 停止；ego 从未到 2 m/s；60 s 仍无冲突 | LBM0 timing error 0.15 s 略超 0.10 s；其 RMSE 0.102 m/s 正常 | 支持，属于次要 D 类 trigger/design failure | v1 不改；v2 用稳定巡航/空间锚点触发并独立预注册 |
| H2 Apollo 主动避险令 TTC 变 null | 存在 stop/obstacle decision 和少量 brake | planned min separation 21.9–33.0 m，无 planned-path conflict；大部分时间仍给油 | 不支持为本轮主要原因 | v2 保留 planned-path 审计，但不能用 H2 解释当前 null |
| H3 Apollo/bridge 执行链异常慢 | 自车中位速度约 0.08–0.17 m/s；93% 时间给油；drive 命令与 neutral chassis 反馈 1200/1200 不一致；bridge chassis 未设置 gear | control topic 正确，CARLA 确实收到油门；说明不是单纯订阅错 topic，仍需修规划 fallback/反馈链 | **主要根因 B，高置信度** | 修 chassis gear、Apollo 10 planning 配置与 execution gate；先做无 NPC 跟踪 smoke，再重跑 |
| H4 evaluator/身份/坐标错误 | 无 | 1 个稳定 ego ID 和 1 个稳定 actor ID；OBB transform golden tests 通过；两计算器零分歧；实际最小 OBB 距离大于 20 m | 反证，非根因 | 不改 production TTC；保留双计算器回归测试 |

此外，CIE0 的 actor RMSE 2.576 m/s、timing error 0.45 s 且未穿过车道中心，满足 C 类 `INTERACTION_ACTOR_EXECUTION_BUG`，是 cut-in 家族的次要但独立阻塞项。

## 7. 实现 bug 与协议设计失败的边界

- 主要实现 bug（B）：bridge chassis gear 反馈缺失；Apollo planning 日志反复报告 lane-follow task conf 缺失和 fallback；现有 infrastructure gate 只数消息，不验证规划—控制—chassis—CARLA 跟踪。
- cut-in 实现 bug（C）：车辆物理执行没有复现声明的 lateral velocity，actor 未进入目标车道。
- protocol 设计失败（D）：NPC 在 route response 后立即动作，没有等待稳定巡航；解析 cut-in 穿过目标车道后仍持续横移；v1 的 32 秒/当前速度 TTC 准入没有 execution readiness gate。

因此只修 TTC evaluator 或延长窗口都无效；只把 observation 从 32 秒改成 60 秒也已经被 R4 反证。

## 8. 最小修复、重跑与 fail-fast

### 8.1 运行链修复

1. bridge 发布 chassis 时显式映射 CARLA/control 状态到 `GEAR_DRIVE/REVERSE/PARKING`，并增加 control gear—chassis gear—CARLA reverse 的一致性测试。
2. 修复 Apollo 10 lane-follow 配置解析，消除 `lane_follow_stage/*.pb.txt is not found` 和持续 fallback；不得用降低规划门槛掩盖错误。
3. 新 infrastructure gate 必须验证连续窗口内 planning target、control、chassis 和 CARLA 实际速度/进度的跟踪；仅有消息计数不再算 valid。
4. cut-in actor 必须通过实际轨迹 RMSE、车道中心穿越和目标车道保持 gate。

### 8.2 v2 场景与准入

详见 `PROTOCOL_V2_CHANGE_PROPOSAL.md`。核心是把 scenario epoch 放在“自车已稳定跟踪巡航”之后，并让 cut-in 在目标车道收敛。所有数值在独立 pilot 中预注册，不能从 formal test 反调。

### 8.3 重跑范围和估计

- 先做 3 次无 NPC 跟踪 smoke，预计 powered-on 小于 0.1 h、增量空间小于 0.1 GiB。
- v2 四类 scenario parent 每类最多 5 个 nominal seed，共最多 20 次，按本轮每次约 77–105 秒 powered-on 估算小于 0.6 h、语义产物小于 0.5 GiB。
- fail-fast：第一个 null 立即审计；同一候选出现第 2 个 TTC-band 失败后，因不可能再达到 4/5，停止该候选和批量构建。连续 2 次 null 则停止全部构建并重新诊断。
- pilot 通过后，旧 F01–F04 的 nominal 必须在新版本重新运行；旧运行不能转正。fault/dose/probe 尚未生成，不能估计为已完成工作。

## 9. 旧 F01–F04 还能做什么

可以：复现“旧 gate 为什么会接受低速运行”、做日志/数据管线回归、验证 ledger 和隔离机制、作为无有限 TTC 的负面工程案例。

不可以：作为训练或正式评价 episode；证明 forecast fault 无害；证明 Apollo 成功避险；证明 evaluator 有 bug；把 `rejected_no_causal_dose` 解释成故障机制无因果作用。

## 10. 可以和不可以宣称

可以宣称：在当前 Apollo 10/CARLA v1 运行链中，连续 TTC=null 主要由自车执行异常慢造成，LBM0 实际轨迹没有形成冲突；production TTC 与独立计算器在本轮一致。

不可以宣称：所有可能场景都会永远 null；修复后一定产生 identifiable 数据；已有 75 个 attempt 是有效 benchmark；Multi-Agent/LLM 或任一 fault 已被评价。

## 11. 诊断产物与资源

状态根：`/root/autodl_apollo10_g0_bundle/runtime_state/diagnostics/ttc_null_20260807T074356Z`

数据根：`/root/autodl-tmp/cage_ad_diagnostics/ttc_null_20260807T074356Z`

每个已执行 run 的 `retained/` 下均有 `trace.jsonl`、`summary.json`、`xy_trajectory.png`、`semantic_timeseries.png` 和 `diagnostic_replay.mp4`：

- `R1_LBM0_SEED1101_32S`
- `R1_RETRY1_LBM0_SEED1101_32S`
- `R2_RETRY1_CIE0_SEED1101_32S`
- `R3_LBM0_SEED1101_60S`

视频均已由 ffprobe 验证为 H.264、1280×720、20 fps，时长分别为 32.00、32.00、32.05、60.00 秒。SHA-256 在状态根的 `ARTIFACT_VALIDATION.json`。4 次 replay 总 powered-on 为 338.318 秒（0.094 h），诊断数据约 32 MiB，低于 1.5 h/5 GiB 上限。

## 12. 固定验证

- `cage-ad-py310 -m pytest -q`：146 passed。
- `compileall -q src scripts tests`、`bash -n`、`shellcheck`：PASS。
- `tools/source_audit.py`：PASS，扫描 186 个 tracked/untracked source candidates、3 个 upstream provenance；secret、private-key filename、1 MiB large-file、runtime/private material 均无命中。
- protocol storage/oracle/diagnosis-visible 定向测试：26 passed；bundle final audit 的 isolation、sensitive material、managed process、static checks 全部 PASS。
- 4 个 trace 的非空行数均等于 summary/finished 的 `trace_frames`；4 个 MP4 均通过 ffprobe。完整 SHA-256 在 `ARTIFACT_VALIDATION.json`。
- 没有 Apollo/CARLA/diagnostic/calibration 残留进程，没有未完成且未 supersede 的 diagnostic plan；Git 未 stage trace、MP4、private config 或 runtime。

## 13. 最终状态

诊断结论不是 D0 数据集终态；它是恢复数据构建前的阻塞审计。旧 ledger、decision、RUN_STATE、protocol v1 YAML 和已有数据均未修改。Apollo/CARLA 已关闭。

`CALIBRATION_REMAINS_PAUSED`
