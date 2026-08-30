# CARLA 车辆物理、挡位和控制接口限速审计

状态：**审计完成；没有发现需要取消的 CARLA 自身限速**

本文件只回答一个问题：当前 Lincoln 开不快，是不是因为 CARLA 的车辆物理、挡位或控制接口把车锁住了？本轮不修改车辆物理、不修改挡位、不修改 Apollo 标定表，也不生成数据集。

## 通俗结论

不是 CARLA 把车硬锁在 1～2 米/秒。

最直接的证据是：同一辆 CARLA Lincoln、同一套原始车辆物理，直接给 50% 油门后，车辆已从约 1.02 米/秒加速到 4.27 米/秒。若存在 1～2 米/秒的硬限速，这次运行不可能发生。

当前更符合证据的解释是：Apollo 原来的通用控制表在这个低速区给出的油门太小。实测在 2.02 米/秒时，30% 和 35% CARLA 油门仍会掉速，40% 才开始小幅加速，45% 和 50% 才有清楚的正加速。因此“计划想开快”不等于“控制层实际给了足够油门”。

## 1. 车辆物理参数有没有把速度锁死

结论：**没有发现异常限速参数，不应修改车辆物理来掩盖控制问题。**

运行时读到的车辆是 `vehicle.lincoln.mkz_2017`，质量 1696 千克，最大转速 6500 转/分，自动变速箱开启，主减速比 3.21，轮胎半径 0.355 米，共 6 个前进挡。扭矩曲线从 1000 转/分的 347 牛·米上升到 3000 转/分的 695 牛·米，再正常下降。这些是完整、可用的车辆动力参数，不是一个被设置成极低最大速度的简化车。

按最大转速、轮胎半径、主减速比和 1 挡齿比做一个只用于排除低速上限的近似换算，1 挡对应约 16.42 米/秒，也就是约 59.1 千米/小时。真实最高速度还会受阻力、轮胎和换挡影响，但这个数量级足以证明当前约 1.4 米/秒不是由 1 挡转速上限造成的。

CARLA 官方接口也没有一个藏在 `VehiclePhysicsControl` 里的“最大车速”开关。车辆速度由扭矩曲线、最大转速、质量、阻力、离合器、主减速比、各挡齿比和轮胎共同产生。道路限速是地图信息；只有交通管理器或 CARLA 自带驾驶 Agent 选择按它控制时，才会变成目标速度。

## 2. 挡位是不是卡住了

结论：**启动初期有约 2.1 秒挂挡等待，但没有持续卡挡。**

运行时自动挡为开启状态。在 V11 的 3134 条控制回读中，`manual_gear_shift` 全部为 `false`，说明没有脚本强制手动挡。车辆启动后先短暂处于 0 挡，约 2.1 秒后进入真实 1 挡。

V11 又把 CARLA 真实挡位和反馈给 Apollo 的挡位逐帧配对检查：900 条配对记录中，错误映射为 0，虚假“已经在前进挡”的记录为 0。也就是说，早期确实存在的挡位反馈问题已经修好，当前 Apollo 能看到真实的空挡到前进挡变化。

V13 和 V16 的所有正式测量样本都确认从真实 1 挡开始，车辆仍能在更大油门下正常加速。因此挡位不是持续慢车的根因。

## 3. 控制接口是不是用了限速模式

结论：**自车使用的是直接油门/刹车接口，没有使用会按道路限速行驶的 CARLA 交通管理器或自带驾驶 Agent。**

bridge 的实际链路是：把 Apollo 百分比油门换算成 CARLA 的 0～1 油门，然后调用 `vehicle.apply_control(VehicleControl)`。它没有对自车调用 `apply_ackermann_control`，也没有调用 `enable_constant_velocity` 或 `set_target_velocity`。配置里的油门换算系数是 1.5，它会放大 Apollo 油门，而不是限制速度。

代码里虽然保留了一个 `set_autopilot` 回调函数定义，但全工作区搜索没有找到自车启用它的调用。协议场景代码创建交通管理器只用于固定随机种子；`set_target_velocity` 只用于前车/横穿车等交互车辆，不用于 Apollo 自车。

CARLA 官方说明也明确区分了这些接口：

- `VehicleControl` 是直接施加油门、刹车、转向和挡位命令；
- 交通管理器只有在车辆通过 `set_autopilot(true)` 注册后才接管，并按道路限速百分比选择目标速度；
- CARLA 自带 Basic/Behavior Agent 也有目标速度和最大速度规则，但本项目自车没有使用这些 Agent；
- `enable_constant_velocity` 会覆盖普通速度变化，本项目自车没有调用它。

