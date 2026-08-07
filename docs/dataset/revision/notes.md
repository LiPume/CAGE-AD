# Notes: CAGE-AD D0 数据生成协议证据

## Repository baseline

- Remote: `git@github.com:LiPume/CAGE-AD.git`
- Starting commit: `ff8a17c`
- Working branch: `codex/dataset-generation-protocol`
- Existing claim: D0-A0 当前仅 2/12 scientific gates 完成，终态为 `MODIFY_INFRA`。

## Current generator audit

- 当前 12 条由 `ScenarioKind(2) × FaultMechanism(6) × seed=0` 笛卡尔积自动展开，不存在逐 episode 的声明式参数表；`scenarios.yaml` 和 `faults.yaml` 只列 ID，真正参数硬编码在 Python。
- 两个场景共用 Town01 同一直线路由。Lead：30 m 前车、5 m/s、6 s 后以 3 m/s² 停车；Cut-in：25 m 前方、横向 -3.5 m、3 m/s，3 s 后横向速度按 0.6 m/s² 增至 1.5 m/s。
- 六种 fault 强度硬编码：prediction 2 s stale/75° bias；planning 至少 10 m/s 或 `3v+3`；control 3.5 s delay 或油门 `2.5x+20` 且 brake=0。
- 每条 episode 统一使用 7 个 companion：nominal、3 fault repeats、3 domain probes；所有 probe 固定从 6 s 开始持续 10 s，没有基于 scenario conflict onset 定义 intervention window。
- `task_failure` 将 collision、TTC<2.5、route failure、motion failure 合并为一个布尔值。route/motion 基础设施失败与安全失败可能被同一标签吸收。
- 正确域 probe 只与 `fault_repeat_0` 的任务失败比较，不比较 paired no-probe trajectory、事件时间或同一 seed 的差值幅度；wrong-domain false repair 不进入 episode PASS 条件。
- 预测 probe 使用 constant velocity，无法修复本身就是加减速/切入的 scenario truth；规划 probe只修改 v/a 不重积分 path/time；control probe强制直行刹车，可能在切入场景引入与责任域无关的安全效果。
- 机制确认依赖单一代理量：prediction 统一看 horizon endpoint displacement、planning 看 mean max speed、control delay 看 release count、gain 看 throttle；未针对机制定义可区分的 effect signature。
- D0-A0 v3：33/36 有注入信号，但仅 16/36 同时任务失败；5/12 获得 2/3 fault votes；2/12 正确域 probe repair；1 次 wrong-domain false repair；最终 2/12 PASS。

## Root cause of poor data quality

当前主要不是“样本太少”，而是生成协议未满足四个条件：

1. scenario exposure：场景必须让相应 semantic error 位于决策敏感区；
2. fault activation：注入必须改变对应边界量且不破坏消息语法/栈运行；
3. outcome causality：故障相对 nominal 必须造成配对安全/任务退化；
4. selective intervention：正确域 intervention 应显著恢复，而错误域不应同样恢复。

扩大 seed 只会复制当前构造缺陷，必须先改为逐 episode recipe 和分层质量 gate。

## Evidence ledger

后续按“论文事实 / artifact 事实 / 当前代码事实 / 设计推导”四类记录，避免把推导写成论文原始协议。

### HINT（正文事实）

- Apollo 9.0 + CARLA 0.9.14；benchmark 共 72 cases，其中 63 个 injected faults、9 个历史真实 bug。
- injected faults 按 Control/Planning/Prediction 分别为 19/25/19；真实 bug 分别为 1/5/3。
- 故障构造使用旧版本函数替换或 synthetic semantic fault；只保留 reference ADS 通过且 faulty ADS 失败的配对 case。
- 每个保留 case 至少重复运行 3 次，并由两名有经验开发者检查 runtime log，确认 faulty code 确实触发相应行为。
- failure oracle 覆盖 collision、traffic-rule violation、task-completion failure；fault-triggering behavior 到系统失败可有最多 5 s 延迟。
- 对 CAGE-AD 的直接约束：必须做 pass→fail 配对筛选、至少 3 次重复、显式 trigger-to-failure window，不能用单次碰撞作为有效样本。

