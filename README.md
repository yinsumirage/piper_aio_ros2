# piper_aio_ros2

`piper_aio_ros2` 是运行在 ROS 2 Humble 上的 Piper 四臂集成仓库，负责：

- 按 USB serial 固定四路 CAN 角色；
- 编排双主臂、双从臂和三台 Intel RealSense；
- 提供默认不动作、显式 enable/arm 的双臂主从遥操作；
- 用白名单录制 rosbag，并转换为 canonical HDF5 和 LeRobot Dataset v3；
- 保留只读 replay，禁止直接向机械臂回放。

官方 `piper_ros2` 提供 ROS 驱动，`piper_sdk` 提供底层 SDK，`piper-aio` 仅作为旧采集实现参考。
三个官方仓库必须保持干净；本仓库不回写它们。

## 当前状态

截至 2026-08-14：

| 能力 | 状态 | 证据边界 |
|---|---|---|
| 四路 CAN serial 绑定 | 已验证 | 稳定接口名、1 Mbps、UP 和重启后映射通过 |
| 四臂 ROS 编排 | 已接入 | 四路真实反馈约 200 Hz；driver 启动会产生查询 TX |
| 双臂主从遥操作 | 已接入 | 默认 unarmed、显式双侧门禁和真实对齐响应已验证；最终 0.05 rad 完成门限仍需一次完整 live-follow 回归 |
| 三台 RealSense | 已接入 | serial→角色、RGB8 640×480、三路约 30 Hz 短包和抽帧通过；长时与拔插重连待验证 |
| bag→HDF5→LeRobot | 软件链路已验证 | 合成 11-topic 闭环通过；真实完整 11-topic episode 尚未验收 |
| 硬件 replay | 未实现 | `--execute` 明确拒绝，不创建 command publisher |

“已接入”表示代码和运行入口已经组成完整系统，不自动等同于长时间稳定性、物理安全认证或真实
episode 内容验收。详细事实见 [`docs/PROGRESS.md`](docs/PROGRESS.md)。

## 版本定义

本仓库只使用下面四个互不替代的版本概念：

| 名称 | 当前值 | 含义 |
|---|---|---|
| package version | `0.2.0` | 本仓库软件发布版本，见 `package.xml` 与 `setup.py` |
| HDF5 schema version | `1` | canonical episode 文件合同，见 `piper_aio_ros2/episode.py` |
| LeRobot dataset format | `v3` | 导出的数据集格式 |
| LeRobot Python package | `0.6.0` | 当前固定并验证过的导出依赖 |

文档不再用含混的“v0/v1”描述项目进度，而使用“已验证 / 已接入待验证 / 未实现”。正式发布时
Git tag 应与 package version 一致；当前仓库尚未创建 release tag。

## 环境与构建

默认环境是 Conda `piper`、ROS 2 Humble、官方 `piper_ros2` overlay，再 source 本仓库：

```bash
conda activate piper
source /opt/ros/humble/setup.bash
source /home/engram/project/piper/piper_ros2/install/setup.bash

cd /home/engram/project/piper/piper_aio_ros2
python -m pip install -r requirements.txt
colcon build --symlink-install
source install/setup.bash
```

顶层环境固定 NumPy 1.26.4、h5py 3.16.0 和 OpenCV 4.11.0.86，避免 ROS Humble CvBridge 与
NumPy 2 的 ABI 冲突。LeRobot 使用独立的 `lerobot-piper` 环境，见
[`docs/data_pipeline.md`](docs/data_pipeline.md)。

## 目录

| 路径 | 用途 |
|---|---|
| `config/` | CAN/ROS、相机、teleop 和录包白名单 |
| `deploy/` | CAN udev/systemd 配置及一次性安装器 |
| `launch/` | 四臂、三相机、teleop 和旧在线采集入口 |
| `piper_aio_ros2/` | 录包检查、转换、schema、相机、teleop 和 replay 实现 |
| `scripts/` | CAN 状态、录包、teleop 会话和 LeRobot wrapper |
| `test/` | 数据合同、CAN 配置、相机配置和 teleop 核心测试 |
| `docs/OPERATIONS.md` | 从开终端到录包、停止和转换的操作流程 |
| `docs/PROGRESS.md` | 已验证事实、未验证项和证据边界 |
| `docs/TODO.md` | 只保留尚未完成的工作 |
| `docs/data_pipeline.md` | rosbag、HDF5 与 LeRobot 数据合同 |

## 四臂硬件映射

`deploy/piper-can.conf` 是 serial→稳定接口名的唯一事实源：

| 角色 | USB serial | 稳定接口 |
|---|---|---|
| 从左 | `003400204148570A20343133` | `can_slave_l` |
| 从右 | `002300374148570D20343133` | `can_slave_r` |
| 主左 | `004400314148570C20343133` | `can_master_l` |
| 主右 | `003B00234148570A20343133` | `can_master_r` |

