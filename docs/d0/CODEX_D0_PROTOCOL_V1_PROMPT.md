# Apollo 10 D0 数据协议 v1 持续实现 Prompt

把下面整段粘贴给 AutoDL 服务器上的 Codex。它只替换旧 D0 Prompt 的“数据生成、D0-2、D0-3”部分；
contracts、预算、oracle 隔离、Agent/Baseline 公平性和 source-only Git 边界继续有效。

```text
你是 CAGE-AD Apollo 10 数据协议 v1 的持续执行 Codex。你的目标不是快速制造一批碰撞，也不是让当前方法取得正结果，而是把仓库中的逐 recipe 生成合同实现为可恢复、可审计、无标签泄漏的数据流水线，并一直执行到 12 个 calibration recipes 全部得到 identifiable、ambiguous 或 rejected 的诚实终态。

一、同步与优先级

1. 在持久盘上的 CAGE-AD Git root 执行只读检查，确认 origin 精确为 git@github.com:LiPume/CAGE-AD.git，保存当前 branch、commit 和 dirty status；不得覆盖未提交修改。
2. 获取远端最新 main，基于包含 `benchmarks/apollo_d0/protocol_v1/` 的 commit 创建或切换工作分支 `codex/apollo-d0-protocol-v1`。若有本地修改冲突，保留修改并写 `USER_ACTION_REQUIRED_GIT.md`，不要 reset/checkout 丢数据。
3. 完整读取：
   - benchmarks/apollo_d0/protocol_v1/README.md
   - benchmarks/apollo_d0/protocol_v1/literature_provenance.yaml
   - benchmarks/apollo_d0/protocol_v1/scenario_recipes.yaml
   - benchmarks/apollo_d0/protocol_v1/fault_recipes.yaml
   - benchmarks/apollo_d0/protocol_v1/probe_recipes.yaml
   - benchmarks/apollo_d0/protocol_v1/episode_recipes.yaml
   - benchmarks/apollo_d0/protocol_v1/quality_gates.yaml
   - docs/dataset/CAGE_AD_D0_GENERATION_PROTOCOL.md
   - contracts/d0/DatasetGenerationRecipes.schema.json
   - tests/d0/test_dataset_generation_protocol.py
   - artifacts/d0/D0_FINAL_REPORT.md
   - 现有 generator、interposer、evaluator、run state、G0 report 和 runtime scripts。
4. `docs/d0/CODEX_D0_IMPLEMENTATION_PROMPT.md` 与 `D0_ACTIVE_DIAGNOSIS_SYSTEM_DESIGN.md` 是有 SHA-256 的历史 checkpoint，不得修改。它们关于 12→36 笛卡尔积的段落已被 protocol v1 取代；其他安全、预算、Git 和评测边界仍有效。

二、持久盘与数据边界

保持现有 APOLLO_GO runtime 不动，并设置：

  CAGE_RUNTIME_ROOT=<现有G0 bundle>/runtime
  CAGE_STATE_ROOT=<现有G0 bundle>/runtime_state/d0_protocol_v1
  CAGE_DATA_ROOT=/root/autodl-tmp/cage_ad_data
  CAGE_PRIVATE_ORACLE_ROOT=/root/autodl-tmp/cage_ad_private_oracle

Git 只保存代码、YAML、schema、small fixtures、decision/manifest 摘要和复现命令。Apollo/CARLA 二进制、Conda env、raw records、视频、完整 semantic traces 和 private oracle 不进 Git。recipe ID、fault ID、candidate、dose、trigger window、companion linkage 只能存在 private state/oracle；diagnosis-visible 文件使用 opaque ID。

三、先改实现，不运行批量实验

1. 实现 protocol loader：启动时用 JSON Schema 验证 episode registry，并交叉检查 scenario/fault reference、candidate order、dose grid、seed separation。把 `episode_recipes.yaml:normative_nested_search` 实现为唯一搜索状态机；其他文字不得另写搜索分支。验证失败就 fail closed。
2. 将 scenario 与 fault 数值从 Python hard-code 迁移为 protocol v1 YAML 驱动。旧 draft/v3 路径保留只读 provenance，不覆盖旧结果。
3. 把 evaluator 拆为五层：infrastructure_valid、mechanism_activated、safety_outcome、task_outcome、attribution_outcome。route/startup/spawn/message 缺失不得再计为 safety failure 或 fault vote。
4. 为六个 fault transformer 分别实现 fixture/unit tests：精确边界、目标字段、start/end、dose、atomic message、kinematic consistency 和 activation signature。prediction delay 必须逐项实现 YAML 的 FIFO state machine；planning transformation 必须同时验证 x/y/s/v/a/relative_time；control fault 不得添加 throttle bias 或清零 brake。
5. 实现 collision identity：counterpart、position、angle、relative speed；按 quality YAML 的 OBB TTC、onset 和 complete classification tree 实现 evaluator；为阈值等号、null TTC、window 首尾和每个 terminal state 建 golden fixtures。
6. 重做三个 probe：history-only forecasting、独立可行动力学 safety planner、独立 tracking controller。不得使用 CARLA future truth、constant-velocity 替代动态 actor、固定 60% brake 或 fault-specific 调参。
7. 实现 append-only calibration ledger。每个 attempt 开始前写 planned record，结束后写 source/config hash、精确命令、status、runtime validity、五层 metrics、资源与失败原因。中断后按 ledger 恢复，不重跑已完成有副作用的 run。
8. 关闭 Apollo/CARLA，运行全部 CPU tests、schema tests、source audit 和 leakage tests；全部通过后 commit/push `feat(d0): implement literature-grounded generation protocol`。

四、实验必须一次只做一个 recipe

严格按 CAL-F01、F02、F03、F04、P01、P02、P03、P04、C01、C02、C03、C04 顺序：

1. 从该 scenario 的 candidate 0 开始，用 seeds 1101–1105 各跑一次 nominal。按 scenario_admission 原样判定；失败才试下一个列出的 candidate。不得发明第四个 candidate。
2. 对首个 admissible candidate，从最弱 dose 开始，每档用 seeds 1101/1102/1103 各跑一次。按 activation、paired degradation、temporal causality 和 collision identity gate 判定；选择第一档通过的最小 dose。不得看 formal seed，也不得跳到更强 dose 追求明显碰撞。
3. 对 selected candidate/dose，用 seeds 1101/1102/1103 各跑一次 no-probe 与三域 probe。计算 paired effect、pre-intervention similarity、wrong-domain margin 和 fault-free regression harm。
4. 按 quality_gates.yaml 自动分类 identifiable/ambiguous/rejected。ambiguous 不改成最可能域；rejected 不删除、不换标签。
5. 输出 `$CAGE_STATE_ROOT/calibration/decisions/<recipe_id>.json` 和人类可读同名 Markdown；运行 leakage scan；commit/push `data(d0): calibrate <recipe-id>`。
6. 关闭 Apollo/CARLA，检查 powered-on hours 和存储，再进入下一 recipe。

五、暂停与继续条件

- 仅当 12 个 recipes 均有终态、全部 attempt 可追溯、CPU tests 与 leakage audit 通过，才汇总 `D0_PROTOCOL_V1_CALIBRATION_REPORT.md`。
- 不要因为某 recipe rejected 就停；按协议继续下一个。只有外部凭据、付费预算、许可证、持久盘不足或破坏性操作确需用户授权时，写单一 `USER_ACTION_REQUIRED.md` 并只暂停受影响步骤。
- calibration 结束后不要自动跑 formal seeds。先提交一份 freeze proposal，列出通过 parents、selected candidate/dose/window/hash、ambiguous/rejected 分布、预计 formal runs/小时/空间和能否支持 abstention。等待用户或主研究任务确认后，才进入 held-out generation。
- 不开始 Autoware，不运行 Agent/baselines，不为凑 36 条复制数据，不修改 protocol v1 gate 来提高通过率。若规范本身必须修改，创建 protocol v2 和新分支，绝不覆盖 v1。

现在开始：先同步包含 protocol v1 的最新仓库，完成只读现状审计和实现差距表；随后持续实现、离线验证，并从 CAL-F01 开始逐 recipe 校准，直到满足上述暂停条件。
```
