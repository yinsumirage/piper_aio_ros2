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

- CAN 系统部署已完成验证：四个 `gs_usb` 设备按 USB serial 映射为 `can_slave_l`、
  `can_slave_r`、`can_master_l`、`can_master_r`，均为 1 Mbps、UP；
  `scripts/can_status.sh` 返回成功。
- 在带 timeout 的被动监听中，四个接口都观察到真实 CAN 流。这个结果只证明总线上有真实帧，
  不证明四路 ROS 解码、topic 语义或机械臂动作正确。
- 对 `can_master_l` 做过一次受控 ROS 读取检查：`JointState` 收到 30 帧，观测频率约
  200 Hz。该结果不外推到其余三路。
- 官方 `piper_read_slave_joint` 初始化期间观察到 13 个查询帧。它们不是运动帧或使能帧，
  检查中没有使能或运动机械臂；但这是非零 TX，因此该节点不能称为严格被动监听。
- 当前代码的 34 个 Python 测试（另含 8 个 subtest）通过；teleop 覆盖严格 9D 名称映射、
  `joint7-joint8` 夹爪、双侧原子 arming、初始对齐、限位、step、stale 和 fault latch。
- 隔离 `ROS_DOMAIN_ID` 的单进程合成测试通过：unarmed 时两路均 0 command，显式 arm 后两路均
  收到有界 7D command，停止输入后 stale 锁存并停发，退出无残留进程。
- 另一隔离 ROS 图以 11 个白名单 publisher 加两条官方 `/follower_*/joint_ctrl` 反馈运行真实
  `bag_preflight`，检查成功且没有 unexpected control publisher；退出无残留进程。
- `colcon build --symlink-install` 和现有 `colcon test` 命令成功，teleop/four-arm launch 参数解析
  成功。现有 setuptools test 入口打印 `Ran 0 tests`，因此 Python 覆盖证据以单独 pytest 为准。
- 2026-08-13 在 `ROS_DOMAIN_ID=231`、`ROS_LOCALHOST_ONLY=1` 的有界真实 CAN 窗口整体启动
  `four_arm.launch.py`：runtime 参数确认 master left/right 分别使用 `can_master_l/r`，follower
  left/right 分别使用 `can_slave_l/r`，四处 `gripper_exist=true`，两路 follower
  `auto_enable=false`。没有调用 `/follower_*/enable_srv` 或发布 `enable_flag`。
- 四路真实反馈均约 200 Hz：master left/right 分别约 `200.16/200.00 Hz`，follower left/right
  分别约 `200.00/200.00 Hz`。两路 master 实测 name 均严格为 9D
  `joint1..joint6,gripper,joint7,joint8`，占位 `gripper=0`；左侧 `joint7=-0.00015`、
  `joint8=0.00015`，右侧均为 0，所以 `joint7-joint8` 分别为 `-0.0003 m` 和 `0.0 m`。
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

## 已停止或未继续

- 四路静态 ROS 反馈和 namespace→CAN 参数已验证，但没有由现场人员逐臂扰动，因此物理
  left/right 接线、关节方向、夹爪方向与完整行程仍未验证。
- `four_arm.launch.py` 已在隔离 ROS domain 整体只读启动；真实 `piper_single_ctrl` 只发布反馈，
  未收到 command/enable。teleop 也仅验证真实输入下的 unarmed 零发布，尚未调用 arm。
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
  （joint6），均超过 `0.10 rad` 初始对齐门限；这是下一次 arm 前必须先物理对齐的真实阻断项，
  不能通过直接放宽阈值规避。