### Minimal Grey Box（正文 + artifact 事实）

- Apollo–VTD 构造 6 类交互场景：3 类无保护左转和 3 类直行交互，交互方向分别来自对向/左侧/右侧。
- 共测试 1,099 条轨迹；清洗时删除重复数据、Apollo crash 和未正常启动数据，并要求训练数据 simulation time 大于 1 分钟。
- 主文没有完整披露所谓 4D fault space 的精确坐标。
- artifact 中每次注入显式记录 `inject_frame`、`fault_frames`、`fault_type` 和 `fault_params`。可见实例包括 control throttle/acceleration、brake、steering，以及 perception object removal、position X/Y、lane marker disappearance 等单字段/单机制注入。
- 对 CAGE-AD 的直接约束：每条 fault recipe 必须声明边界、目标字段、触发 frame/time、持续长度、参数和恢复方式；仅写一个 fault 名称不构成可复现数据。

### ADSDx（正文 + 选择性 artifact 检查事实）

- Apollo 6.0、Autoware 1.15/OpenPlanner 2.5、LGSVL 2021.2.2；将 ACAV faults 扩展到 22 种。
- DriveFuzz 运行超过 60 CPU-hours 后筛出 81 个 collision scenarios：Apollo 40、Autoware 41。保留条件为 fault-free ADS 不碰撞、可可靠重现/重放、每例有至少一个可区分事故特征（碰撞位置或角度）。
- 再加入每栈 6 个 non-ADS-responsible cases；最终 Apollo 46、Autoware 47，共 93。
- fault injection location 是 responsible-module GT；trigger condition 由注入代码的因果语义推导，再逐步改变相关属性，若合理变化可降低碰撞速度或避免事故则标注为 trigger；两名有两年以上 ADS 测试经验的作者复核每例。
- 事故同一性不只看“是否碰撞”，还看 collision object、angle、position/location 和 speed，并为 simulator nondeterminism 留容差。
- 正文明确报告 perfect prediction 有时也会消除 planning fault 的后果，造成 wrong-domain attribution；因此“某 probe 修复碰撞”不是充分根因证据。
- artifact 中的 5 个示例由原始复杂场景裁剪而来：原始场景含 10–68 个 agents 和非零天气，裁剪后仅保留 2–3 个关键 agents，并统一清除天气扰动。artifact 不是完整 93-case benchmark。
- 对 CAGE-AD 的直接约束：背景复杂度与根因验证必须分层；先在裁剪后的最小事故场景验证归因，再用复杂背景做鲁棒性，不得把天气/NPC 数量同时当 fault 变量。

### ACAV（正文事实）

- 原始 ADS 集含 110 个测试引擎生成事故：43 intersection、31 merging、36 rear-end；其中 7 个只是轻微擦碰，因精度限制没有可靠 causal event。
- fault-injection 集包含 8 个 code-level faults：2 个 prediction、6 个 planning；具体包括 ignore NPC、错误 prediction model、错误 follow/ignore/yield/overtake decision 和保持高速度等。
- 每个 fault 类型运行测试引擎约 1 天，使用变化路线和多类型 NPC，每段记录统一 120 s，总计 1,206 个事故记录。
- ACAV 以 causal event 持续时间判断主因，且承认 planning fault 常伴随 2–3 个相关 causal events。
- 对 CAGE-AD 的直接约束：fault signature 要按机制定义并带时间区间，不能用所有 fault 共用一个代理量；多事件传播应记录而非强压成单一布尔标签。

### ROCAS（正文事实）

- 从已有文献收集 184 个已确认事故，删除不可由外部场景利用及纯性能问题后保留 144 个，按行为、后果和事故场景归为 12 类。
- physical mutation 要求事故被消除，同时事故前 actor trajectories 与原执行保持相似；否则把所有 actor 速度设为 0 就会形成无意义“修复”。
- cyber mutation 同样要求事故被消除且 ADS 在事故场景前的轨迹保持相似；搜索最小配置变化。
- 另构造 200 条由原执行小扰动得到的 regression cases，检查修复配置没有引入新危险行为。
- 对 CAGE-AD 的直接约束：所有 intervention 必须有 pre-intervention trajectory similarity 和 minimality 条件；“强制停车”不能自动算有效反事实。

