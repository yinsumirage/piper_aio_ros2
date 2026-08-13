# 数据闭环

本仓库 `0.2.0` 把一个 episode 分成三层：显式白名单 rosbag 保存原始 ROS 消息，离线转换为
canonical HDF5 schema `1`，再导出为本地 LeRobot Dataset v3。录包和转换工具只订阅/读取
数据，不启动驱动、相机、控制节点，不使能机械臂，也不发送控制消息。

## 录包合同

`config/record_topics.yaml` 是 11 个 topic 的唯一白名单；脚本从不使用 `ros2 bag record -a`：

| 流 | topic | 类型 |
|---|---|---|
| front RGB | `/camera_f/color/image_raw` | `sensor_msgs/msg/Image` |
| left RGB | `/camera_l/color/image_raw` | `sensor_msgs/msg/Image` |
| right RGB | `/camera_r/color/image_raw` | `sensor_msgs/msg/Image` |
| left follower state | `/follower_left/joint_states_feedback` | `sensor_msgs/msg/JointState` |
| right follower state | `/follower_right/joint_states_feedback` | `sensor_msgs/msg/JointState` |
| left leader intent | `/master_left/joint_states` | `sensor_msgs/msg/JointState` |
| right leader intent | `/master_right/joint_states` | `sensor_msgs/msg/JointState` |
| left follower EEF | `/follower_left/end_pose_stamped` | `geometry_msgs/msg/PoseStamped` |
| right follower EEF | `/follower_right/end_pose_stamped` | `geometry_msgs/msg/PoseStamped` |
| left executed command | `/follower_left/joint_ctrl_cmd` | `sensor_msgs/msg/JointState` |
| right executed command | `/follower_right/joint_ctrl_cmd` | `sensor_msgs/msg/JointState` |

默认不录 depth。运行前 preflight 会以 JSON 检查 topic 存在、类型、publisher、磁盘空间及
输出目录；缺相机时明确失败。脚本自动创建目标父目录，目标目录已存在时拒绝覆盖，录包使用
zstd message compression。
control-topic 检查只放行白名单以及两个精确的官方反馈 topic
`/follower_left/joint_ctrl`、`/follower_right/joint_ctrl`；其他 `joint_ctrl`、`pos_cmd`、
`gripper_ctrl`、`enable_flag` 或 `/control/` publisher 仍会阻止录包。隔离 ROS 图已用 11 个
白名单 publisher 加这两条官方反馈做过回归，未连接驱动或 CAN。

```bash
conda activate piper
source /opt/ros/humble/setup.bash
source /home/engram/project/piper/piper_ros2/install/setup.bash
source /home/engram/project/piper/piper_aio_ros2/install/setup.bash
cd /home/engram/project/piper/piper_aio_ros2

ros2 run piper_aio_ros2 bag_preflight --config config/record_topics.yaml --output-dir /data/episode_000
./scripts/record_bag.sh /data/episode_000
```

上述命令假定所需 publisher 已经由用户按独立安全流程启动；本仓库的录包脚本不会代为启动。
默认 `config/record_topics.yaml` 是包含三路 RGB 的 11-topic 整体 profile；
`scripts/record_cameras.sh` + `config/camera_record_topics.yaml` 是相机-only 诊断案例。
`record_bag.sh` 的第二个参数可以换成另一份 stream config，但当前 loader 要求每份配置都包含恰好
三路 RGB；无图像或少于三相机的 profile 尚未实现。完整 episode 转换还要求双侧 state、EEF、
intent，并默认要求双侧 executed command。

## canonical HDF5 schema 1

一个 rosbag 目录转换成一个 HDF5 episode。14 维关节顺序固定为：

```text
left_joint1..left_joint6, left_gripper,
right_joint1..right_joint6, right_gripper
```

所有 `JointState` 都按 `name` 映射，不能按数组前 7 项截取。普通 follower 的 7 维消息使用
`gripper`；官方 master 的 9 维消息
`joint1..joint6,gripper,joint7,joint8` 使用 `abs(joint7 - joint8)` 作为 canonical gripper opening，
忽略固定占位的 `gripper`。所有 position gripper 都归一化为非负开度；position 必须完整且 finite，
velocity/effort 缺失时补 0。
为兼容旧 `piper-aio` 遥操 publisher，唯一额外别名是 7D `joint0..joint6`：其中
`joint0..joint5` 映射到 canonical `joint1..joint6`，`joint6` 映射到 gripper；它同样按
`JointState.name` 重排并支持乱序，空 `name` 不做位置猜测。

主要键为：

| key | 合同 |
|---|---|
| `/observations/images/{cam_high,cam_left_wrist,cam_right_wrist}` | `(T,480,640,3)` HWC `uint8` |
| `/observations/qpos`, `/observations/qvel`, `/observations/effort` | `(T,14)` |
| `/observations/eef_pose` | `(T,14)` |
| `/action` | `(T,14)`，由根属性 `action_source` 指明来源 |
| `/actions/intent`, `/actions/executed` | `(T,14)` |
| `/actions/executed_valid` | `(T,)` bool |
| `/timestamps/frame_ns` | `(T,)` 固定网格时间 |
| `/timestamps/source_ns/<stream>` | `(T,)` 源消息时间 |
| `/sync_delta_ns/<stream>` | `(T,)` 源时间减目标时间 |

