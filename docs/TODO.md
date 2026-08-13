# 后续工作

本文件只保留尚未完成的事项。已完成事实和历史问题统一记录在 `docs/PROGRESS.md`。

## P0：首个真实完整 episode

- [ ] 按 `docs/OPERATIONS.md` 启动三相机、四臂 driver 和默认 unarmed teleop，确认 11 个白名单
  publisher、磁盘空间和无额外 control publisher。
- [ ] 在明确授权、安全现场和急停可触达的条件下，录一个 10 秒静态包和一个 10–30 秒低速主从
  遥操作包；保留 bag、配置 SHA、仓库 SHA、CAN 映射和相机 serial。
- [ ] 用 `bag_inspect` 检查每路类型、count、rate、起止时间和 timestamp 来源；缺流或无 command 的
  bag 不得标为完整 episode。
- [ ] 转换 HDF5，保存 QC JSON，检查 overlap、有效帧、丢帧原因、同步 delta 和
  `action_source=executed`。
- [ ] `validate_episode` 通过后导出 LeRobot Dataset v3，重新加载并逐路观看视频。
- [ ] 人工对齐检查同一时刻的 master intent、teleop command、follower state、EEF 和三路 RGB，
  不能只检查 shape。

完成条件：至少一个真实 11-topic episode 通过 record→inspect→HDF5→validate→LeRobot reload，
并保存人工内容审查结论。

## P0：最终 teleop 配置回归

- [ ] 清空从臂工作区、确认急停可触达并检查无旧 driver/teleop 进程。
- [ ] follower 未 enable 时启动当前版本，确认 unarmed 零 command；核对 left/right 语义接口没有串线。
- [ ] 双侧 enable 和 arm 后确认第一条 command 保持 follower，随后追踪冻结 master 目标；两侧进入
  0.05 rad / 0.002 m 容差并稳定 0.3 秒后应报告 live follow active。
- [ ] 先左、后右、最后双侧做小幅关节和夹爪完整张合，记录方向、峰值误差、主观延迟和停止行为。
- [ ] 单独验证 stale/fault 后 bridge 停发，并由人工完成 disarm→disable；Ctrl+C 不等于硬件 disable。
- [ ] 保存短时 command/follower state 统计和结束后的残留进程、CAN TX 检查。

完成条件：当前 `0.2.0` 配置有一份可审计的左右/双侧 live-follow 记录，而不只依赖旧版本现场描述。

## P1：RealSense 与长时数据质量

- [ ] 三路同时运行 5–10 分钟，记录 recorder count/rate、CPU、内存、磁盘增长、USB reset 和 gap。
- [ ] 拔插三台设备后重新启动，确认相同 serial 仍映射到 front/left/right topic。
- [ ] 用真实 episode 统计重新评估 RGB 20 ms、state/EEF 10 ms、action 20 ms 同步容差。
- [ ] 明确 EEF 坐标系、单位和四元数→RPY 约定。
- [ ] 增加 command 与 follower state 的跟踪误差/延迟 QC，但继续区分 commanded action 与电机 ACK。
- [ ] 决定中断、磁盘不足、部分 topic 消失后的失败数据隔离和重试规则。

## P1：在线 collector 的去留与重构

当前保留 `collect.py`、`collect.launch.py` 和 `config/topics.yaml`，不直接删除。

- [ ] 先确定是否确实需要“在线直接写 HDF5”，还是统一使用 ROS topic→rosbag→离线转换。
- [ ] 如果继续在线路径，复用 canonical 同步规则：RGB 最近邻、state/EEF 容差、action 因果选择、
  source timestamp 和 sync delta；不得继续维护隐式的第二套同步合同。
- [ ] 增加在线保存后的 `validate_episode` 门禁；不合格文件不能进入正式数据集。
- [ ] 若一段真实使用期内没有在线路径需求，再单独决定弃用，而不是本轮直接删除。

## P2：Replay 与批量数据集

- [ ] 在真实 episode 合同稳定前保持硬件 replay 禁用。
- [ ] 先实现纯离线时间轴检查和可视化，再考虑隔离 ROS domain 的 command replay。
- [ ] 若未来增加真机 replay，必须复用 teleop 的 arming、对齐、限位、stale、fault 和显式
  enable/disable 门禁。
- [ ] 完成多 episode 批量导出、任务标签、数据集版本和本地/Hub 发布边界。
