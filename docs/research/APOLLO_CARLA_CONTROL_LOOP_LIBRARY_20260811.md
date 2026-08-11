# Apollo—bridge—CARLA 控制闭环资料库（2026-08-11）

## 这份资料库解决什么问题

当前不是研究大模型诊断方法，而是先回答一个基础问题：Apollo 已经给出规划和控制命令，为什么 CARLA 里的车仍然开不快。

可以把整条链理解为：

> Apollo 规划目标速度 → Apollo 控制器算油门/刹车 → bridge 翻译并下发 → CARLA 车辆运动 → bridge 把真实车辆状态回报给 Apollo。

任何一环不正确，后面的交互场景、预计碰撞时间和故障诊断数据都会失去意义。

## 资料实际存放位置

第三方网页和论文原件不进入 Git，统一保存在持久盘：

`<bundle>/runtime/references/apollo_control_loop_20260811/`

目录含义：

- `web/`：公开网页的本地快照；
- `papers/`：可以公开取得的论文原件；
- `metadata/`：出版社公开的题名、作者、出版信息；
- `web/access_limited/`：网站返回的拒绝访问或空响应，只用于证明当时没有取得全文，不能当论文阅读。

当前资料库约 43 MiB，不包含代码包、数据集、视频或复现环境。

## 第一组：直接解释当前控制链的资料

### Apollo 纵向控制

1. Apollo 9 中文纵向控制说明
   - 官方网页：<https://apollo.baidu.com/docs/apollo/9.0/md_modules_2control_2controllers_2lon__based__pid__controller_2README__cn.html>
   - 本地：`web/apollo_9_lon_pid_cn.html`
   - 对当前问题的意义：确认 Apollo 先根据位置和速度误差算期望加速度，再查车辆标定表得到油门或刹车。

2. Apollo 车辆纵向自动标定论文
   - 公开页面：<https://arxiv.org/abs/1808.10134>
   - 本地网页：`web/apollo_auto_calibration_arxiv.html`
   - 本地论文：`papers/apollo_auto_calibration_1808.10134.pdf`
   - 对当前问题的意义：不同车辆需要自己的“速度＋期望加速度→油门/刹车”关系，不能默认通用表能准确控制 CARLA Lincoln。

3. Apollo 10 标定表字段
   - 官方网页：<https://apollo.baidu.com/docs/apollo/10.x/calibration__table_8proto_source.html>
   - 本地：`web/apollo_10_calibration_table_proto.html`
   - 对当前问题的意义：确认表中每一项只有当前速度、期望加速度和控制命令三个核心值。

### CARLA 执行和时间

4. CARLA 0.9.15 车辆控制
   - 官方网页：<https://carla.readthedocs.io/en/0.9.15/core_actors/>
   - 本地：`web/carla_0.9.15_actors.html`
   - 对当前问题的意义：`throttle`、`brake` 和 `steer` 只是输入，车辆实际响应还受质量、发动机、变速箱、车轮和阻力影响。

5. CARLA 车辆物理参数
   - 官方网页：<https://carla.readthedocs.io/en/latest/tuto_G_control_vehicle_physics/>
   - 本地：`web/carla_vehicle_physics.html`
   - 对当前问题的意义：必须记录当前 Lincoln 的真实物理参数，不能只记录油门百分比。

6. CARLA 同步和固定步长
   - 用户指定版本：<https://carla.readthedocs.io/en/0.9.10/adv_synchrony_timestep/>
   - 当前网页：<https://carla.readthedocs.io/en/latest/adv_synchrony_timestep/>
   - 本地：`web/carla_0.9.10_synchrony.html`、`web/carla_current_synchrony.html`
   - 对当前问题的意义：同步模式必须配固定时间步；每次重复要重新加载世界；命令和状态必须绑定到同一个仿真帧。

## 第二组：判断场景是否真的成立

7. CARLA 原始论文
   - <https://arxiv.org/abs/1711.03938>
   - 本地论文：`papers/carla_1711.03938.pdf`

8. 高保真仿真场景测试综述
   - <https://arxiv.org/abs/2112.00964>
   - 本地论文：`papers/scenario_testing_survey_2112.00964.pdf`

9. 场景测试基本要求
   - <https://arxiv.org/abs/2005.04045>
   - 本地论文：`papers/scenario_testing_fundamentals_2005.04045.pdf`

这些资料共同支持一个原则：参数写入成功、参与车辆行为成功、危险交互形成，是三件不同的事。预计碰撞时间为空时，应先检查两车是否真的接近，不能为了得到数值修改评价公式。

## 第三组：故障诊断论文网页资料

10. HINT
    - <https://arxiv.org/abs/2607.12598>
    - 本地论文：`papers/hint_2607.12598.pdf`

11. Minimal Grey Box
    - DOI：<https://doi.org/10.1109/IV64158.2025.11097509>
    - 本地只有公开出版信息：`metadata/minimal_grey_box_crossref.json`
    - IEEE 网页没有返回可用全文；服务器没有绕过访问限制。正式精读仍以用户已有合法副本为准。

12. ADSDx
    - DOI：<https://doi.org/10.1145/3783993>
    - 公开代码页：<https://zenodo.org/records/17847407>
    - 本地：`web/adsdx_zenodo.html`、`metadata/adsdx_crossref.json`
    - ACM 网页拒绝自动访问；本地拒绝页不能当论文全文。正式精读仍以用户已有合法副本为准。

