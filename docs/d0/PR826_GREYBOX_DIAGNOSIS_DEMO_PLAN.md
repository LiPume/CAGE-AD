# PR826 灰盒主动诊断与双栏动画 Demo 实施方案

> 状态：STABLE_REFERENCE_ADMITTED（P2 normal-only configured reference 已通过冻结的 3/3 门槛）
> 冻结日期：2026-08-29
> 目标平台：Apollo 10 host mode + CARLA 0.9.15
> 产品定位：AI Diagnosis Copilot，而非代码修复 Agent，也不是另一个 HINT
> 事实标记：VERIFIED / INFERRED / PROVISIONAL / UNKNOWN

## 1. 最终交付物

本轨道最终只承诺以下核心输出：

1. 一对可重复的 fixed / faulty Apollo 10–CARLA 运行；
2. 一个可审计的灰盒诊断过程：假设、动作、证据、成本、belief 更新和停止理由；
3. 一份工程师可执行的报告，定位到责任域/原生模块、异常接口、可疑语义信号、证据链和下一检查方向；
4. 一个同步双栏动画 Demo：左侧为 CARLA/BEV 行为，右侧为逐步诊断录制；
5. 可重放脚本、run manifest、版本/资源/成本/失败账本和 oracle-isolation 证据。

核心报告不要求源码、函数或代码行。FilterLaneSequences 只属于 benchmark 构造侧的隐藏
ground truth，以及企业明确授权 L3 源码时的可选 drill-down。

目标报告应包含：

    Failure: Ego 未完成预期超车
    Responsibility domain: interaction forecasting
    Root-cause module: Prediction
    Suspicious interface: Prediction -> Planning
    Suspicious signal: lead NPC predicted trajectories
    Observed mismatch: predicted trajectory 与已实现 NPC 轨迹不一致
    Propagation: Planning 在该预测输入下采取保守行为；Control 正确跟踪 Planning
    Causal probe: 非 GT 的零速运动学 prediction probe 后，Planning 行为发生预期改变
    Confidence / prediction set: 由校准器给出，不使用 LLM 自报置信度
    Engineer next checks: lane-sequence filtering / candidate selection / trajectory generation
    Stop reason: risk met / no valuable action / budget / abstain / tool failure

## 2. 明确不做什么

- 不自动修改或提交 Apollo 修复；
- 不把代码级定位作为论文核心指标；
- 不把历史 PR、commit、patch、injector 名或 fault label 暴露给诊断路径；
- 不把 CARLA future ground truth replacement 伪装为普通 L1 观测或低权限干预；
- 不用演示手填的 0.33 -> 0.05 -> 0.95 冒充校准 posterior；
- 不用 2017 年 Apollo checkout 直接连接 CARLA 0.9.15；
- 不因一个漂亮视频放松 reference/fault/mechanism/repeatability gate；
- 不声称一个黄金案例证明 Agent 策略优于 fixed/rule/greedy Bayesian。

## 3. 一手来源核验结果

### 3.1 HINT 论文与 PR826

- HINT v1 于 2026-07-14 发布。论文将 PR826 作为 motivating example：近乎静止的
  lead NPC 被 Prediction 赋予错误轨迹，Planning 因而保守，形成 failed overtake；论文称
  根因函数为 FilterLaneSequences。[VERIFIED]
  - https://arxiv.org/html/2607.12598
- HINT 使用 Apollo 9.0、CARLA 0.9.14、Ubuntu 22.04 和 RTX 4090；benchmark admission
  要求 reference pass、faulty fail、至少三次运行、开发者确认机制激活，且当前数据的
  activation-to-failure 延迟不超过 5 秒。[VERIFIED]
- Apollo PR #826 于 2017-10-25 合并，PR 页面显示一个修复 commit。[VERIFIED]
  - https://github.com/ApolloAuto/apollo/pull/826
- commit 92b7434c4656555d8350fc051e5d1d5c32897db6 只改动
  modules/prediction/predictor/sequence/sequence_predictor.cc，核心变更是在
  GetLaneChangeDistanceWithADC(...) 小于 FLAGS_lane_change_dist 之外增加 LEFT/RIGHT
  lane-change 类型约束。[VERIFIED]
  - https://github.com/ApolloAuto/apollo/commit/92b7434c4656555d8350fc051e5d1d5c32897db6

