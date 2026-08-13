# 可审计进展（截至 2026-08-14）

本文只记录已经观察或验证的事实。“代码已接入”“软件测试通过”“真实硬件通过”和“完整 episode
通过”是不同证据层级，不相互替代。

## 版本与基线

- 当前软件版本：`0.2.0`。
- HDF5 schema：`1`；LeRobot Dataset 格式：`v3`；导出环境固定 `lerobot==0.6.0`。
- `b598595fa16325a1d42dcb2c777860d1dcb0c281`：最初的 ROS 2 collector、HDF5 schema、只读
  replay 和纯 Python 测试。
- `0306f53652ac02aa52f28d74a19cb838397df572`：四路 CAN serial 绑定、部署脚本和四臂 namespace。
- `f002c6f`、`e51c35a`：白名单 rosbag、压缩读取、canonical 转换和 LeRobot v3 导出。
- `b266a69` 至 `18df124`：默认 unarmed teleop、夹爪规范化、冻结目标对齐、tmux/control 流程和
  0.05 rad 完成门限标定。
- `b06af28`、`60e7b8c`、`f90e2ec`：三台 RealSense serial 绑定、launch、status、短包和录制修复。
- `16b0c05062cdedf56e3e8f45fb6702e8c4c9ea6a`：合并 teleop 与 RealSense 两条集成线，是本轮文档
  整理前的仓库基线。

当前没有 Git release tag；正式发布时 tag 应与 package version 一致。

## 当前能力

| 能力 | 状态 | 已有证据 | 尚未证明 |
|---|---|---|---|
| CAN serial→稳定接口 | 已验证 | 重启后四路映射、1 Mbps、UP 通过 | 长时间总线质量 |
| 四臂 ROS 编排 | 已接入并短时验证 | 四路反馈约 200 Hz、namespace/CAN 参数确认 | 长时间运行和全部状态语义 |
| 双臂 teleop | 已接入 | 默认零 command、显式门禁、真实运动和对齐响应 | 最终配置的完整 live-follow 回归与定量误差 |
| 三台 RealSense | 已接入并短包验证 | serial 角色、RGB8 640×480、三路短包与抽帧 | 5–10 分钟、拔插重连、完整 episode |
| bag→HDF5→LeRobot | 软件闭环已验证 | 11-topic 合成 bag、HDF5 validate、v3 reload | 真实完整 11-topic episode |
| 在线 Python collector | 保留待重构 | 旧交互和 HDF5 保存仍存在 | 与 canonical 因果同步合同一致 |
| 硬件 replay | 未实现 | 只读 shape；`--execute` 拒绝 | 任何隔离或真机 command replay |

## 已验证事实

### CAN 与四臂反馈

- `deploy/piper-can.conf` 当前物理映射为：从左 `003400...→can_slave_l`、从右
  `002300...→can_slave_r`、主左 `004400...→can_master_l`、主右
  `003B00...→can_master_r`。
- 四个 `gs_usb` 接口在部署和正常重启后均为目标稳定名、1 Mbps、UP；`can_status.sh` 通过。
- 带 timeout 的被动监听在四路都观察到真实 CAN 流。该结果不证明 ROS 解码和动作语义。
- `can_master_l` 的一次受控 ROS 读取收到 30 帧，约 200 Hz `JointState`；后续四臂窗口观测到
  master left/right 约 `200.16/200.00 Hz`，follower left/right 均约 `200 Hz`。
- 官方 `piper_read_slave_joint` 每路初始化会发送 13 个查询帧。它们不是 enable 或运动帧，但说明
  driver 启动不是零 TX。清理后 TX 停止增长。

### 双臂主从遥操作

- teleop 默认 unarmed，bridge 不自动 enable follower；真实未 arm 窗口左右各 4.02 秒为零 command。
- 两路 master 实际消息均为严格 9D `joint1..joint6,gripper,joint7,joint8`；canonical 夹爪使用
  `abs(joint7-joint8)`，不读取占位 `gripper`。
- 用户分阶段完成过 enable、arm、左右单侧和双侧运动，确认基础跟随方向可用，并由此发现并修正
  follower 物理左右标签反向和 10% 速度过慢问题。
- 后续双侧对齐日志确认 command 约 100 Hz；右 joint6 误差在 0.3 秒内从 `0.2013` 降至
  `0.0428 rad`，两侧最终稳定在约 `0.0321/0.0365 rad` 的静态残差，证明 follower 实际执行了目标。
- 代码据此把完成门限从 0.02 标定到 0.05 rad，并保留冻结 master、首帧保持 follower、双侧同时
  切换、15 秒 timeout、stale 和 fault latch。最终 0.05 rad 版本仍需保存一次完整 live-follow 结果。
- `/follower_*/joint_ctrl_cmd` 只代表 bridge 发布的 commanded action；官方
  `/follower_*/joint_ctrl` 在本机不能作为电机 ACK。

### 三台 RealSense

- 当前固定角色为：front=`335622070696`、left=`349622073361`、right=`335622072178`。
- 三台 D435 均按 serial 启动成功，输出 `sensor_msgs/msg/Image`、RGB8、640×480；角色由用户根据
  serial-labelled 真实预览确认，不依赖枚举顺序或 `/dev/video*`。
- 9.864 秒 zstd message-compressed 正式短包三路各写入 297 帧，共 891 帧；自动读回 type、count、
  timestamp 成功，按 recorder 接收时间约 `30.01/30.07/30.05 Hz`，没有超过 100 ms 的接收 gap。
- 三路 PNG 抽帧成功，采样时间最大相差约 10 ms。该结果证明当前绑定与短包录制可用，不证明
  长时间稳定、硬件同步或拔插重连。

### 数据链与软件验证

- 30 帧、11-topic 合成 rosbag 已通过 record/inspect→HDF5→validate，得到
  `action_source=executed`；压缩 FILE/MESSAGE bag 使用 `SequentialCompressionReader` 正确读取。
- 合成 HDF5 已导出为三路视频的 LeRobot Dataset v3，并完成 reload。
- intent 与 executed 分开保存；默认训练导出只接受 executed。commanded action 不等于电机执行 ACK。
- 本轮精简后，Python compile、shell `bash -n`、CAN parser、49 个 Python 测试加 8 个 subtest、
  colcon build/test 和三个 launch 参数解析均通过。测试只证明软件合同，不替代硬件验证。

## 已接入但尚未完成的验收

- 最终 0.05 rad 对齐门限下，双侧进入 live follow 后的方向、夹爪全行程、延迟、跟踪误差、
  stale/fault 停止行为尚未形成一份完整记录。
- 三台相机的 5–10 分钟稳定性、同一 Hub 的带宽余量和拔插重连后角色保持尚未验证。
- 尚无同时包含三相机、双 master intent、双 follower state、双 EEF 和双 command 的真实 bag，
  也没有完成其 HDF5 QC、LeRobot reload 和三路视频人工抽查。
- EEF 坐标系、四元数→RPY 约定和跨设备时间同步尚未用真实 episode 验收。
- 在线 `collect.py` 仍使用独立同步逻辑，暂不作为正式训练数据入口。

## 证据边界

- `can_status.sh` 只证明网络部署；接口 UP 不证明机械臂角色和 ROS topic 正确。
- 静态配置、单元测试和隔离 ROS smoke 不证明真实硬件消费 command。
- RealSense 已接入和短包通过，不等于长时间、重连或完整多模态 episode 通过。
- 用户现场观察能证明当时流程可运行，但没有日志时不能扩写为定量精度或一般性安全结论。
- replay 当前始终只读，不是硬件回放能力。
