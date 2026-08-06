# Apollo D0 GitHub Source-only 交接规范

> 目标：让 AutoDL 保留大体量运行环境，让 GitHub 成为可审查、可继续开发的源码事实源。不得把 53+ GiB runtime 搬到本地或提交 Git。

## 1. 仓库与分支

- 使用全新的 private repository：`CAGE-AD`。
- 固定 SSH remote：`git@github.com:LiPume/CAGE-AD.git`。
- 工作分支：`codex/apollo-d0-active-diagnosis`。
- 服务器工作区建议：`<persistent-bundle>/project/CAGE-AD`。
- 不在旧 `Zhijia-Guardian` 仓库中开发；旧仓库不是新论文代码依赖。
- 禁止 force-push、改写已有公共历史或把 token 写入 remote URL/config 文件。

### 服务器首次连接

优先 clone 新远端，不在旧工作区替换 remote：

```bash
git clone git@github.com:LiPume/CAGE-AD.git <persistent-bundle>/project/CAGE-AD
cd <persistent-bundle>/project/CAGE-AD
```

若远端已有 `main`/README，执行 `git pull --ff-only origin main`；若远端仍为空，则在这个新 clone 中创建 `README.md`、提交 `first commit` 并推送 `main`。随后创建工作分支：

```bash
git switch -c codex/apollo-d0-active-diagnosis
git push -u origin codex/apollo-d0-active-diagnosis
```

如果目标路径已存在，必须先验证 Git root 和 `origin` 精确匹配上述仓库；不匹配时停止，不覆盖目录。

推荐 tag：

- `g0-apollo10-go`：G0 必要源码 checkpoint；
- `d0-apollo-pilot`：D0-A1、baseline 和审计完成。

## 2. GitHub 必须保存

```text
src/cage_ad/                       # 主动诊断、Agent、adapter、evaluation 源码
benchmarks/apollo_d0/             # scenario/fault/action/split registry
configs/d0/                       # 预算、policy、calibration、模型示例配置
contracts/                        # JSON Schema/Pydantic contract 与示例
deploy/autodl_apollo10/           # launch/config/环境检查，不含环境本体
scripts/g0/                       # G0 可复现脚本
scripts/d0/                       # D0 生成、运行、评估、审计脚本
tests/d0/                         # CPU 单测、schema、泄漏、预算测试
third_party/*/UPSTREAM.yaml       # upstream URL、commit/tag、license、获取命令
third_party/patches/              # Apollo/bridge 的文本 patch
artifacts/g0/                     # 报告、版本锁、小型 evidence index
artifacts/d0/                     # 小型结果表、plot source、manifest index
docs/d0/                          # 本设计、实现 Prompt、决策与限制
```

G0 checkpoint 必须从服务器实际工作区收集，而不是依据本地不完整 evidence bundle 猜测：

- G0 新增/修改 scripts；
- `runtime/apollo_g0` 中由本项目编写的源文件和配置；
- `coordination/` contracts；
- CARLA–Apollo bridge patch；
- Apollo `application-pnc` patch 或可复现 patch series；
- G0 实验项目新增/修改源码；
- 版本、命令、依赖来源与 SHA-256 索引。

若第三方目录包含大量 upstream 文件，只提交 `UPSTREAM.yaml + patch`，不要复制整个仓库。

## 3. 禁止提交

- Apollo/CARLA binaries、Conda 环境、Docker layer、build/install/cache；
- maps、models、weights、raw sensor、record/bag、视频、大型日志；
- evaluator-private oracle payload、injector state、GT 可见路径镜像；
- `.env`、API key、GitHub token、SSH private key、cookies、个人信息；
- core dump、临时 lock、PID、socket、absolute host path；
- 第三方数据集压缩包或许可证不允许再分发的内容。

建议 `.gitignore` 至少覆盖：

```gitignore
.env*
!.env.example
runtime/
data/raw/
data/private/
**/oracle_private/
**/*.bag
**/*.record*
**/*.mp4
**/*.pcd
**/*.onnx
**/*.engine
**/build/
**/install/
**/cache/
**/__pycache__/
*.log
*.pid
```

## 4. Runtime 引用合同

源码不得硬编码 `/root/autodl_apollo10_g0_bundle`。入口从以下变量解析：

```text
CAGE_RUNTIME_ROOT        # Apollo/CARLA/bridge 大体量运行目录
CAGE_STATE_ROOT          # append-only run state/evidence/manifest
CAGE_PRIVATE_ORACLE_ROOT # evaluator-only，诊断进程不可读
CAGE_DATA_ROOT           # raw episode data，可独立挂载
```

每个 artifact reference 保存：

```json
{
  "source_commit": "git_sha",
  "runtime_version": "version_or_sha",
  "relative_path": "path_below_declared_root",
  "sha256": "...",
  "size_bytes": 0,
  "visibility": "diagnosis_visible_or_evaluator_private"
}
```

## 5. 数据发布边界

- Git 保存 benchmark generators、registries、split、small semantic fixtures 和结果索引。
- AutoDL 持久盘保存 raw episode 和 private oracle。
- 主 benchmark 的公开版本优先提供“生成脚本 + manifest + semantic evidence”；raw sensor 可按许可证与存储预算另放 release/object storage。
- ADSDx、ACAV、HINT 等第三方 artifact 只保存来源、版本、校验和、适配脚本，不重新上传原始包。

## 6. Commit gates

1. `chore(g0): checkpoint Apollo 10 reproducible source`
2. `feat(d0): add diagnosis contracts and state engine`
3. `feat(d0): add benchmark generators and semantic tools`
4. `feat(d0): add non-agent diagnostic policies`
5. `feat(d0): add single-agent policy`
6. `feat(d0): add structured multi-agent policy`
7. `test(d0): freeze pilot protocol and audit results`

每个 gate：

1. 运行对应 unit/schema/leakage tests；
2. 更新 `RUN_STATE.yaml` 和 `CHANGELOG_D0.md`；
3. 提交小而完整的 commit；
4. remote 已配置时立即 push；
5. push 失败不丢本地提交，记录到 `USER_ACTION_REQUIRED_GITHUB.md`，继续所有不依赖远端的工作。

## 7. CI 与可复现性

GitHub Actions 只运行不需要 Apollo/CARLA/GPU 的工作：

- Python lint/type/schema tests；
- budget/ledger/state-machine unit tests；
- forbidden-key/path/secret scan；
- fixture-based belief/policy tests；
- manifest/UPSTREAM/patch completeness。

完整 simulator integration test 只在 AutoDL 执行，并将 compact report、commit SHA、runtime SHA 和证据校验和推回 GitHub。

## 8. G0 源码 checkpoint 验收

- clean clone 能安装项目自身的轻量 Python 依赖并通过 CPU tests；
- `UPSTREAM.yaml` 能唯一解析 Apollo 10、CARLA 0.9.15 和 bridge 来源；
- textual patches 可做 dry-run/apply 检查；
- Git history 中无大文件、secret、raw payload、private oracle；
- G0 report 中的命令能映射到仓库脚本；
- 服务器实际可执行环境仍留在持久盘，Git clone 不被误称为可独立运行的完整镜像。
