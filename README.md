# piper_aio_ros2

面向 ROS 2 Humble 的独立采集与四臂编排仓库。它复现
[`piper-aio`](https://github.com/innovator-zero/piper-aio) 的三相机、双臂 episode
交互和主要 HDF5 schema，并把本机 CAN 部署、ROS namespace 与采集配置集中在这里。
官方 `piper_ros2` 提供驱动，`piper-aio` 提供旧采集参考，`piper_sdk` 提供底层 SDK；
三个官方仓库必须保持干净，本仓库不回写它们。

截至 2026-08-13，四路稳定 CAN 接口、真实反馈和初版双臂 teleop 已完成分阶段现场运行；用户
报告跟随基本正常，同时发现 follower 已部署左右标签反向和 10% 速度过慢。仓库现已按物理左右
交换 follower serial→稳定名并撤销 ROS 层临时补偿；系统规则已安装并在重启后通过四路状态检查。
最新 teleop 在 arm 时冻结 master 目标：首帧保持 follower，双侧稳定对齐后才进入
100 Hz/100% live follow；另提供默认不 enable/arm 的 tmux 三窗格启动器。该版本已通过离线/隔离
ROS 测试，尚待重新启动节点后真机回归。
相机、EEF 语义和完整 episode 尚未验证。可审计边界见
[`docs/PROGRESS.md`](docs/PROGRESS.md)。

rosbag、canonical HDF5 与 LeRobot Dataset v3 的闭环用法见 [`docs/data_pipeline.md`](docs/data_pipeline.md)；
实机遥操作、相机绑定和首个真实 episode 的依赖顺序见 [`docs/TODO.md`](docs/TODO.md)。

## v0 能做什么

- `rclpy` 订阅三路 RGB，可选三路 depth；图像使用 ROS 2 sensor-data QoS。
- 采集左右 follower 的 qpos/qvel/effort、左右 action、左右 follower EEF。
- EEF 从 ROS 2 `PoseStamped` 的四元数转换为旧 AIO 的 `xyz+rpy`，第 7 维取 follower
  `JointState.position[6]` 的 gripper。
- 交互保持旧流程：ENTER 开始、SPACE 停止、`s` 保存、`q` 丢弃。
- 数据校验和 HDF5 保存位于纯 Python 模块，可在没有 `rclpy`/硬件时测试。
- replay 只有只读预览；默认 dry-run，v0 即使传 `--execute` 也会拒绝执行。
- 双臂 teleop 独立启动且永远从 unarmed 开始；只有显式服务 arming 且四路状态安全时才发布。

在线采集把同一次 snapshot 的 observation 与 leader intent 写入同一帧；当前在线路径没有
executed command 输入，因此保存的 episode 会明确标记为 intent-only。

## 依赖与构建

推荐使用已有的 Conda `piper` 环境。NumPy、h5py 和供 CvBridge 运行的 headless OpenCV
由顶层 `requirements.txt` 固定；
`rclpy`、`sensor_msgs`、`geometry_msgs`、`cv_bridge` 和 launch 包来自
`/opt/ros/humble`，不要通过 pip 安装这些 ROS 包。

OpenCV 固定为 4.11.0.86，与 NumPy 1.26.4 配合；不要改用要求 NumPy 2 的 4.12 系列，
否则会再次触发 ROS Humble CvBridge 的 NumPy 1.x ABI 冲突。

```bash
conda activate piper
source /opt/ros/humble/setup.bash
python -m pip install -r /home/engram/project/piper/piper_aio_ros2/requirements.txt
python -c "import h5py, numpy, rclpy, cv_bridge, cv2"
```

当前构建生成的 console scripts 使用
`/home/engram/miniconda3/envs/piper/bin/python`；切换环境或重建后应重新检查脚本首行。

```bash
cd /home/engram/project/piper/piper_aio_ros2
colcon build --symlink-install
source /home/engram/project/piper/piper_ros2/install/setup.bash
source install/setup.bash
```

目录只保留运行所需的几层：

| 路径 | 用途 |
|---|---|
| `config/` | CAN 角色对应的 ROS 节点参数和采集 topics |
| `deploy/` | 一次性 CAN udev/systemd 部署文件与安装器 |
| `launch/` | 四臂节点编排和交互式采集入口 |
| `piper_aio_ros2/` | 采集、HDF5 episode 和只读 replay 实现 |
| `scripts/` | 日常只读状态检查 |
| `test/` | CAN 配置解析和 episode schema 测试 |
| `docs/PROGRESS.md` | 已验证事实、限制和下一步 |
| `docs/TODO.md` | 实机遥操作、相机和真实数据闭环验收清单 |

采集节点必须在交互式终端运行。先检查并修改 `config/topics.yaml`，再运行：

```bash
ros2 launch piper_aio_ros2 collect.launch.py
# 或换用另一份参数文件
ros2 launch piper_aio_ros2 collect.launch.py config:=/absolute/path/topics.yaml
```

这两个命令只描述用法；构建或安装本包不会启动节点。

## 四臂 CAN 部署

2026-08-13 先通过 sysfs/udev 属性链识别四个 `gs_usb` 设备，随后完成系统部署验证：
稳定接口名、1 Mbps bitrate 和 UP 状态均与配置一致。

| 实机角色 | USB serial | 审计时接口 | 目标稳定接口 |
|---|---|---|---|
| 从右 | `002300374148570D20343133` | `can0` | `can_slave_r` |
| 从左 | `003400204148570A20343133` | `can1` | `can_slave_l` |
| 主左 | `004400314148570C20343133` | `can2` | `can_master_l` |
| 主右 | `003B00234148570A20343133` | `can3` | `can_master_r` |

两路 follower 的初次部署接口名来自运动前的角色判断；首次真实遥操作证明物理左右相反。
`deploy/piper-can.conf` 现已按物理角色修正为 serial、语义稳定接口名和 `BITRATE=1000000` 的
唯一事实源；`config/four_arm.yaml` 同步撤销临时补偿，left/right 再分别使用
`can_slave_l/r`，避免双重翻转。
先做无特权 dry-run：

```bash
cd /home/engram/project/piper/piper_aio_ros2
./deploy/install_can.sh --dry-run
./scripts/can_status.sh
```

当前主机已完成正常重启，`can_status.sh` 实测四路均为目标 serial、稳定接口名、1 Mbps 和 UP。
`colcon build` 只把 ROS launch/config 安装进工作区；它不会写 `/etc`、reload udev、重命名或拉起
CAN，也不会安装/启用 systemd unit。新主机仍须完成下面的显式系统部署后才能启动驱动或 teleop。

本机当时没有在线强改两路 UP 接口的同名循环，而是先安装 conf/udev 规则，再由正常重启按 serial
重新命名；现有 service 已 enabled：

```bash
sudo ./deploy/install_can.sh
sudo reboot
```

全新部署或没有同名循环的主机，才可在停机窗口使用：

```bash
sudo ./deploy/install_can.sh --activate --enable-service
```

该命令会先验证 root、命令依赖、配置重复项、Linux 15 字符接口名上限，以及四个已连接
gs_usb 的 serial/当前状态；只有全部通过才安装下列文件：

- `/etc/piper/piper-can.conf`
- `/etc/udev/rules.d/70-piper-can.rules`
- `/usr/local/sbin/piper-can-up`
- `/etc/systemd/system/piper-can.service`

`--activate` 只在接口 DOWN 且映射正确时把当前接口改为稳定名、设置 1 Mbps 并拉起；
`--enable-service` 只启用 CAN 网络层的 oneshot service。脚本不会启动 ROS、publish CAN
控制帧或使能机械臂。不带 `--activate` 时仅安装文件并 reload udev/systemd 配置，不改变
当前接口；不带 `--enable-service` 时不设置开机拉起。

安装后日常检查不需要 sudo，也不会发送 CAN 或机械臂命令：

```bash
cd /home/engram/project/piper/piper_aio_ros2
./scripts/can_status.sh
systemctl status --no-pager piper-can.service
ip -details link show can_master_l
```

`can_status.sh` 只证明 serial、接口名、bitrate 和 UP 状态正确；业务帧含义仍需单独验证。
2026-08-13 曾用超时保护的被动监听确认四路都有真实流，详见进展文档。

## 四臂 ROS 编排

官方 `piper` 包当前真实 executable 只有 `piper_read_slave_joint` 和
`piper_single_ctrl`。前者只连接 CAN、读取反馈并发布 `JointState`，没有控制订阅、enable
service 或 `auto_enable` 参数，因此用于主左/主右；后者用于从左/从右，配置中明确
`auto_enable: false`。本仓库不 include 官方默认 `auto_enable=true` 的双臂 launch。

```bash
# 只解析参数，不启动节点
ros2 launch piper_aio_ros2 four_arm.launch.py --show-args

# 安装已完成、状态已人工复核后才由用户决定是否实际启动：
# ros2 launch piper_aio_ros2 four_arm.launch.py
```

四个 namespace 和关键 endpoint：

| namespace | 节点 | CAN | feedback | command |
|---|---|---|---|---|
| `/master_left` | `piper_read` | `can_master_l` | `joint_states` | 无 |
| `/master_right` | `piper_read` | `can_master_r` | `joint_states` | 无 |
| `/follower_left` | `piper_ctrl` | `can_slave_l` | `joint_states_feedback`, `end_pose`, `end_pose_stamped` | `joint_ctrl_cmd`, `pos_cmd`, `enable_flag`, `enable_srv` |
| `/follower_right` | `piper_ctrl` | `can_slave_r` | `joint_states_feedback`, `end_pose`, `end_pose_stamped` | `joint_ctrl_cmd`, `pos_cmd`, `enable_flag`, `enable_srv` |

官方控制节点的实际关节命令订阅名是 `joint_ctrl_single`；launch 只把它 remap 为稳定外部
名 `joint_ctrl_cmd`。`joint_states_feedback`、`end_pose`、`end_pose_stamped` 均为官方实际相对
topic，不做多余 remap。namespace 保证四臂 topic/service 不冲突。teleop 不包含在
`four_arm.launch.py` 中，驱动启动不会自动开始遥操作；也没有 `/can_mapping` topic。
`config/topics.yaml` 仅把采集器的 arm
输入改到上述 namespaced feedback，相机 topic 未改。

## 安全双臂 teleop（两阶段对齐已真机观测，0.05 rad 完成门限待复测）

`teleop.launch.py` 单独启动 `/dual_arm_teleop`。节点默认且固定从 unarmed 开始，不调用
`/follower_*/enable_srv`，也不修改 `auto_enable: false`。两侧共同 arming：缺任一 master 或
follower、输入不新鲜、名称/维度/finite 检查失败或任一输入越界时，整体拒绝。

显式 arm 后使用严格的两阶段绝对姿态流程，不保留 relative 偏置，也不会让四条臂自动回机械零位。
arm 瞬间冻结左右 master 目标；第一条 command 严格等于各自 follower 的最新反馈，随后只追冻结目标。
alignment 期间两条 master 必须保持稳定，累计漂移超过配置门限会 fault。左右 follower 都进入
`alignment_joint_tolerance_rad` / `alignment_gripper_tolerance_m` 并连续稳定
`alignment_settle_sec` 后，bridge 才原子切换到实时 master follow，并报告
`dual-arm alignment complete; live follow active`。

alignment 在首秒每 `0.1 s`、随后每秒打印左右最大关节/夹爪剩余误差和 command publish cycle；
超过 `alignment_timeout_sec` 仍未完成会 fault，并在错误中带出两侧残差，不再无限无声等待。
一次真实双侧对齐在 `0.4 s` 内收敛到左 `0.0321 rad`、右 `0.0365 rad` 的近零位稳定残差，因此
完成容差标定为 `0.05 rad`，夹爪仍为 `0.002 m`。默认 master 保持门限为 `0.05 rad` / `0.005 m`，
settle 为 `0.3 s`，timeout 为 `15 s`；0.05 rad 版本仍需真机确认能切入 live follow。

arm 前以及对齐过程中，任一侧主从关节或夹爪距离超过
`max_alignment_joint_error_rad` / `max_alignment_gripper_error_m` 都会拒绝或锁存 fault。默认
`1.0 rad`、`0.08 m` 只是待真机标定的软件安全门限，不是自动规划能力或 Piper 物理极限。80 mm
来自官方 follower 控制代码采用的上限；本机完整行程仍需保存实测。此前 70 mm 门限已被真实 master
开度超过并造成误停，因此不再使用。

官方 reader 源码在 `gripper_exist: true` 时构造 9D
`joint1..joint6,gripper,joint7,joint8`；其中 `gripper` 为占位，bridge 用
`abs(joint7-joint8)` 生成非负开度的 7D `joint1..joint6,gripper`。四条物理臂均有夹爪，配置保持四处
`gripper_exist: true`。本机两路真实 master 已在未使能窗口确认严格 9D name、占位
`gripper=0` 和相反的 `joint7/joint8`；原始差值当时为左 `-0.0003 m`、右 `0.0 m`。由于实机进一步
确认左右 master 的原始夹爪符号可能相反，而官方 follower command 使用开度绝对值，canonical
position 统一为非负开度幅值。
这只确认当前消息输入，夹爪物理方向、零点、单位与完整行程仍待现场扰动标定。映射器能严格
解析 6D reader 输出用于兼容诊断，但 teleop arming 必须有 9D 夹爪输入，绝不会给第 7 维补零。

command 显式填写 `velocity[6]` 和 `effort[6]=gripper_effort`：对齐及正常同步均为 100 Hz/100%。
`velocity[6]` 只被官方节点用于六个臂关节的 `MotionCtrl_2`；官方 `GripperCtrl` 没有速度百分比参数，
只有目标开度和力矩。默认 `gripper_effort: 1.0` 是力矩，不是“夹爪 100% 速度”；快速夹爪跟随通过
直接发送完整开度目标实现。官方 follower feedback 和 master reader 线程均为 200 Hz；bridge 的
100 Hz 是 command timer，不是电机 ACK 频率。任一侧 stale、
非有限、绝对值越界、schema
改变或单步跳变会停止后续双侧发布并
锁存 fault；必须显式 disarm（同时清空旧输入）后，重新收到四路新鲜数据才能再次 arm。
`config/teleop.yaml` 的默认阈值只是保守的软件门禁，不是 Piper 物理极限，必须在真机阶段标定。

推荐使用仓库自带的 tmux 会话，不必手工新建三个 SSH 终端：

```bash
# 在仓库根目录执行；DRIVER 固定为左侧 30%，右侧是 TELEOP / CONTROL
./scripts/teleop_session.sh start
```

`start` 只启动 `four_arm.launch.py` 和默认 unarmed 的 `teleop.launch.py`，绝不 enable 或 arm。
tmux 已开启鼠标，可以直接点击窗格切换。在 CONTROL 窗格按顺序执行：

```bash
./scripts/teleop_control.sh status
./scripts/teleop_control.sh enable   # 显式硬件 enable，不会 arm
./scripts/teleop_control.sh arm      # 开始真实冻结目标 alignment
./scripts/teleop_control.sh stop     # 先 disarm，再 disable 两个 follower
```

按 `Ctrl-b` 后按 `d` 可退出 tmux 画面但保留进程；之后运行
`./scripts/teleop_session.sh attach` 重新进入。鼠标滚轮可看历史日志；若不用鼠标，按 `Ctrl-b` 后按方向键
切窗格。完整停止并关闭整个会话使用：

```bash
./scripts/teleop_session.sh stop
```

若检测到会话之外已经存在旧 launch 或残留 driver/teleop 子进程，`start` 会拒绝创建重复节点。传统的三个
终端方式仍可使用：

```bash
ros2 launch piper_aio_ros2 four_arm.launch.py
ros2 launch piper_aio_ros2 teleop.launch.py
ros2 service call /dual_arm_teleop/arm std_srvs/srv/SetBool "{data: true}"
ros2 service call /dual_arm_teleop/arm std_srvs/srv/SetBool "{data: false}"
```

硬件 enable/disable 是上述 bridge arming 之外的独立人工操作，bridge 永不代办。第一次真机验收
必须逐阶段重新授权：清空从臂工作区并保证急停可触达；硬件未使能时先核对四路 name/单位/夹爪
和 unarmed 零 command；仍未使能时短暂 arm 检查第一条 command 等于 follower 当前反馈、后续两路
7D command 等于 arm 时冻结的 master 目标、100% 速度字段和夹爪 effort，随即 disarm。硬件 enable
后再次 arm 就会开始真实快速对齐运动，应让 master 保持稳定；日志明确报告 live follow active 后
才允许移动 master 做小幅跟随。
任何左右串线、方向/单位错误、未 arm 出现 command、超阈值、跟踪突变、stale
未停发、disarm 失败或异常 enable 都立即停止，disarm bridge 并由人工独立 disable 硬件。

## RealSense 当前边界

本次检查时，ROS 2 Humble 的 RealSense wrapper 4.58.3（camera、camera-msgs、
description）和 ROS librealsense2 2.58.3 已安装在 `/opt/ros/humble`。系统级
librealsense2 runtime/tools 2.58.1（含 `rs-enumerate-devices` 和 `realsense-viewer`）仍并存。

当前 `rs-enumerate-devices -s` 未枚举到相机，因此尚无可记录的 serial，三台物理相机的
serial 映射待连接设备后确定。这只是当前检查结果，连接状态和软件环境可能变化，配置相机
topic 前需要重新确认。

## 默认 topic 映射

| 数据 | 默认 topic | ROS 消息 |
|---|---|---|
| front/left/right RGB | `/camera_f|l|r/color/image_raw` | `sensor_msgs/Image` |
| front/left/right depth | `/camera_f|l|r/depth/image_raw` | `sensor_msgs/Image` |
| follower left/right | `/follower_left/joint_states_feedback`, `/follower_right/joint_states_feedback` | `sensor_msgs/JointState` |
| action left/right | `/master_left/joint_states`, `/master_right/joint_states` | `sensor_msgs/JointState` |
| follower EEF left/right | `/follower_left/end_pose_stamped`, `/follower_right/end_pose_stamped` | `geometry_msgs/PoseStamped` |

后三组由 `four_arm.launch.py` 的 namespace/remap 提供。主臂使用官方只读节点的真实反馈，
不再把从臂控制命令回显当作 leader 测量。采集 YAML 仍只包含 ROS topic；CAN serial/角色
映射在 `deploy/piper-can.conf`，ROS 节点到稳定 CAN 名的参数在 `config/four_arm.yaml`。

图像 contract 与旧 AIO 相同：RGB 必须为 `(480, 640, 3)`；depth 必须为
`(480, 640)`。兼容旧相机路径时，`(400, 640)` depth 会在上下各补 40 行零。

## HDF5 schema

对长度为 `T` 的 episode：

| key | shape / dtype |
|---|---|
| `/observations/images/<camera>` | `(T, 480, 640, 3)`, `uint8` |
| `/observations/images_depth/<camera>` | 可选，`(T, 480, 640)`, `uint16` |
| `/observations/qpos` | `(T, 14)`, `float64` |
| `/observations/qvel` | `(T, 14)`, `float64` |
| `/observations/effort` | `(T, 14)`, `float64` |
| `/observations/eef_pose` | `(T, 14)`, `float64` |
| `/action` | `(T, 14)`, `float64` |
| `/collect` | `(T,)`, UTF-8 string，值为 `teleop` |

Piper ROS 2 当前反馈可能只给 6 个 qvel；v0 将缺失的 gripper qvel 补零，以保持 14 维
schema。文件先写到同目录临时文件，再原子改名；已存在的 episode 不会覆盖。

## replay（始终安全）

```bash
ros2 run piper_aio_ros2 replay /path/to/episode_0.hdf5 --mode joint
ros2 run piper_aio_ros2 replay /path/to/episode_0.hdf5 --mode eef
```

两者只读取并报告 shape，不创建 ROS publisher。`--execute` 是显式的未来执行门，但 v0
会直接报错且不发送任何命令；真正发布路径尚未实现。

## 安全边界与常见诊断

- 未获明确授权时，不运行 `piper_single_ctrl`、teleop 或 `four_arm.launch.py`，不调用 enable
  service，也不发布控制 topic。`auto_enable: false` 不是完整的硬件安全系统。
- `piper_read_slave_joint` 没有运动或使能订阅，但初始化会发送查询帧；它不是零 TX 的被动
  监听器。需要严格被动检查时使用有 timeout 的 `candump`。
- CAN 异常先运行 `./scripts/can_status.sh`，再看
  `systemctl status --no-pager piper-can.service` 和对应接口的 `ip -details link show`；
  不要先重启服务或重插映射。
- ROS 命令不存在时，依次确认 `conda activate piper`、`source /opt/ros/humble/setup.bash`、
  `source /home/engram/project/piper/piper_ros2/install/setup.bash` 和本仓库
  `source install/setup.bash`。
- 只有节点已获授权且正在运行时，才用 `ros2 topic list`、`ros2 topic info <topic>` 和
  `ros2 topic hz <topic>` 做只读检查；不要为诊断启动控制节点。
- 采集一直等待时，逐项确认三个 RGB、四个 JointState 和两个 PoseStamped topic 均有消息，
  且消息时间戳、图像 shape 和关节向量长度符合 contract。

## 尚未验证 / v0 边界

- 未在真实相机、完整 leader/follower/EEF topic 组合上录制并保存 episode。
- 未验证不同设备时钟下的时间戳同步、实际图像 encoding、EEF 坐标系和 RPY 约定。
- 未实现压缩图像、动态分辨率、rosbag 输入、完整 replay 发布或硬件安全系统。
- CAN 系统部署、四路被动流和四臂 launch 的有界真实反馈已验证；四路约 200 Hz，启动各产生
  13 个查询 TX，停止后 TX 不再增长；没有 enable 或运动机械臂。
- 初版绝对映射 teleop 的纯逻辑、隔离 ROS、真实 unarmed 零 command 已验证；用户随后现场完成
  arm、左右单侧及双侧 enable/运动流程并报告动作方向符合，但同时发现两路 follower 物理角色
  反接、10% 跟随过慢。仓库的 serial 语义修正、ROS 补偿撤销、冻结目标的两阶段对齐和
  100 Hz/100% 同步已经代码化；系统映射重启生效后仍需再次真机回归。这不是长时间稳定性或完整
  物理安全认证。
- 相机 serial 绑定、相机 launch 和相机 topic 保持为后续独立任务边界；本次未添加或修改
  相机启动逻辑。

许可证与来源归属见 `LICENSE` 和 `NOTICE`。
