# piper_aio_ros2

面向 ROS 2 Humble 的独立 v0 采集包。当前目标是先复现
[`piper-aio`](https://github.com/innovator-zero/piper-aio) 的三相机、双臂 episode
采集交互和主要 HDF5 schema；它不会启动 Piper 驱动、配置 CAN、使能机械臂或控制硬件。

## v0 能做什么

- `rclpy` 订阅三路 RGB，可选三路 depth；图像使用 ROS 2 sensor-data QoS。
- 采集左右 follower 的 qpos/qvel/effort、左右 action、左右 follower EEF。
- EEF 从 ROS 2 `PoseStamped` 的四元数转换为旧 AIO 的 `xyz+rpy`，第 7 维取 follower
  `JointState.position[6]` 的 gripper。
- 交互保持旧流程：ENTER 开始、SPACE 停止、`s` 保存、`q` 丢弃。
- 数据校验和 HDF5 保存位于纯 Python 模块，可在没有 `rclpy`/硬件时测试。
- replay 只有只读预览；默认 dry-run，v0 即使传 `--execute` 也会拒绝执行。

v0 有意保留旧采集器的时序配对：第一帧 observation 先缓存，之后把上一帧 observation
与当前帧 action 配对，最后一个 observation 不写入。是否修正这一时序需用真实数据验证后再决定。

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
source install/setup.bash
```

采集节点必须在交互式终端运行。先检查并修改 `config/topics.yaml`，再运行：

```bash
ros2 launch piper_aio_ros2 collect.launch.py
# 或换用另一份参数文件
ros2 launch piper_aio_ros2 collect.launch.py config:=/absolute/path/topics.yaml
```

这两个命令只描述用法；构建或安装本包不会启动节点。

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
| follower left/right | `/joint_left`, `/joint_right` | `sensor_msgs/JointState` |
| action left/right | `/joint_states_ctrl_left`, `/joint_states_ctrl_right` | `sensor_msgs/JointState` |
| follower EEF left/right | `/end_pose_stamped_left`, `/end_pose_stamped_right` | `geometry_msgs/PoseStamped` |

后三组默认值来自已检查的 `piper_ros2/src/piper/launch/start_two_piper.launch.py`。其中
`/joint_states_ctrl_*` 是 Piper 控制命令回显，不是独立物理 leader 的测量；若系统存在真正的
leader 发布者，必须把 `topics.leader_action_left/right` 改成对应的 `JointState` topic。YAML
只包含 ROS topic，不包含 CAN 口或设备映射。

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

## 尚未验证 / v0 边界

- 未在真实相机、真实 leader/follower topic 或 Piper 硬件上运行。
- 未验证不同设备时钟下的时间戳同步、实际图像 encoding、EEF 坐标系和 RPY 约定。
- 未实现压缩图像、动态分辨率、rosbag 输入、完整 replay 发布或硬件安全系统。
- ROS 2 官方双臂 launch 本身默认 `auto_enable=true`；本仓库不会启动它。硬件侧启动和
  CAN/使能流程不属于本 v0。

许可证与来源归属见 `LICENSE` 和 `NOTICE`。
