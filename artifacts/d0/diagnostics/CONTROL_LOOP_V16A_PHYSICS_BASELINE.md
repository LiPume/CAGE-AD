# CARLA Lincoln 车辆物理基线检查 V16-A

状态：**已预注册，尚未运行**

## 为什么插入这一步

V15 证明原来的低速控制表与 CARLA Lincoln 不匹配；V16 又证明相同油门的效果会随车速变化。但这两点还不能单独证明“只需要继续做二维控制表”。在反算新表前，必须先确认 CARLA 车辆本体在原始物理参数下全油门能够正常提速。

guardstrikelab/carla_apollo_bridge 的第 159 号开放问题报告称，该 bridge 未主动设置车辆物理，并建议临时打开车轮体积碰撞、把零油门且离合器结合时的阻尼改成 0.35。报告同时认为 Apollo 通用标定表命令偏小。它是社区问题报告，作者明确称物理改法是临时修复，不能直接当作本项目的正确配置。

CARLA 第 3256 号开放问题展示了换挡时间和离合器阻尼会显著改变维持车速所需油门，但对象是 Tesla Model 3，不是 Lincoln。它只能说明这些参数值得检查，不能证明 Lincoln 应照抄相同修改。

## 本轮允许与禁止事项

只启动 CARLA 0.9.15，不启动 Apollo，不启动 bridge，不生成数据集。

允许：读取并记录 Lincoln 的全部车辆物理、每帧实际控制、速度、加速度、挡位、位置、道路限速读数和碰撞。

禁止：调用 `apply_physics_control`，修改阻尼、换挡时间、变速箱、质量、扭矩、阻力、轮胎或地图；禁止 Traffic Manager、autopilot、恒速和目标速度接口。

## 冻结实验

- 地图：Town01；固定位置与 V13/V16 相同；零其他车辆；20 Hz；
- 生成一辆 `vehicle.lincoln.mkz_2017`，先用零控制静置 1 秒；
- 从静止开始直接请求油门 1.0、刹车 0、转向 0、手刹关闭、倒车关闭、手动换挡关闭；
- 连续 10 秒，共 200 帧，只运行一次；
- 每帧用 `get_control()` 回读 CARLA 上一帧实际采用的控制；
- 运行前后各读取一次完整车辆物理并要求完全一致；
- 使用碰撞传感器检查是否撞到环境。

## 冻结判断标准

只有同时满足以下条件才判定 `PASS_PLANT_BASELINE`，并允许恢复二维标定：

- 正好 200 帧，起始速度不超过 0.05 米/秒；
- 每帧回读均为油门 1.0、刹车和转向 0、手刹/倒车/手动换挡关闭；
- 物理参数前后完全一致，自动挡开启，进入前进挡且至少升到 2 挡；
- 没有碰撞；
- 第 10 秒速度至少达到 10 米/秒。

若第 10 秒速度不超过 3 米/秒，判定 `FAIL_PLANT_WEAK_STOP`；停止二维标定，转而审计车辆生成与物理初始化。

若速度在 3～10 米/秒之间，或没有升到 2 挡，判定 `INCONCLUSIVE_STOP`；同样不得继续标定，先查明原因。控制被覆盖、物理发生变化或碰撞则判定 `INVALID_STOP`，不得把无效运行解释成车辆动力弱。

门槛在看正式结果前冻结，本轮只允许一个正式运行，不根据结果修改标准。

## 资料存档

- `runtime/references/apollo_control_loop_20260811/web/v16a_primary/guardstrikelab_issue_159.json`，SHA256 `5d956a51bd2aff2a8b37e3d90d083d77784de2af81f81f6f86737772e1d4f766`
- `runtime/references/apollo_control_loop_20260811/web/v16a_primary/carla_issue_3256.json`，SHA256 `a5765a0b52913cc1c1e07c11a2812b10da769baa382f31d0c15355a753f0cd24`

在线原文：

- https://github.com/guardstrikelab/carla_apollo_bridge/issues/159
- https://github.com/carla-simulator/carla/issues/3256
- https://carla.readthedocs.io/en/0.9.15/python_api/