13. ACAV
    - <https://arxiv.org/abs/2401.07063>
    - 项目页：<https://acav2023.github.io/>
    - 本地论文：`papers/acav_2401.07063.pdf`

14. ROCAS
    - <https://arxiv.org/abs/2409.07774>
    - 本地论文：`papers/rocas_2409.07774.pdf`

15. MoDitector
    - <https://arxiv.org/abs/2502.08504>
    - 本地论文：`papers/moditector_2502.08504.pdf`

16. Leveraging Modular Architecture
    - DOI：<https://doi.org/10.1145/3707455>
    - 本地公开出版信息：`metadata/leveraging_modular_crossref.json`、`web/leveraging_modular_metadata.html`
    - ACM 网页没有返回可用全文；服务器没有绕过访问限制。正式精读仍以用户已有合法副本为准。

这些诊断论文用于以后设计对照方法和故障分类，不能替代当前底层控制闭环修复，也不能把它们的旧平台数据混进 CAGE-AD 主数据集。

## 对服务器真实代码和旧运行证据的研究结论

### 已经确认的事实

1. Apollo 当前安装的纵向控制器确实执行“速度/位置误差→期望加速度→标定表→油门/刹车”。
2. 当前 Apollo 车辆参数的油门死区是 `15.7%`，旧运行中绝大多数油门命令恰好也是 `15.7%`。这说明控制器多数时间只是卡在最低油门，而不是使用一张已经匹配 CARLA Lincoln 的精确标定表。
3. bridge 再把该命令乘 `1.5`，因此 CARLA 常见实际输入约为 `0.2355`。
4. 旧的 20 秒无车运行中，CARLA 有 371 帧收到油门、29 帧收到刹车；车辆最高速度约 `0.78 m/s`，只前进约 `4.42 m`。
5. 同一运行中规划目标速度中位数约 `0.88 m/s`，且规划器出现 13 轮失败/备用规划。慢车不是单纯的“bridge 没转发油门”。
6. `localization_accel_alpha=0.0` 会让 bridge 回报的加速度永远为零，这是确定的反馈错误。
7. 但是 Apollo 当前纵向控制源码主要用位置误差、速度误差和规划加速度计算控制量；真实加速度在这一路径里主要用于调试量和加加速度计算。因此“加速度恒零”必须修，但不能先验认定它就是唯一根因。
8. 旧 trace 缺少 CARLA 真实加速度、Apollo 收到的加速度和纵向控制内部调试量；旧记录也没有把每条 Apollo 命令与 bridge 最终采用的仿真帧一一绑定。

### 当前最小根因树

- 如果固定 `0.2355` 油门时 CARLA Lincoln 能平稳加速，主要问题在 Apollo 的间歇刹车、规划失败或命令时序。
- 如果固定 `0.2355` 油门时 CARLA Lincoln 本身仍开不动，主要问题在车辆专用标定和 bridge 控制映射。
- 加速度恒零是独立的反馈正确性问题；必须在修复后验证“CARLA 真实加速度”和“Apollo 收到的纵向加速度”方向、单位和数值一致。

## 本轮不做的事

- 不修改旧数据、旧标签、旧划分和旧评价门槛；
- 不为了产生预计碰撞时间而调场景答案；
- 不把油门简单调大到“看起来能跑”；
- 不开始 Agent、Multi-Agent 或 Autoware；
- 不把第三方论文和网页提交到 Git。

## v3 补充的官方源码与网页（2026-08-11）

本轮新增文件位于持久资料库的 `web/v3_primary/`：

- `apollo10_piecewise_jerk_speed_optimizer.cc`：Apollo 10 官方标签 `r10.0.0` 的速度优化源码；确认规划初始加速度来自当前起点，并受车辆最大减速/加速边界约束。
- `apollo10_trajectory_stitcher.cc`：确认车辆状态中的真实加速度会写入新规划起点。
- `apollo10_vehicle_state_provider.cc`：确认 Apollo 在统一地图坐标模式下读取 `linear_acceleration_vrf.y` 作为车辆前向加速度。
- `apollo10_digital_filter_coefficients.cc`：Apollo 官方数字低通滤波系数实现。
- `carla_0.9.15_python_api.html`：CARLA 0.9.15 Python API 快照。
- `carla_current_physics_substepping.html`：CARLA 官方同步、固定步长和物理子步说明。

关键校验和：

- Apollo 速度优化源码：`be813648e4b73e1d72b608f338cbef747a81ea230d7090045b5fc1bd89ef9210`
- Apollo 轨迹拼接源码：`ee690d38d324d5df5453f43fd64cdbae0abb5c3f4fc11d480ebe9a34da81c0c6`
- Apollo 车辆状态源码：`aac7b987444d39b1864a0b5ad55f150aeae89069539ba18db1eca844302cba33`
- Apollo 滤波源码：`26a18cbbe7b21f275ccffeb835474b6c704386aa7f44e02f7b6b3aa414b0b939`

这些资料把 v2 的退化解释从“可能是加速度尖峰”提升为源码可复核的链条：CARLA 原始加速度 → bridge 定位反馈 → Apollo 车辆状态 → 规划起点加速度 → 速度优化边界。v3 因此必须逐项验证，不能再次同时修改三个控制量。
