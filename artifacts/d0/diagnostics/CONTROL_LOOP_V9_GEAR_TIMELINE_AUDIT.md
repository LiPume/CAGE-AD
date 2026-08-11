# Apollo—bridge—CARLA 真实挡位时间线 v9 审计

状态：**审计前合同已冻结，尚未运行**

分支：`codex/apollo-d0-control-loop-repair-v9`

基线提交：`ac17a92f40b0a06f6b9dfe229979ffd45b6e8465`

## 已找到的问题

bridge 当前向 Apollo 回报挡位时，只判断 `hand_brake` 和 `reverse`：不是手刹、不是倒车就固定回报 `GEAR_DRIVE`。它没有读取 CARLA `VehicleControl.gear`。因此旧结果中的“Apollo 控制挡位=前进挡、Apollo 底盘挡位=前进挡”只是 bridge 自己前后一致，不能证明 CARLA 自动变速箱真实处于 1 挡。

V8 已观察到真实 CARLA gear 从 0 进入 1 的延迟会随油门变化。CARLA 官方 API 也明确把 `gear` 和 `manual_gear_shift` 定义为车辆控制状态字段。

## 唯一允许的修改

只增加观测字段，不改变控制行为：

- bridge 逐命令记录 CARLA `gear` 和 `manual_gear_shift` 回读；
- 20 Hz 轨迹逐帧记录相同字段；
- 不修改 bridge 向 Apollo 回报挡位的旧逻辑；
- 不修改油门、刹车、转向、alpha、自动变速箱或车辆物理。

沿用 V7 已通过的启动、Town01、转向和 alpha 配置，只运行一次 20 秒无车诊断。结果仍标记 `RUNTIME_REPAIR_SMOKE_NOT_DATASET`。

## 审计要求

- 400 个仿真帧必须全部有 CARLA 真实 gear；
- 必须报告第一帧 gear=1 的时间、gear=0 总帧数、油门首次非零时间；
- 必须分别报告 Apollo 控制挡位、Apollo 底盘挡位和 CARLA 实际挡位；
- 任何真实 gear=0 但 Apollo 底盘仍回报前进挡的帧都记为“反馈不真实”，不得继续沿用旧的挡位一致性说法；
- 本轮不修挡位、不调油门，只决定下一阶段应先修反馈还是先做标定。

V9 预算 10 分钟、256 MiB。

## 审计结果

待填写。