### 3.2 HINT replication package 审计

论文指向 Zenodo FL4ADS replication package：

- DOI：10.5281/zenodo.19235927
- 唯一归档：HINT.zip
- 大小：8,689,239,451 bytes
- MD5：8e575fc77d7acb9efa80860e7cdac3c5

本次没有下载整包。使用 HTTP Range 只读取 ZIP64 end record 和 50,256-byte central
directory，共发现 360 个条目和 12 个 scene 目录。中央目录缓存为：

    runtime/cache/downloads/HINT.zip.central-directory.bin
    sha256=79f00d36f1352d506b2baf93a3b8fc1f3715b40bd92e340cafa256c8e937e18c

公开包确实包含 scene1 README、YAML 和 record；scene1.record 压缩大小为
40,172,122 bytes，解压大小为 139,234,933 bytes。

本次已用 range requests 只提取该单条 record，并按存储合同保存到：

    runtime/raw/pr826_greybox_demo_v1/hint_public_scene1/scene1.record
    sha256=b2d974190f8d1645d33218a2f6f78d890837a5ef8bfb0f9aa1936b55b7ad59f1

Apollo 10 `cyber_recorder info` 确认它完整可读：46.218074 秒、73,260 条消息、37 个
channels。其中 `/apollo/perception/obstacles` 5,766 条、`/apollo/prediction` 3,984 条、
`/apollo/planning` 822 条、`/apollo/control` 4,620 条、localization/chassis 各 5,769 条。
原生回放抽样只看到 obstacle 100：它先近乎静止，随后加速并发生横向 lane transition；
Prediction 样本包含 6 秒、lane_0/lane_1 候选，Planning 后段为 lane_1 正常巡航。这更符合
公开 YAML 的 cut-in/lane-change 叙述，不足以把该 record 当成“静止前车、持续无法超车”的
matched faulty run。[VERIFIED SAMPLE, NOT A FULL CAUSAL LABEL]

但公开元数据与论文正文存在必须解决的不一致：

| 来源 | Failure | 行为描述 | 根因名字 |
|---|---|---|---|
| HINT 论文 Fig.3/正文 | failed overtake | near-stationary lead NPC 的错误预测阻止超车 | FilterLaneSequences |
| scene1/README.md | Collision with NPC | 未展开 | Prediction:SequencePredictor:FilterSequence |
| scene1/scene.yaml | planning failed to avoid collision | NPC cut-in prediction 缺失 | Prediction::SequencePredictor::FilterSequence |

因此当前可以说“公开包包含一个标为 PR826 的 record”，不能说“公开 scene1 已经精确给出
论文 failed-overtake 的 CARLA spawn 参数和 Apollo 9 fault patch”。中央目录没有发现 Apollo
源码快照、PR826 patch 或按 commit 命名的 fault injection 文件。[VERIFIED]

归档顶层 README 链接的 Google Drive Benchmark Scenarios 目录已完成小文件审计。五个公开
场景均未提供论文 failed-overtake 的 Apollo 9 port patch 或精确 spawn 参数；它们仅保留为
artifact 审计支线。[VERIFIED]

### 3.3 Apollo 10 与 bridge

- Apollo 10 官方支持 Ubuntu 22.04 x86-64 host mode：aem start -b host；源码/包模式
  使用 buildtool。[VERIFIED]
  - https://apollo.baidu.com/docs/apollo/10.x/md_docs_2_xE5_xAE_x89_xE8_xA3_x85_xE6_x8C_x87_xE5_x8D_x97_2_xE5_xAE_x89_xE8_xA3_x85_xE6_x8C_x87_xE5_x8D_x97.html
- Apollo 10 Prediction 官方定义为 Perception 输入到 predicted trajectories，再供 Planning
  使用；内部包含 Container/Scenario/Evaluator/Predictor。[VERIFIED]
  - https://apollo.baidu.com/docs/apollo/10.x/md_collection_2prediction_2README__cn.html
- 当前 application-pnc/core/cyberfile.xml 已依赖 prediction，本地安装有 Prediction DAG、
  libprediction_component.so 和 source package。[VERIFIED]
