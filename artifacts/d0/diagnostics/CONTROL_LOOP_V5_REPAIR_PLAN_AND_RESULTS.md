# Apollo—bridge—CARLA 控制闭环 v5 修复计划与结果

状态：**V5-A 部分成功但未通过，已回滚；终态 D0_MODIFY_INFRA**

分支：`codex/apollo-d0-control-loop-repair-v5`

基线提交：`9f3b1a3b8316d42f5c28033d8a5feda2660deaae`

V3/V4 的失败证据保持只读；数据集、TTC、bridge 和 Apollo 仍暂停。

## 找到的问题

服务器没有图形显示环境。CARLA 官方说明 0.9.12 起的 Unreal 4.26/Vulkan 无屏幕运行应显式传入 `-RenderOffScreen`。V3/V4 独立启动命令没有这个开关，只设置了 CARLA 官方脚本不解析的 `CARLA_RENDER_MODE=offscreen` 环境变量。

## 唯一修复与停止条件

V5-A 只做一项行为改变：独立官方启动器增加 `-RenderOffScreen`。为保持与 V4 可比较，Town01 仍作为第一个地图参数，其他 Vulkan、GPU、用户、HOME 和端口设置不变。

只启动 CARLA，一次、最多 90 秒；不启动 bridge、Apollo、车辆或场景。成功必须同时满足：

- 服务器通过 RPC 可读；
- 当前地图精确为 Town01；
- 检查结束前服务器仍存活；
- 能正常关闭且没有 Signal 11。

失败立即回滚并关闭 V5，不再试其他渲染开关。成功才允许把同一启动方式接入 V5-B 的单变量转向闭环。

V5 新增 powered-on 上限 15 分钟，存储上限 512 MiB。

## 测试后结果

V5-A 只运行了一次。加入 `-RenderOffScreen` 后，CARLA 不再在 2 秒内退出：服务器成功启动，RPC 在 90 秒检查期间持续可读，进程存活约 95 秒，最后能够正常关闭，日志没有 `Signal 11`。这证明 V3/V4 的独立启动崩溃主因确实包含漏传官方无屏幕开关。

但当前地图始终是默认 `Town10HD_Opt`，没有变成 Town01。也就是说，把 Town01 作为打包启动脚本参数没有生效。因为冻结门槛要求地图必须精确为 Town01，V5-A 仍判失败，V5-B 转向闭环没有运行。

真实环境已恢复到 V5 前的 G0 启动方式；CARLA、bridge 和 Apollo 均已关闭。V5 终态为 `D0_MODIFY_INFRA`，但保留一个已经证实的基础设施结论：独立启动必须显式使用 `-RenderOffScreen`。

后续若建立新合同，只能使用 CARLA 0.9.15 官方支持的客户端 `load_world('Town01')`，并且必须在启动 bridge 和 Apollo 之前单独完成、检查和稳定等待；不能再重复命令行预载地图路线。
