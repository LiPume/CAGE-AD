# Apollo 10 + CARLA 展示视频录制合同

状态：**第一次录制的车辆闭环有效，但视频编码无效；已登记一次同配置低负载重录**

本视频只用于直观展示 Apollo 10 在 CARLA Town01 中控制 Lincoln 稳定直行。它复用 V17 已通过的正向低速
标定表，运行 20 秒无 NPC、无故障、无 probe 的闭环，同时由只读第三人称 RGB 相机截取自车速度超过
0.5 m/s 后的连续 15 秒。

视频固定为 1280×720、20 fps、H.264、`yuv420p`、无音频。画面必须标注“演示录像、非数据集、非安全
认证”。相机没有控制权限，不能修改车辆、Apollo、bridge、场景或评价条件。

录制只有同时满足以下条件才算成功：300 帧完整且相机帧不跳；MP4 可由 ffprobe 解码；V17 冻结闭环合同
仍然通过；运行中无 NPC、无故障、路线有效、规划覆盖至少 95%、速度跟踪比例至少 70%。如果录相导致闭环
结果改变，则视频作废并保留失败记录，不能拿去展示。

视频和 metadata 留在持久盘 `$CAGE_DATA_ROOT/demo_videos/protocol_v1/`，不进入 Git，也不冒充科学评测结果。

## 录制结果

第一次运行 `NO_NPC_SHOWCASE_V17_01` 的 Apollo/CARLA 闭环正常完成：400 帧连续、无 NPC、路线有效、规划覆盖
96%、速度跟踪比例 75.35%、前进 34.91 米。旧通用评估器仍只因已知的自动挡起步请求/反馈条件显示
`FAIL`，实际假前进挡反馈为 0；该区别沿用 V17 冻结合同，不改评价条件。

视频进程在向 ffmpeg 写入时得到 `BrokenPipeError`，没有产生可交付 MP4。系统剩余内存充足，车辆闭环也未
中断。第一次的 recorder 日志、闭环 trace、summary 和 result 全部保留，不能算成功视频。

只允许一次录制基础设施修复：把 H.264 preset 从 `medium` 降为 `ultrafast`，固定只用 2 个编码线程，并在
失败时完整报告 ffmpeg 退出码和错误文本。此改动只降低录制负载，不改变相机位姿、分辨率、帧率、编码格式、
车辆、Apollo、控制表、路线、运行时长或任何闭环门槛。重录使用新 ID `NO_NPC_SHOWCASE_V17_RETRY1`。

第二次运行的闭环再次正常完成，但视频仍在第一帧前退出。这次完整错误为：Apollo 环境中的 `LD_LIBRARY_PATH`
使 `/usr/bin/ffmpeg` 错误加载了 Apollo 自带的另一版 `libavutil`，出现
`undefined symbol: av_opt_child_class_iterate`，退出码 127。离线对照已经证明：同一 Apollo shell 中直接运行
ffmpeg 必然复现 127；只对 ffmpeg 子进程移除 `LD_LIBRARY_PATH` 后，系统 ffmpeg 正常返回 0。

因此登记最后一次环境隔离重放 `NO_NPC_SHOWCASE_V17_RETRY2`：录相 Python 仍在 Apollo/CARLA 客户端环境中，
只有它创建的 `/usr/bin/ffmpeg` 子进程去掉 `LD_LIBRARY_PATH`。不改变车辆、场景或视频内容。前两次失败日志和
闭环结果继续保留；若本次仍失败，不再实时重录。