- 当前 Apollo 10 FilterLaneSequences 已包含 parking、lane type、signed ADC distance、
  obstacle polygon within own lane 等额外逻辑，不能机械粘贴 2017 两行代码。[VERIFIED]
- guardstrikelab bridge 的公开 README 实际只声明测试过 CARLA 0.9.14 + Apollo 8.0.0，
  license 为 Apache-2.0；当前 G0 的 Apollo 10 能力来自 pinned upstream 加本地适配和验证。
  - https://github.com/guardstrikelab/carla_apollo_bridge

## 4. 系统边界与数据隔离

    Benchmark builder, private/oracle side
      historical PR/commit + semantic port patch + injector telemetry + fault label
                             |
                             v
    Diagnosis adapter, visible L0/L1/L2 side
      failure window + realized actor motion + predicted actors + motion plan
      + control target + vehicle response + action catalog + cost
                             |
                             v
    Active diagnosis controller
      belief -> legal action -> verified evidence -> update -> stop/abstain
                             |
                             v
    Diagnosis report

Private evaluator 才能读取 run mapping、semantic patch telemetry 和 expected responsibility。
必须通过独立目录/UID 保证诊断进程不能读取 fault_type、root_module、PR/commit 标识、
injector config、fixed/faulty 映射和 future-GT 结果。文件名、scenario ID、topic 名也不能编码答案。

## 5. PR826 Apollo 10 语义移植

### 5.1 两个候选 phenotype，不混写

1. P826-A，论文一致主案例：failed overtake
   - 直路双车道；
   - lead NPC 近乎静止；
   - 相邻车道可通行；
   - route goal 足够远；
   - fixed build 完成超越；faulty build 未完成超越。
2. P826-B，公开 artifact 一致复核案例：cut-in/collision
   - 只在 scene1 record/scenario 信息足够时实现；
   - 用于解释公开包不一致，不替代 P826-A。

若只有 B 能成立，最终必须称为 artifact-consistent PR826 case。若 A 成立但没有作者 patch
对照，应称为 PR826-semantic port，不能称为 HINT exact replication。

### 5.2 Patch 规则

stock Apollo 10 为 fixed reference。faulty patch 必须：

- 只改变 nearby lane-sequence filtering 相同职责的语义；
- run-scoped 或独立 build，可一键回滚；
- 不改变 CARLA、map、route、NPC policy、bridge、Planning、Control；
- 私有记录 filter 前后 candidate ID、probability、lane-change type、ADC distance、enable mask；
- 用单元测试证明 candidate-set delta 与 patch 语义一致；
- 不以最终车辆失败反推并不断加重 fault dose。

现代实现已经通过前置 lane-type guard 区分 LEFT/RIGHT/ONTO_LANE，并在小距离时检查 obstacle
polygon 是否仍在本车道。候选 port 必须先构造函数级 fixture，证明现代 guard 变化能复现
“有效高置信候选被错误移除、剩余候选导致错误输出”，再进入 CARLA。

## 6. 场景和收录 Gate

### 6.1 参数冻结

在看到 faulty 结果前冻结 Town/map、ego/NPC spawn、lane IDs、blueprint/physics、route、NPC
policy、seed、0.05 s 步长、warm-up、failure window、camera、patch SHA 和全部 oracle。
论文没有给出这些数值，不能标为 paper parameters。

所有 normal-only screening attempt 必须在任何 fault patch 编译或 faulty run 之前分配不可变
`screening_id`，并追加写入 `reference_screening_ledger.jsonl`。每条记录至少包含完整 manifest
SHA、地图/坐标/lane/route/seed、运行时间、reference capability 指标、PASS/REJECT、机器可判定
reject code 和产物路径。淘汰记录不得删除或覆盖；选中场景时只能依据 reference capability，
不能读取尚不存在的 faulty 结果。

### 6.2 Reference gate

至少 3/3 fixed runs 满足：

- runtime valid、零非预期 frame gap、route accepted；
- 无碰撞、无非法 lane invasion；
- NPC 行为误差在冻结容差内；
- ego 进入相邻 lane、纵向超过 lead NPC，并进入预定 success region；
- 不依赖 CARLA constant-velocity API 控制 ego；
- Prediction、Planning、Control channel 覆盖率达到预注册门槛。

