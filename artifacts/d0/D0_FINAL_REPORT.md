# Apollo 10 D0 最终报告

最终状态：**D0_MODIFY_INFRA（需要重新设计实验基础设施）**

停止位置：D0-2 benchmark smoke

正式修复版 batch：`d0_a0_repaired_v3`

完成日期：2026-08-06

## 一句话结论

Apollo 和 CARLA 已经能够稳定、可恢复地生成数据，但当前设计的故障和排查 probe 还不能稳定形成“可以判断责任模块”的诊断题。修复版 12 道题只有 2 道通过，因此没有继续生成 36 道正式题，也没有比较普通算法、Single-Agent 或 Multi-Agent。

## 为什么是 D0_MODIFY_INFRA

完整实验要求一条诊断题同时满足：

1. 没有故障时车辆正常；
2. 同一故障重复 3 次，至少 2 次确实激活并造成预先定义的驾驶失败；
3. 对正确责任域实施不使用 GT 的 probe 后，失败应当消失；
4. 诊断可见数据中不能泄漏真实故障标签。

修复版虽然完成了全部 84 次配套运行，但只有 2/12 个 episode 同时满足这些条件。v2 的 0/12 结果已经触发过唯一一次允许的机制级修复；如果再调强故障、放松阈值或改变 evaluator，就不再是同一个预注册实验。因此诚实终态只能是 `D0_MODIFY_INFRA`。

## Gate 完成情况

| Gate | 结果 | 说明 |
|---|---|---|
| G0 source-only checkpoint | PASS | `1fa6fb1`，已推送远端 |
| D0-1 合同、状态、预算和 verifier | PASS | `51f7ba0`，typed gate、ledger、恢复与隔离测试通过 |
| D0-2 benchmark 实现 | PASS | `9ae1bfa`，两个场景、六种故障、O0-O3 和 I2-F/P/C |
| D0-2 运行生命周期修复 | PASS | `a08859d`，每次运行使用 fresh CARLA，可恢复执行 |
| D0-2 formal v2 科学结果 | FAIL | 84/84 次运行有效，但 0/12 题通过；完整保留 |
| 唯一一次机制级修复 | 已执行 | `edf09c6`；未改标签、split、预算、阈值或 evaluator |
| D0-2 repaired v3 运行 | PASS | 一次无效启动被归档并原配置重试后，当前 84/84 有效 |
| D0-2 repaired v3 科学结果 | FAIL | 2/12 通过，visible oracle 泄漏为 0 |
| D0-3 至 D0-6 | 未运行 | 主数据集无效，继续比较算法没有科学意义 |

## v3 的准确身份

- 执行源码：`edf09c6af0a1de2e6d68c35ce0abbebc0f2a9df8`；
- 配置 SHA-256：`6bfe98a2611b44cfc8d8a4504a44397853ec97f09ba36d30884e1d08eb6e526a`；
- plan SHA-256：`b496234a10871cf7d26dc52219bac8164a25a5e905308d1c7540b942c08a2112`；
- execution SHA-256：`1aa5de1cae27da1b60999c0b59479d6a2ddbb2b794735a032c3505a303b7cc5c`；
- evaluation SHA-256：`956b3f65833aced0104734d3011c1d5ad53e3d53fc4883db6034f396f002055a`。

数据集文档翻译后会重新生成 public manifest，其最终 SHA 以 `FINAL_ARTIFACT_CHECKSUMS.sha256` 为准。

## 数字结果

| 检查项 | 结果 |
|---|---:|
| 独立诊断 episode | 12 |
| 当前有效配套运行 | 84/84 |
| 正常场景有效 | 12/12 |
| 故障重复运行有效 | 36/36 |
| 确认出现故障机制信号 | 33/36 |
| 同时满足机制信号和任务失败 | 16/36 |
| 至少获得 2/3 有效故障票的 episode | 5/12 |
| 正确责任域 probe 修复成功 | 2/12 |
| 错误责任域也产生修复的次数 | 1 |
| 可见数据中的 oracle token 泄漏 | 0 |
| 完整科学 gate 通过 | **2/12** |

通过的两题都是切入场景，分别为 `planning_unsafe_cost_or_speed_bias` 和 `control_gain_saturation_tracking_bias`。其中规划题还出现了一次错误责任域 probe 也能“修好”的情况，说明因果选择性仍然不足。

预测朝向偏置在 6/6 次重复中都能观察到注入信号，却 0 次造成冻结定义下的任务失败。控制传输延迟也在 6/6 次中出现机制信号，却 0 次造成任务失败。两个 `planning_constraint_omitted` episode 都稳定造成失败，但正确的规划 probe 没有把失败消除。前车场景的控制增益故障也有同样问题。

## 无效运行和重试

v3 有一次 forecasting probe 完整运行了 32.05 秒，但 Apollo 没有成功初始化 route/planning，车辆完全没动。这次被记为 `D0-2-RUNTIME-007`，不算科学负例。重试前，status、checkpoint、private metrics、场景/interposer stats 和语义 capture 都复制到了 `invalid_attempts/attempt_1` 并计算校验和。随后用完全相同的 run ID、源码和配置重试并通过；已经 PASS 的 intervention 没有重复执行。

## 资源使用

- 估算 powered-on 时间：7.28 小时，上限 30 小时；
- 增量存储：约 17.72 GiB，上限 100 GiB；
- 结束时 Apollo、CARLA、bridge 和 batch 进程均已停止；
- evaluator-private 根目录权限保持 `0700`。

## 为什么没有继续跑 Agent

D0-3 的前提是先得到一个科学上有效的 smoke generator。当前多数故障信号要么没有造成预定义任务失败，要么正确域 probe 无法选择性地消除失败。此时扩展到 36 个 episode 只会复制有问题的诊断题；继续比较 fixed、greedy、Single-Agent 或 Multi-Agent 可能奖励数据伪影，不能检验原假设。

这不是缺少 API key、预算或许可证导致的暂停，而是科学依赖条件没有满足。

## 未来修改必须遵守的边界

未来如果继续，必须注册为新的基础设施版本，重新设计场景、故障和 probe 的因果作用范围，在查看正式结果前冻结新规则，并完整保留 v2/v3 作为失败 pilot。不得重新标注本批 episode，也不得用放松后的阈值重新解释当前结果。
