# 可审计进展（截至 2026-08-13）

本文只记录已观察或已验证的结果。静态检查、配置存在、接口 UP 和真实数据/动作验证是不同
证据层级，不相互替代。

## 仓库基线

- `b598595fa16325a1d42dcb2c777860d1dcb0c281`：建立 ROS 2 episode 采集、HDF5 schema、
  dry-run replay 和纯 Python 测试。
- `0306f53652ac02aa52f28d74a19cb838397df572`：加入四臂 CAN 稳定命名、部署脚本、ROS
  namespace 编排和 CAN 配置解析测试。

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

## 已停止或未继续

- 其余三路 ROS 解码没有继续验证；没有据此宣称四臂 ROS 链路已打通。
- `four_arm.launch.py` 未整体启动；`piper_single_ctrl`、teleop、控制 topic 和 enable service
  未作为本轮验证的一部分运行。
- 相机未完成 serial 绑定和图像 topic 验证。
- EEF 坐标系、四元数到 RPY 约定、夹爪第 7 维和跨设备时间同步未验证。
- 尚未完成包含三相机、双 follower、双 leader action 和双 EEF 的完整 episode 录制、保存、
  读回与内容审计。

## 证据边界

- `colcon build/test`、Python 测试和 launch 参数解析只证明软件接口与静态 contract。
- `can_status.sh` 只证明部署映射和网络层状态。
- 被动 CAN 流不证明 ROS 解码正确；单路 `JointState` 不证明其余三路或完整采集正确。
- replay 当前只读 HDF5 并打印 shape；即使传 `--execute` 也会拒绝，不是硬件回放验证。