reference 不会超车时，先判场景/Planning 能力不成立，禁止用 fault patch 制造对比。

### 6.3 Faulty admission gate

至少 3/3 faulty runs 满足：

- 除 patch/build ID 外与 fixed manifest 相同；
- failure oracle 3/3 成立；
- private mechanism oracle 3/3 成立；
- mechanism activation 早于 failure，间隔不超过 5 秒；
- 诊断可见目录零标签泄漏；
- 两名 reviewer 或一名 reviewer加 deterministic checker 确认机制。

主 task-incompletion oracle 必须同时验证相邻 lane 可用、NPC 近静止、ego 在 deadline 前仍未
进入 pass success region，并排除 collision 等替代解释。数值在第一次正式 run 前由
normal-only pilot 冻结。

## 7. 灰盒诊断动作

以下是 action catalog，不是固定故障树。controller 每步按 expected information gain 与 cost
选择动作。

| ID | 动作 | 权限 | 类型 | 目的 |
|---|---|---|---|---|
| O0 | failure window/ego/actor realized motion | L0 | observation | 建立候选 |
| O1-C | control tracking check | L1 | query | 区分控制源故障与执行上游命令 |
| O1-P | planning consistency check | L1 | query | 判断保守规划能否被预测输入解释 |
| O1-F | prediction fidelity check | L1 | query | ADE/FDE/heading/maneuver mismatch |
| O2-T | native timing/dependency window | L2 | query | 排除 stale/delay/transport |
| I2-K | 零速/常速度运动学 prediction probe | R2 | non-GT intervention | 切断错误预测传播 |
| I3-GT | CARLA future-GT replacement | R2 upper bound | strong intervention | 仅作因果上界 |

I2-K 只使用 intervention 时刻已经可见的 actor state，按冻结运动学模型外推，不读取未来
CARLA 轨迹。I3-GT 必须单列，不能成为核心方法必需步骤。

### 7.1 冻结 cost function

每个动作同时报告四个原始成本分量，禁止只报一个无单位分数：

- `wall_time_sec`：从 action accepted 到 evidence committed 的实测墙钟时间；
- `simulation_class`：0=只读既有 record，1=离线 replay，2=新跑仿真，3=新跑干预仿真；
- `access_rank`：0=L0，1=L1，2=L2，3=R2/private-oracle；
- `intervention_risk_rank`：0=只读，1=shadow/identity，2=单一 semantic-slot 可逆修改，
  3=多字段或 future-GT replacement。

controller 使用以下预注册归一化成本，不把它宣称为最优或通用经济模型：

    t = min(wall_time_sec / 60, 1)
    C(a) = 0.25*t + 0.30*(simulation_class/3)
           + 0.20*(access_rank/3) + 0.25*(intervention_risk_rank/3)

动作排序使用 `expected_information_gain / max(C(a), 0.05)`，同时受四个原始分量的 hard budget
约束。报告必须并列给出 raw vector、scalar、权重版本和实测值；权重敏感性只作离线分析，
不得为当前 case 调权。缓存命中仍报告原始访问等级，但墙钟时间按实际值记录。

### 7.2 I2-K 最小干预 admission gate

I2-K 不允许整包重建 Prediction message。对于目标 obstacle，必须保持 message header、frame、
sequence/timestamp、obstacle ID 和顺序、obstacle 数量、目标/非目标 obstacle metadata、trajectory
数量、probability、relative-time grid、lane-id schema 与发布频率不变；只允许修改白名单中的
trajectory point position/heading/velocity/acceleration semantics。零速模型固定首点位置和 lane，
常速度模型只使用干预时刻可见状态外推。

在 I2-K 可用于任何因果结论前，以下全部是 admission gate，而不是普通测试：

1. field-diff verifier 证明差异只落在冻结白名单；
2. identity probe 序列化等价且 3/3 无行为差异；
3. wrong-domain probe 3/3 不改变目标 failure；
4. I2-K 3/3 通过 rate/age/count/ID/timestamp 和非目标 obstacle side-effect audit；
5. 任一项失败则 intervention evidence 标为 `INVALID_INTERVENTION`，不得更新根因分数。