新主机先做无特权检查；只有明确授权的部署窗口才能运行安装：

```bash
./deploy/install_can.sh --dry-run
./scripts/can_status.sh

# 一次性系统部署；会写 /etc，必须单独获得授权
sudo ./deploy/install_can.sh
sudo reboot
```

日常只读检查不需要 sudo：

```bash
./scripts/can_status.sh
systemctl status --no-pager piper-can.service
ip -details link show can_master_l
```

CAN service 只配置网络接口，不启动 ROS、不 enable 机械臂，也不证明业务 topic 正确。

## ROS namespace 与 topic

| namespace | 节点 | CAN | 主要输出/输入 |
|---|---|---|---|
| `/master_left` | `piper_read` | `can_master_l` | `joint_states` |
| `/master_right` | `piper_read` | `can_master_r` | `joint_states` |
| `/follower_left` | `piper_ctrl` | `can_slave_l` | `joint_states_feedback`、`end_pose_stamped`、`joint_ctrl_cmd` |
| `/follower_right` | `piper_ctrl` | `can_slave_r` | `joint_states_feedback`、`end_pose_stamped`、`joint_ctrl_cmd` |
| `/camera_f` | RealSense | serial `335622070696` | `color/image_raw` |
| `/camera_l` | RealSense | serial `349622073361` | `color/image_raw` |
| `/camera_r` | RealSense | serial `335622072178` | `color/image_raw` |

两路 follower 保持 `auto_enable: false`。`four_arm.launch.py` 不包含 teleop；启动 driver 不会自动
进入主从控制。官方 reader 初始化会发送查询帧，因此不是严格零 TX 的被动监听器。

## 采集路径

### 正式路径：rosbag

正式训练数据以 `config/record_topics.yaml` 的 11-topic 白名单为准：三路 RGB、双 follower state、
双 master intent、双 follower EEF、双 teleop command。录包、检查、转换与导出命令见
[`docs/OPERATIONS.md`](docs/OPERATIONS.md)。

当前所有 stream config 都必须包含恰好三路 RGB。`config/camera_record_topics.yaml` 是三相机短包
诊断白名单，不是完整 episode。

### 保留路径：在线 Python collector

`collect.py`、`collect.launch.py` 和 `config/topics.yaml` 暂时保留，作为旧交互式采集和后续在线
collector 重构的基础：

```bash
ros2 launch piper_aio_ros2 collect.launch.py
```

这条路径目前没有复用 rosbag 转换器的因果 action 选择和同步容差，不作为正式训练数据的推荐入口。
后续若继续发展，应与 canonical 同步合同共用实现，而不是维护第二套隐式同步规则。

## Teleop 与安全边界

`teleop.launch.py` 始终从 unarmed 开始，不自动调用 `/follower_*/enable_srv`。显式 arm 需要左右
master/follower 输入同时新鲜、finite、名称完整且未越界；任一侧 stale、跳变或超限都会停止双侧
发布并锁存 fault。

主臂严格使用 9D `joint1..joint6,gripper,joint7,joint8`，canonical gripper opening 为
`abs(joint7-joint8)`；占位 `gripper` 不用于命令。teleop 发布的 `joint_ctrl_cmd` 是发给 follower
控制节点的 commanded action，不是电机 ACK，实际跟踪必须看 follower state。

真正的 `enable` 或 `arm` 会导致机械臂运动，只能在工作区清空、急停可触达并获得明确授权后执行。
完整的终端顺序、开始/停止顺序和录包流程见 [`docs/OPERATIONS.md`](docs/OPERATIONS.md)。

## Replay

```bash
ros2 run piper_aio_ros2 replay /path/to/episode.hdf5 --mode joint
ros2 run piper_aio_ros2 replay /path/to/episode.hdf5 --mode eef
```

replay 只读取并打印 shape。`--execute` 会报错退出，不发送任何 ROS 或 CAN command。

## 常见诊断

- ROS 命令不存在：依次确认 Conda、ROS Humble、官方 overlay 和本仓库 overlay 已 source。
- CAN 异常：先运行 `./scripts/can_status.sh`，不要先重启服务或改映射。
- 相机异常：运行 `ros2 run piper_aio_ros2 realsense_inventory`，再检查配置 serial 与在线设备。
- 录包 preflight 失败：按 JSON 报告检查缺失 topic、类型、publisher、磁盘和额外 control publisher。
- 转换失败：先运行 `bag_inspect`；不要把缺 topic、无 command 或同步失败的 bag 标成完整 episode。
- 停止后先检查残留 ROS 进程、相机节点和 CAN TX，不使用宽泛 `pkill`。

许可证与来源归属见 `LICENSE` 和 `NOTICE`。
