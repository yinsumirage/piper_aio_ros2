# piper_aio_ros2

面向 ROS 2 Humble 的独立采集与四臂编排仓库。它复现
[`piper-aio`](https://github.com/innovator-zero/piper-aio) 的三相机、双臂 episode
交互和主要 HDF5 schema，并把本机 CAN 部署、ROS namespace 与采集配置集中在这里。
官方 `piper_ros2` 提供驱动，`piper-aio` 提供旧采集参考，`piper_sdk` 提供底层 SDK；
三个官方仓库必须保持干净，本仓库不回写它们。

截至 2026-08-13，四路稳定 CAN 接口及被动真实流已验证，主左只读 ROS 路径已做一次
受控检查；相机、EEF、其余三路 ROS 解码和完整 episode 尚未验证。可审计边界见
[`docs/PROGRESS.md`](docs/PROGRESS.md)。

rosbag、canonical HDF5 与 LeRobot Dataset v3 的闭环用法见 [`docs/data_pipeline.md`](docs/data_pipeline.md)。

## v0 能做什么

- `rclpy` 订阅三路 RGB，可选三路 depth；图像使用 ROS 2 sensor-data QoS。
- 采集左右 follower 的 qpos/qvel/effort、左右 action、左右 follower EEF。
- EEF 从 ROS 2 `PoseStamped` 的四元数转换为旧 AIO 的 `xyz+rpy`，第 7 维取 follower
  `JointState.position[6]` 的 gripper。
- 交互保持旧流程：ENTER 开始、SPACE 停止、`s` 保存、`q` 丢弃。
- 数据校验和 HDF5 保存位于纯 Python 模块，可在没有 `rclpy`/硬件时测试。
- replay 只有只读预览；默认 dry-run，v0 即使传 `--execute` 也会拒绝执行。

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

| 角色 | USB serial | 审计时接口 | 稳定接口 |
|---|---|---|---|
| 从左 | `002300374148570D20343133` | `can0` | `can_slave_l` |
| 从右 | `003400204148570A20343133` | `can1` | `can_slave_r` |
| 主左 | `004400314148570C20343133` | `can2` | `can_master_l` |
| 主右 | `003B00234148570A20343133` | `can3` | `can_master_r` |

`deploy/piper-can.conf` 是 serial、稳定接口名和 `BITRATE=1000000` 的部署事实源。
先做无特权 dry-run：

```bash
cd /home/engram/project/piper/piper_aio_ros2
./deploy/install_can.sh --dry-run --activate --enable-service
./scripts/can_status.sh
```

安装前 `can_status.sh` 会准确显示当前 `can0..can3`，并因稳定名/bitrate/state 未就绪返回
非零。`colcon build` 只把 ROS launch/config 安装进工作区；它不会写 `/etc`、reload
udev、重命名或拉起 CAN，也不会安装/启用 systemd unit。

由用户选择停机窗口后，唯一需要的 sudo 安装命令是：

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
topic，不做多余 remap。namespace 保证四臂 topic/service 不冲突。当前没有 teleop 节点，也没有
`/can_mapping` topic；主臂反馈不会自动发送给从臂。`config/topics.yaml` 仅把采集器的 arm
输入改到上述 namespaced feedback，相机 topic 未改。

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
- CAN 系统部署和四路被动流已验证；四臂 launch 只做静态/解析验证，未整体启动。
  主左只读 ROS 路径单独检查过，初始化有非零查询 TX；未使能或运动机械臂。
- 相机 serial 绑定、相机 launch 和相机 topic 保持为后续独立任务边界；本次未添加或修改
  相机启动逻辑。

许可证与来源归属见 `LICENSE` 和 `NOTICE`。
