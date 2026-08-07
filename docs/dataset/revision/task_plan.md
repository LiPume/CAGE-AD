# Task Plan: CAGE-AD D0 数据生成协议重构

## Goal

基于本地核心论文正文、已下载 artifact 与当前 CAGE-AD 代码，给出不依赖实现者自由发挥的逐 episode 数据生成、验证、划分与发布规范，并提交到 GitHub。

## Phases

- [x] Phase 1：拉取仓库、检查分支与现有文档/代码资产
- [x] Phase 2：审计当前 12-case 生成器、Dataset Card、失败报告与测试
- [x] Phase 3：逐篇还原 HINT、Minimal Grey Box、ADSDx、ACAV、ROCAS、MoDitector 等数据构建方法
- [x] Phase 4：冻结 CAGE-AD 场景、故障、参数、配套运行、oracle 与质量 gate
- [x] Phase 5：编写逐 episode 生成协议、manifest/registry 规范和服务器执行说明
- [x] Phase 6：对齐或补充 schema、registry、文档测试与一致性检查
- [x] Phase 7：无上下文读者测试、修订、commit 并 push

## Key Questions

1. 当前 12 个 smoke cases 为什么只有 2 个通过，失败来自数据设计还是 runtime 实现？
2. 每一种 fault 的注入边界、强度、持续时间和可辨识证据应来自哪篇论文或哪类真实 bug？
3. 如何避免场景名、注入配置、时间戳、动作结果或 simulator truth 泄漏根因？
4. 每个 diagnosis episode 必须有哪些 nominal、confirmation、wrong-domain probe 和 counterfactual 配套运行？
5. 哪些阈值可以预注册，哪些必须由 pilot nominal distribution 冻结？

## Decisions Made

- 新规范以 Apollo 10 + CARLA 0.9.15、perfect-perception PnC 为当前边界，不扩展 perception 或 Autoware。
- 论文提供 taxonomy、构造逻辑和强度选择依据；不机械复制不同 Apollo/CARLA/VTD/LGSVL 版本的原始数值。
- 每个正式 episode 必须由声明式 registry 唯一生成，禁止服务器 Codex临时发明场景或 fault 参数。
- 旧 `docs/d0/` 两个主设计文件属于有 SHA-256 的 G0 checkpoint，保持字节不变；protocol v1 和新服务器 Prompt 作为后续覆盖层。
- 12 条从“全笛卡尔积样本”改为“6 个 fault archetypes × 2 个机制匹配 exposure variants”的 calibration recipes。
- 先用 calibration seeds 1101–1105/1101–1103 选择最小可用 candidate/dose，再冻结 formal seeds 2101–2103；formal 每 seed/condition 重复 3 次。
- correct-domain probe 不自动等于根因；必须同时满足 pre-intervention similarity、paired improvement 和 wrong-domain margin，否则进入 ambiguous。

## Errors Encountered

- 首次本地测试调用了没有 pytest 的系统 Python；随后误用 Python 3.9 创建 venv，与项目 `>=3.10` 不兼容。已将该环境移到 `/tmp/cage-ad-venv-py39-20260807`，改用 workspace Python 3.12 建立仓库内忽略的 `.venv`。
- 修改两个带 G0 provenance 校验和的历史设计文件导致 source checkpoint test 失败；已完整恢复字节内容，另建 `CODEX_D0_PROTOCOL_V1_PROMPT.md` 承载新指令。

## Status

**Complete** — fresh-reader P0/P1 已修订；全量测试、source audit、commit 与 remote push 均完成。
