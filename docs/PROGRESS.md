# 可审计进展（截至 2026-08-13）

本文只记录已观察或已验证的结果。静态检查、配置存在、接口 UP 和真实数据/动作验证是不同
证据层级，不相互替代。

## 仓库基线

- `b598595fa16325a1d42dcb2c777860d1dcb0c281`：建立 ROS 2 episode 采集、HDF5 schema、
  dry-run replay 和纯 Python 测试。
- `0306f53652ac02aa52f28d74a19cb838397df572`：加入四臂 CAN 稳定命名、部署脚本、ROS
  namespace 编排和 CAN 配置解析测试。
- `c8607f7e538a6104397e6481dfa45d36a994c13a`：精确放行两条官方 follower control-feedback
  topic，同时继续拒绝未授权 command/enable publisher。
- `b266a6958f43e20f0b3bec0209c6d819538d3602`：加入默认 unarmed、双侧原子门禁和 fault latch 的
  双臂 teleop bridge；未包含自动 enable。

## 已验证

- 初次 CAN 系统部署曾验证四个 `gs_usb` 稳定名均为 1 Mbps、UP，
  `scripts/can_status.sh` 返回成功；后续真实运动证明当时两路 follower 的 `l/r` 名称与物理角色
  相反。该结果证明网络部署可用，不证明初始 follower 角色判断正确。
- 在带 timeout 的被动监听中，四个接口都观察到真实 CAN 流。这个结果只证明总线上有真实帧，
  不证明四路 ROS 解码、topic 语义或机械臂动作正确。
- 对 `can_master_l` 做过一次受控 ROS 读取检查：`JointState` 收到 30 帧，观测频率约
  200 Hz。该结果不外推到其余三路。
- 官方 `piper_read_slave_joint` 初始化期间观察到 13 个查询帧。它们不是运动帧或使能帧，
  检查中没有使能或运动机械臂；但这是非零 TX，因此该节点不能称为严格被动监听。
- 当前代码的 39 个 Python 测试（另含 8 个 subtest）通过；teleop 覆盖严格 9D 名称映射、
  `abs(joint7-joint8)` 夹爪开度、双侧原子 arming、首帧保持与直接绝对对齐、双侧同时切换、command 限位、step、stale
  和 fault latch。
- 隔离 `ROS_DOMAIN_ID` 的单进程合成测试通过：unarmed 时两路均 0 command；显式 arm 后第一帧
  保持各侧 follower 反馈，随后直接发送完整绝对目标，两侧一起进入 100 Hz/100% 同步；停止输入后
  stale 锁存并停发，退出无残留进程。
- 另一隔离 ROS 图以 11 个白名单 publisher 加两条官方 `/follower_*/joint_ctrl` 反馈运行真实
  `bag_preflight`，检查成功且没有 unexpected control publisher；退出无残留进程。
- `colcon build --symlink-install` 和现有 `colcon test` 命令成功，teleop/four-arm launch 参数解析
  成功。现有 setuptools test 入口打印 `Ran 0 tests`，因此 Python 覆盖证据以单独 pytest 为准。
- 2026-08-13 在 `ROS_DOMAIN_ID=231`、`ROS_LOCALHOST_ONLY=1` 的有界真实 CAN 窗口整体启动初版
  `four_arm.launch.py`：当时 runtime 参数确认 master left/right 分别使用 `can_master_l/r`，follower
  left/right 分别使用已部署标签 `can_slave_l/r`，四处 `gripper_exist=true`，两路 follower
  `auto_enable=false`。没有调用 `/follower_*/enable_srv` 或发布 `enable_flag`。
- 四路真实反馈均约 200 Hz：master left/right 分别约 `200.16/200.00 Hz`，follower left/right
  分别约 `200.00/200.00 Hz`。两路 master 实测 name 均严格为 9D
  `joint1..joint6,gripper,joint7,joint8`，占位 `gripper=0`；左侧 `joint7=-0.00015`、
  `joint8=0.00015`，右侧均为 0，所以原始 `joint7-joint8` 分别为 `-0.0003 m` 和 `0.0 m`。
  follower 均为 7D，样本夹爪分别为 `-0.0028 m`、`0.0003 m`。
- 两路 follower 的原始 `arm_status/ctrl_mode/mode_feedback/teach_status/motion_status/err_code`
  在采样时均为 0。该消息不暴露六个电机的独立 enable bit，因此这里只确认软件
  `auto_enable=false`、内部 command gate 未被调用和状态原始值，不能把它扩写为完整硬件使能审计。