根属性包括 `schema_version=1`、`fps`、`action_source`、`joint_order`、`topic_map` 和
`created_by`。正式训练的 `/action` 默认必须来自 executed command。若 bag 没有两路
executed stream，转换只有在显式 `--allow-intent-only` 时才生成 intent-only episode；其
`action_source=intent` 且 `executed_valid=false`，不会冒充已执行动作。

这里的 executed 是实际发布给 follower 控制节点的 commanded action，不是电机已经执行该动作的
闭环测量或 ACK；当前 teleop bridge 的两路 command publisher 正是 executed stream 的来源，
物理跟踪结果仍以 follower state 为准。

转换采用 30 Hz 固定网格。RGB 最近邻容差 20 ms，state/EEF 最近邻容差 10 ms；intent 和
executed 只因果选择目标时刻之前最近一条，容差 20 ms，绝不选择未来 action。优先使用正数
header stamp，否则使用 bag receive time。任一必需流缺失或超容差会丢弃该目标帧；同一相机
源帧若被重复选择，转换拒绝输出，不用复制旧图像伪造有效帧。图像按第二遍 reader 只解码已选
帧，避免把整包 RGB 放进内存。转换同时生成含 rate、overlap、丢帧原因、同步 delta 和 action
来源的 QC JSON。

```bash
ros2 run piper_aio_ros2 bag_inspect /data/episode_000 --config config/record_topics.yaml
ros2 run piper_aio_ros2 bag_to_hdf5 /data/episode_000 /data/episode_000.hdf5 \
  --config config/record_topics.yaml
ros2 run piper_aio_ros2 validate_episode /data/episode_000.hdf5
```

若必须保留只有 leader intent 的历史 bag，应显式加 `--allow-intent-only`，并保留验证器报告
中的 action_source 边界。

## LeRobot Dataset v3

LeRobot 环境与 ROS 环境分离；`requirements/lerobot.txt` 固定 `lerobot[dataset]==0.6.0`。
首次创建环境可运行：

```bash
./scripts/setup_lerobot_env.sh
```

脚本只对当前命令使用清华 conda-forge/PyPI 镜像，不修改全局 condarc 或 pip 配置；可用
`LEROBOT_CONDA_CHANNEL`、`LEROBOT_PYPI_INDEX_URL`、`LEROBOT_ENV_NAME` 和
`LEROBOT_PYTHON_VERSION` 覆盖。若 `lerobot-piper` 已存在，脚本只报告 Python、LeRobot、
h5py、PyTorch 和 CUDA 状态，不安装或重装任何包。

导出 wrapper 默认执行 `conda run -n lerobot-piper`，并与 setup 脚本共用
`LEROBOT_ENV_NAME` 覆盖；用户不需要手动切换环境：

```bash
./scripts/export_lerobot.sh /data/episode_000.hdf5 \
  --output /data/lerobot/piper_demo \
  --repo-id local/piper_demo \
  --task "双臂遥操作示例"
```

默认只接受 `action_source=executed`；intent-only 输入只有显式传
`--allow-intent-only` 才会导出；同一次导出的所有 episode 必须使用一致的 action_source，禁止
把 intent 与 executed 混进同一个 Dataset。三路 HWC `uint8` 输入写成 LeRobot v3 标准 video feature，
由 `dataset.finalize()` 生成 MP4 和 v3 元数据。输出保持本地，不 push Hub，并拒绝覆盖已有目录。

## 已验证与边界

纯同步函数、schema/save、验证器，以及合成数据的 HDF5 到三路 LeRobot video、finalize 和
Dataset v3 回读已验证。主任务还用 30 帧、11 topic 合成 rosbag 跑通过
inspect -> HDF5 -> validate -> LeRobot reload，并用隔离的合成 publisher 验证了 11 topic
preflight 与 file/zstd 录包；精确 30 Hz、30 帧的 file/zstd 合成 bag 已跑通
inspect -> HDF5 -> validate，得到 30/30 帧且 `action_source=executed`。

三台真实相机已完成 serial→角色绑定、三路 RGB8 640×480 短包和 PNG 抽帧检查；长 episode、
相机拔插重连以及包含机械臂状态/action/EEF 的完整 11-topic 真机录制仍未验证。上述合成
file/zstd 证据继续覆盖转换链，真实相机短包则使用 zstd message compression；两者都不能替代
完整 episode 验收。

teleop 另在隔离 ROS domain 中验证了默认 unarmed 零 command、显式 arming 后左右均发布有界
7D command、输入 stale 后停止；真实四路输入窗口也验证了 unarmed 时 4.02 秒左右均为零
command。两路真实 master 已确认严格 9D name、占位 `gripper=0` 及 `joint7/joint8` 成对相反；
后续真机运动暴露左右原始差值符号不一致，因此 canonical position 已统一为开度幅值。这些仍不是
硬件 ACK、夹爪完整行程标定或修复后的真实四臂运动验证。最新 bridge 采用官方控制代码中的
80 mm 上限，首帧保持 follower 后发送完整 master 绝对目标；`velocity[6]=100` 只控制六个臂关节，
`gripper_effort=1.0` 是夹爪力矩而非速度。当前 0.05 rad 完成门限仍需保存一次完整 live-follow 回归。