每条 evidence 必须包含 opaque evidence_id、semantic slot/time window、native provenance、
checksum、tool status、unit/frame/alignment、access、measured cost、side effects 以及支持/反驳
的假设。

Demo 中的概率只允许来自独立 calibration episodes 上冻结的 likelihood/posterior；否则显示
uncalibrated suspicion score 或 prediction set。LLM 只组织动作提议和报告，不写最终 posterior。

## 8. 停止与结果边界

停止条件包括 calibrated risk 达标、prediction set 达标、没有有价值可负担动作、预算耗尽、
工具失败或当前权限不可辨识。即使 I3-GT 消除 failure，也只能说明被替换语义具有因果作用；
replacement 改变多个字段或有副作用时，必须保留 alternative explanation。

## 9. 动画 Demo

最终视频建议 1920x1080、30 fps、60–90 秒：

| 左栏 | 右栏 |
|---|---|
| CARLA chase camera / BEV | Active Diagnosis Console |
| ego、NPC、lane、route | failure window |
| realized 与 predicted trajectories | candidate set / belief |
| planned ego trajectory | selected action + cost |
| fixed/faulty/probe 对照 | evidence/verifier/final report |

所有动画从冻结 record 按 simulator timestamp 离线渲染，不在录屏时临时调用 LLM 或重跑随机
场景。建议分镜：

1. 0–8 s：正常预期与 faulty 症状；
2. 8–18 s：O0 建立候选；
3. 18–30 s：Control tracking evidence；
4. 30–42 s：Planning propagated response；
5. 42–56 s：Prediction fidelity mismatch；
6. 56–70 s：I2-K probe 对照；
7. 70–82 s：灰盒 Diagnosis Report；
8. 82–90 s：虚线 optional L3 卡片，明确不属于核心输入。

产物包括 fixed/faulty/probe 视频、diagnosis_trace.jsonl、overlay_timeline.json、report JSON/MD、
最终 H.264、run manifests、SHA256 和渲染命令。

## 10. 分阶段 Gate

| Phase | 产物 | PASS Gate | 失败时动作 |
|---|---|---|---|
| P0 研究与计划 | 本文、TODO、artifact audit | 边界/事实/未知项分开 | 回到来源核验 |
| P1 Prediction bring-up | stock Prediction smoke | channel/map/rate/trajectory | 修接口，不碰 patch |
| P2 normal-only scene | P826-A reference | 3/3 完成超车 | 改场景能力，不改 oracle |
| P3 semantic fixture | unit fixture + private telemetry | candidate delta 符合 PR 语义 | 淘汰 patch 假设 |
| P4 matched runs | fixed/faulty manifests | reference/fault/mechanism 均 3/3 | 淘汰 scene–fault pair |
| P5 gray-box tools | O0/O1/O2 | schema/cost/no leakage | 修 adapter/verifier |
| P6 interventions | I2-K，I3 可选 | side effects 可测、3 repeats | observation-only/abstain |
| P7 controller/report | action trace/report | 校准/拒答/evidence refs | 不显示伪概率 |
| P8 video | 双栏同步成片 | timestamps/content/checksum | 重渲染，不重写结果 |
| P9 final audit | runbook/report/ledgers | replay/repeats/secret/oracle scan | 保持未完成 |

## 11. 当前测试与问题

### P2-D / P2-V2 最终结果（2026-08-29）

- 初始 Town01 RF01 静态前车案例仍永久保留为 `CASE_NOT_ADMITTED`：首次正式重复未超车，
  且 target Prediction trajectory coverage 为 0，不能作为 Prediction → Planning 案例。
- P2-D 将差异定位到 Planning 可用轨迹和 lane-borrow/route execution 分叉，并同时确认完全
  静止目标主要走 static-obstacle Planning 语义；因此没有继续用 RF01 调阈值制造成功。
- P2-V2 最终冻结候选为
  `RF04_13_SLOW_110_LANE_TANGENT_LC_LONG_80S_MAP_WIDTH_V1_CTRL_V17`：Town04、目标速度
  1.10 m/s、stock Prediction/Planning、metadata-corrected HD map、V17 Control calibration。