因此，取消交通管理器限速或修改 Agent 的 `max_speed` 对当前 Apollo 自车不会起作用。

## 4. 已有实车式测量为什么足以排除硬限速

V13 中，车辆从 1.0176 米/秒开始，真实 1 挡、零刹车、50% 油门运行 3 秒，结束速度为 4.2704 米/秒，三次重复完全一致。

V16 中，从 2.0221 米/秒开始的结果如下：

| CARLA 油门 | 速度变化趋势 |
|---:|---:|
| 30% | -0.3478 米/秒² |
| 35% | -0.1463 米/秒² |
| 40% | +0.1643 米/秒² |
| 45% | +0.6584 米/秒² |
| 50% | +1.2317 米/秒² |

这组数据说明车辆没有“到某个速度就被切断动力”，而是低油门不足以抵消该速度下的车辆阻力；提高油门后，加速度随之明显提高。

## 5. 现在不应该做什么

- 不应把交通管理器的限速比例改成负数，因为自车没有由交通管理器控制；
- 不应打开恒速接口，因为它会绕开 Apollo 的真实控制闭环，使数据集失去诊断意义；
- 不应提高发动机扭矩、最大转速，或降低车辆质量和阻力来“让结果好看”；
- 不应强制锁 1 挡作为正式方案，因为自动挡已经正常工作，而且会改变被评估车辆；
- 不应继续批量生成 TTC 数据，直到新的低速控制候选通过无车闭环和交互场景有效性检查。

## 6. 下一步

保持 CARLA 原始车辆物理、自动挡和直接 `VehicleControl` 接口不变。继续使用 V16 的多速度实测结果制作一次运行专用的低速控制候选，再用冻结的 0.70 跟踪门槛验证。若失败，保留失败结果并停止，不通过修改 CARLA 物理或评价标准救结果。

## 官方网页存档

网页保存在持久盘 `runtime/references/apollo_control_loop_20260811/web/`，不进入 Git：

- `v3_primary/carla_0.9.15_python_api.html`
- `v17_primary/carla_0.9.15_actors.html`，SHA256 `b761dc119ac5a155811eb0f6e67b013ad3ba64a5a426ef93f45980e03832b6f8`
- `v17_primary/carla_0.9.15_agents.html`，SHA256 `2d316663b3ffb322fb1a906b260d2b9d8d73789e0e9fdd9a8ded5b71079ab18f`
- `v17_primary/carla_0.9.15_traffic_manager.html`，SHA256 `40fd880245251a0fabfa1130203d2dec219f012f9aba7299e7210fb796176595`

对应官方在线页面：

- https://carla.readthedocs.io/en/0.9.15/core_actors/
- https://carla.readthedocs.io/en/0.9.15/python_api/
- https://carla.readthedocs.io/en/0.9.15/tuto_G_traffic_manager/
- https://carla.readthedocs.io/en/0.9.15/adv_agents/

## 本地证据和校验和

- V11 物理与闭环摘要：`runtime/d0_control_loop_v11_20260811/NO_NPC_V11_PAIRED_GEAR_01/runtime_summary.json`，SHA256 `45c8f0c585c8b028db9f9b7d24c957ef52d3f261fd1f4561a1d66c7fe6b08a53`
- V11 挡位配对摘要：`runtime/d0_control_loop_v11_20260811/NO_NPC_V11_PAIRED_GEAR_01/paired_gear_summary.json`，SHA256 `f2f7b0c0d47f08b0efd4d054bff6a01a5c836f10393c1219d42a690312a726fe`
- V13 1 挡油门测量：`runtime/d0_control_loop_v13_20260811/CARLA_V13_GEAR_ONE_01/summary.json`，SHA256 `5f92a0b95822b6a77809f20a31927c2a23966dbcdcaa0e7ae4c30d2146e75d88`
- V16 多速度测量：`runtime/d0_control_loop_v16_20260811/CARLA_V16_MULTI_SPEED_01/summary.json`，SHA256 `2737c31410bb79ce04519ae75de4771d585f9d1a3313cfa7d9b0dae46637ece1`
- bridge 控制代码：`runtime/bridge/apollo-carla/carla_bridge/actor/ego_vehicle.py`，SHA256 `1f52b3ce750b043e80204297a267744baf96522af44f9883b64375deba545ecb`
- bridge 配置：`runtime/bridge/apollo-carla/carla_bridge/config/settings.yaml`，SHA256 `f08c9d7dccc26d56ea5543a1e928f678b392a82fbee9b1ccd5d1205cfafc8bc1`