### MoDitector（正文事实）

- MICS 定义要求系统失败、目标模块出错，且 collision effect window 内其他模块不出错；多模块同时出错的 case 不被强行作为单模块 GT。
- 4 个基础场景来自 NHTSA pre-crash typology；CARLA synchronized mode；每个实验用不同 seed 重复 3 次。
- 模块注入预实验从 100 个正常场景抽样，对 perception/prediction/planning 分别使用三档强度并重复 3 次，显示常规/中等模块误差经常不足以触发系统失败。
- oracle 复核通过从首次模块错误时刻开始替换 perfect/safe output；prediction/perception repair rate 约 89%，并非 100%，说明上游修复不保证下游安全。
- 对 CAGE-AD 的直接约束：必须分开判断 module error、system failure 和单模块可归因性；不能因为注入信号存在就把数据当成诊断样本。

## Design deductions（不是论文原始设定）

- D0-A0 下一版改为两阶段：development/calibration 负责 scenario exposure 与 fault dose search；formal split 只使用冻结 recipe 和 held-out seeds。
- 12 条 pilot 不再代表 2×6 的机械笛卡尔积，而是 6 个 fault archetype 各自绑定 2 个有暴露能力的 scenario variants。
- 每个正式条件至少 3 次重复；runtime validity、nominal correctness、fault activation、system degradation、counterfactual selectivity 分开打 gate。
- fault dose 使用预声明从弱到强的网格，选“满足 gate 的最小剂量”，不能在查看 held-out 结果后调参。
- correct-domain probe 只有在保持事故前轨迹相似、改善显著超过 wrong-domain probes 时才构成 identifiable evidence；否则进入 ambiguous/abstention pool，不得改标签或删除。
- route failure、Apollo startup failure、actor spawn failure 属于 infrastructure invalid，不是 safety failure。

## Open issues

- 需要在 Apollo 10 runtime 上实测新 scenario templates 的 nominal sensitivity envelope；本地只能冻结流程和候选参数，不能声称数值已通过。
- 新 planning trajectory transformation 必须在服务器实现后验证 `x/y/s/v/a/relative_time` 一致性，任何字段不一致都应判 injector invalid。
- history-only forecasting、independent safety planner 和 tracking controller 三类 probe 需要在 held-out fault-free regression set 上测副作用率。

## Fresh-reader test and resolutions

无上下文审阅者能正确还原 CAL-F01 的 scenario candidate、seed、dose、trigger window、probe 和 formal freeze
流程，但指出五类高风险歧义。已在当前版本处理：

1. 用 `episode_recipes.yaml:normative_nested_search` 建立唯一嵌套搜索：nominal fail 才换 candidate；dose pre-probe
   gate fail 才继续更强 dose；一旦找到第一个因果有效 dose 就停止全部 candidate/dose 搜索并进入 probe 分类。
2. 为 prediction FIFO 补全 Apollo input/output topic、protobuf、整消息 prebuffer、source time、header/timestamp、
   warmup failure、稳定队列顺序和 window-end clear 语义。
3. 为场景补全 ego-local center offset、spawn rotation/z、analytic velocity、固定 weather/background、fresh world/reset、
   seed propagation 和实现 source hash 要求。
4. 为所有分类组合增加有优先级的 complete decision tree，并把 selectivity 的等号边界统一为
   `correct - best_wrong > 0.10` 才 identifiable。
5. 固化 OBB TTC、module-error/degradation onset；要求服务器为 null/等号/window/terminal states 建 golden fixtures。

仍然必须由服务器实证而非本地文档声称的部分：Apollo 10 nominal sensitivity、各 transformer 的真实 protobuf
一致性、probe regression harm 和每个 recipe 的最终分类。