- 冻结合同之后连续三次正式运行均为 `SCREENING_PASS`；Prediction trajectory coverage
  分别为 0.9839、0.9870、0.9870，Planning valid ratio 分别为 0.9477、0.9551、0.9415，
  三次均无碰撞、无非法 lane invasion，并完成超越和 success-region 到达。
- 机器审计、冻结合同、失败场景账本、修复账本和最终报告已纳入
  `benchmarks/apollo_d0/pr826_reference_v1/` 与 `docs/d0/evidence/pr826_reference_v1/`。
- 本阶段没有创建 fault patch、matched faulty run、诊断 Agent 或动画。

### DeepSeek

- key 存储于 workspace 外 /root/.config/cage-ad/deepseek.env；目录 0700、文件 0600；
- bundle 内没有新增真实 .env；
- deepseek-v4-pro + Chat Completions + json_object 最小调用 PASS；
- 用量 38 prompt + 5 completion = 43 tokens；
- key 值不写入本文、manifest 或日志。

### 现有 Apollo 场景烟测，不是 PR826

恢复并验收了一份此前未写回状态的 20 秒 no-NPC Apollo–CARLA run：

- 400 frames、0 gaps、route accepted、0 NPC；
- 最大车速 4.191 m/s、tracking ratio 1.017；
- bridge gain max error 2.16e-8、横向偏差 0.115 m；
- Planning coverage 0.9075，低于 0.95；
- brake active fraction 0.13，高于 0.10；
- stack log 含 56 条 Piecewise jerk speed optimizer failed。

因此该 run 按冻结合同 FAIL，不能成为后续前置 PASS，也与 PR826 无关。

evaluator 曾用大小写敏感字符串漏掉真实日志表达。现已改成 case-insensitive recognized
failure patterns，并新增回归测试；相关定向测试 6/6 PASS。修复后该 run 有三项失败：
planning coverage、brake fraction、speed optimizer failures。

### HINT scene1 record 兼容性烟测

- 单条 record 的 range 提取、SHA256 和 `cyber_recorder info` 均 PASS；
- Apollo 10 Python `RecordReader` 在构造 reader 时触发
  `PY_SSIZE_T_CLEAN macro must be defined for '#' formats`，因此不能把它作为离线解析器；
- 改用 CyberRT 原生 replay/echo 后，Perception、Prediction、Planning 和 Localization 均能解码；
- 非 TTY 回放会产生大量终端控制警告，后续正式 extractor 应使用独立 subscriber 并将 player
  stdout/stderr 限流到日志文件；
- 本次抽样进一步支持“公开 scene1 不是论文图中纯 failed-overtake phenotype”的风险判断，
  但没有据此虚构 collision timestamp 或 causal diagnosis。

### 最高风险

1. 论文与公开 scene1 的 failure/function 名不一致；
2. 作者 Apollo 9 port patch 未从归档中央目录中发现；
3. stock Apollo 10 在冻结 RF01_01 中一次完成超车、首次预注册重复未完成，稳定 reference
   能力不成立；该 scene 已触发 `CASE_NOT_ADMITTED`；
4. 现代 filtering guard 已重构，fault port 需要 fixture 证明；
5. bridge pseudo-object feed 是 CARLA truth，必须隔离 diagnosis realized motion 与 evaluator future GT；
6. 单一 case 无法校准 posterior，Demo 可能只能显示 prediction set；
7. I2-K 行为改变可能来自 side effect，必须有 identity/wrong-domain controls；
8. 视频必须最后从冻结 records 生成。
9. Apollo 10 随包 Python RecordReader 与当前 Python ABI 不兼容，需要原生 subscriber extractor。

## 12. 待用户审核的默认选择

1. 核心交付是 gray-box Diagnosis Report；代码 drill-down 为虚线 optional；
2. 主案例是论文一致的 P826-A failed overtake；artifact cut-in/collision 作为并行审计；
3. 核心 mixed-action 使用 non-GT I2-K，future-GT I3 仅作上界；
4. 无校准集前不显示伪精确 posterior；
5. reference 不能稳定超车时诚实结束为 CASE_NOT_ADMITTED；
6. 审核通过后先做 P1 Prediction bring-up 和 P2 normal-only reference，不先写 fault patch。