- 随后在同一真实四路反馈窗口启动 teleop，日志明确报告 unarmed。启动前两路 command publisher
  均为 0；启动后各有 1 个 bridge publisher，但 `4.02 s` 内左右 command 消息数均为 0。
  `/dual_arm_teleop/arm` 存在但未调用，两个硬件 enable service 也未调用；未观察到 teleop fault。
- 成功采样窗口内四路 host TX 各增加 13 个启动查询包，TX error 为 0；此前一个完成节点初始化
  但采样程序失败的窗口也观察到同样增量。最终清理后无 driver/teleop 残留，连续 2 秒四路
  host TX 均不再增长。
- 随后用户按未使能 arm、左右单侧、双侧的顺序完成初版绝对映射真机流程，报告动作方向和跟随
  基本符合、没有明显异常；同时以真实运动确认 master 左右正确，但两路 follower 的已部署
  `can_slave_l/r` 名称对应物理左右相反：master left 当时驱动物理右 follower，master right
  驱动物理左 follower。10% 速度的主观跟随明显过慢。该项是用户现场观察，没有保存逐轴日志、
  延迟、跟踪误差或完整安全测试记录。

## 已停止或未继续

- 初版真机运动已经暴露 follower 物理左右与已部署接口标签相反。仓库现已交换两路 follower
  serial→稳定名，并让 ROS left/right 恢复使用语义 `can_slave_l/r`；系统规则已安装，重启后
  `can_status.sh` 确认四路目标 serial、稳定名、1 Mbps 和 UP。物理左右的逐侧回归仍需完整记录。
- master 夹爪映射和 follower 运动方向得到现场正向反馈，但夹爪完整行程、逐轴定量跟踪误差、
  stale/fault 的真实运动行为和长时间稳定性仍未留存可审计证据。
- 2026-08-13 的 100 Hz/80% 真机回归中，用户确认关节能够运动，但张开夹爪时 bridge 锁存
  `left: automatic gripper alignment distance exceeded threshold` 并按设计停止双侧发布。只读样本显示
  master-left 原始差值为负、master-right 为正，而 follower feedback/官方 command 使用非负开度；
  这定位为 canonical 符号错误，不是 CAN 断开。开度幅值修复尚待真机复测。
- 随后的幅值修复版本能 arm 并进入 alignment，但约 52 秒内没有报告 complete；用户继续张开
  master-left 夹爪后触发现有 `0.07 m` 绝对门限，双侧停发。disarm 后还出现一次
  `follower_left: joint step safety limit exceeded`。只读复查确认四路反馈仍为约 200 Hz，当前左右
  输入静止且 CAN/topic 均在线；官方 follower 源码采用 80000（0.08 m）夹爪上限，且 `GripperCtrl`
  没有速度百分比参数。代码现改为 0.08 m 门限、首帧保持后发送完整目标、六关节 100% 以及
  `gripper_effort: 1.0`；该版本仅完成离线/隔离 ROS 验证，尚未真机复测。
- 相机未完成 serial 绑定和图像 topic 验证。
- EEF 坐标系、四元数到 RPY 约定和跨设备时间同步未验证。两路 master 的 9D name/当前值已
  观测，但夹爪单位、方向、零点与完整行程仍未通过现场物理扰动标定。
- 尚未完成包含三相机、双 follower、双 leader action 和双 EEF 的完整 episode 录制、保存、
  读回与内容审计。

## 证据边界

- `colcon build/test`、Python 测试和 launch 参数解析只证明软件接口与静态 contract。
- `can_status.sh` 只证明部署映射和网络层状态。
- 被动 CAN 流不证明 ROS 解码正确；单路 `JointState` 不证明其余三路或完整采集正确。
- replay 当前只读 HDF5 并打印 shape；即使传 `--execute` 也会拒绝，不是硬件回放验证。
- teleop 的隔离 ROS command 只证明桥接器发布合同和安全门禁，不证明驱动消费、硬件 enable、
  方向/单位、夹爪行程、跟踪精度、电机 ACK 或真实运动安全。
- 本轮静态样本下，左侧最大主从关节误差约 `0.145 rad`（joint4），右侧约 `0.112 rad`
  （joint6）。当前实现不再要求人工把四臂摆到同一姿态：显式 arm 后第一条 command 保持 follower
  当前姿态，随后让官方控制器以 100% 追 live master 的完整绝对目标；双侧反馈进入配置容差后才
  报告 complete。夹爪没有独立速度字段，直接发送完整开度目标，`gripper_effort` 仅表示力矩。
  默认最大自动对齐距离 `1.0 rad` / `0.08 m` 尚未真机标定，也不执行机械零位回零。
- 用户现场报告能证明初版流程在当时可运行并发现左右错误，但没有机器生成的 command/state
  日志，不能据此给出定量同步精度、最大安全速度或“没有危险”的一般性结论。
