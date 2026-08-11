# Apollo—bridge—CARLA 控制闭环 v6 修复计划与结果

状态：**修复前合同已冻结，尚未启动 v6**

分支：`codex/apollo-d0-control-loop-repair-v6`

基线提交：`4b61326d28d57b7443fa31ed9ad51ded6542f922`

## 已知事实

- V5 已证明 `-RenderOffScreen` 能让独立 CARLA 服务器在无显示环境中稳定运行并提供 RPC；
- V5 也证明打包启动命令没有预载 Town01，地图保持 Town10；
- CARLA 0.9.15 官方文档明确支持服务器启动后由客户端调用 `client.load_world('Town01')`；
- 早先独立车辆响应脚本曾用相同 API 成功进入 Town01，但本轮必须重新做一个不含车辆的干净检查。

## V6-A 唯一允许的检查

1. 独立官方启动器只增加已经被 V5 验证的 `-RenderOffScreen`，不在命令行传地图；
2. 等默认世界 RPC 就绪；
3. 单独的有界客户端只调用一次 `load_world('Town01')`；
4. 等待新世界至少一个 tick，确认地图精确为 Town01；
5. 不启动 bridge、Apollo、车辆、路线或场景，然后正常关闭。

只运行一次，90 秒上限。任何异常、Signal 11、地图不符或无法正常关闭都判失败并回滚，不允许重试。

## V6-B 依赖

只有 V6-A 成功，才允许把“RenderOffScreen 启动→客户端预载 Town01→bridge”接入闭环脚本，再重新应用冻结转向值 `0.419643` 做一次 20 秒无车测试。油门、刹车、加速度反馈及 V3-B 门槛保持不变。

数据集和 TTC 在基础闭环通过前继续暂停。V6 预算上限 15 分钟、512 MiB。

## 测试后结果

待填写。
