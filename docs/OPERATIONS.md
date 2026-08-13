# 操作流程

本文给出当前系统从环境准备、启动、录包到停止和转换的推荐顺序。真正的 follower `enable` 或
teleop `arm` 会导致机械臂运动，必须由现场操作者明确授权并保证工作区清空、急停可触达。

## 1. 每个终端先加载环境

```bash
conda activate piper
source /opt/ros/humble/setup.bash
source /home/engram/project/piper/piper_ros2/install/setup.bash
source /home/engram/project/piper/piper_aio_ros2/install/setup.bash
cd /home/engram/project/piper/piper_aio_ros2
```

建议准备三个 SSH 终端：

| 终端 | 用途 |
|---|---|
| A | 三台 RealSense launch |
| B | 四臂 driver、teleop 和 CONTROL；由 tmux 管理三个窗格 |
| C | rosbag preflight、录制、检查和转换 |

## 2. 启动前只读检查

先确认仓库版本和 CAN 网络状态：

```bash
git status --short --branch
git rev-parse HEAD
./scripts/can_status.sh
```

确认三台相机与配置中的 serial 都在线：

```bash
ros2 run piper_aio_ros2 realsense_inventory
ros2 run piper_aio_ros2 camera_status \
  --config config/cameras.yaml --devices-only
```

检查没有旧会话或残留控制进程：

```bash
./scripts/teleop_session.sh status
```

如果发现旧进程，先识别其终端和 PID，并按原会话的停止流程清理；不要使用宽泛 `pkill`。CAN
接口异常时先保存 `can_status.sh` 和 `ip -details link show` 输出，不要直接修改系统部署。

## 3. 终端 A：启动三台 RealSense

```bash
ros2 launch piper_aio_ros2 three_realsense.launch.py \
  config:=$PWD/config/cameras.yaml
```

launch 会在创建节点前检查配置 serial 与在线设备。当前固定输出为：

- front：`/camera_f/color/image_raw`
- left：`/camera_l/color/image_raw`
- right：`/camera_r/color/image_raw`

如需录一个不含机械臂的三相机诊断短包，在终端 C 运行：

```bash
./scripts/record_cameras.sh /home/engram/data/piper/camera_check_001 10
```

该脚本依次执行 camera status、三 topic preflight、限时 zstd 录制和自动 `bag_inspect`。

## 4. 终端 B：启动四臂 driver 与默认 unarmed teleop

以下命令会启动真实 Piper driver。即使没有 enable，官方 reader 初始化也会产生查询 CAN TX；必须
在已经确认 CAN 角色和现场边界后执行：

```bash
./scripts/teleop_session.sh start
```

tmux 布局为：

- 左侧 DRIVER：`four_arm.launch.py`
- 右上 TELEOP：默认 unarmed 的 `teleop.launch.py`
- 右下 CONTROL：人工执行 status、enable、arm 和 stop

启动本身不会 enable 或 arm。先在 CONTROL 窗格运行：

```bash
./scripts/teleop_control.sh status
```

确认两路 follower 为 `auto_enable=false`、四路输入在线、teleop 日志为 unarmed。此时不要移动主臂
来推断跟随，因为 bridge 尚未发布 command。

## 5. 终端 C：在运动前开始完整 rosbag

正式 episode 使用 `config/record_topics.yaml` 的 11-topic 白名单。`record_bag.sh` 会先运行
preflight，成功后才开始录制：

```bash
./scripts/record_bag.sh /home/engram/data/piper/episode_001
```

preflight 只证明 topic/type/publisher/磁盘和 control publisher 合同满足，不证明每路随后一定有消息。
因此必须在录制结束后运行 `bag_inspect`。

建议在 teleop 仍 unarmed 时先开始录包，以保留动作前状态；转换时有效 overlap 会从第一条 executed
command 开始。

## 6. CONTROL：显式开始主从遥操作

以下两步会改变硬件状态。只有获得本次运动授权后才执行：

```bash
./scripts/teleop_control.sh enable
./scripts/teleop_control.sh arm
```

`enable` 要求左右 follower 都成功，否则尝试回滚为双侧 disabled。`arm` 会冻结当时的左右 master
目标，第一条 command 保持 follower 当前反馈，随后开始真实对齐；两侧达到容差并稳定 0.3 秒后才
进入 live follow。

操作顺序：

1. enable/arm 前让两条 master 保持静止；
2. 等待 `dual-arm alignment complete; live follow active`；
3. 先做单侧、小幅、单关节动作；
4. 再检查夹爪，最后才做双侧动作；
5. 任一串线、方向错误、突变、fault 或异常停发都立即执行 stop。

## 7. 停止顺序

先在终端 C 按一次 `Ctrl+C` 正常结束 rosbag，等待 recorder 写完 metadata 并返回 shell。

随后在另一个已加载环境的终端运行：

```bash
./scripts/teleop_session.sh stop
```

`teleop_session.sh stop` 会先调用 control stop，按 disarm→disable 两个 follower 的顺序退出，再关闭
tmux。关闭 tmux 本身不等于硬件 disable，不能只杀 launch 进程。最后在终端 A 按一次 `Ctrl+C`
停止相机 launch。

停止后检查：

```bash
./scripts/teleop_session.sh status
./scripts/can_status.sh
ros2 node list
```

确认没有 driver、teleop、camera 或 recorder 残留；对需要严格检查的硬件窗口，再确认短时间内 CAN
TX 不继续增长。

## 8. 检查并转换 episode

```bash
ros2 run piper_aio_ros2 bag_inspect \
  /home/engram/data/piper/episode_001 \
  --config config/record_topics.yaml

ros2 run piper_aio_ros2 bag_to_hdf5 \
  /home/engram/data/piper/episode_001 \
  /home/engram/data/piper/episode_001.hdf5 \
  --config config/record_topics.yaml

ros2 run piper_aio_ros2 validate_episode \
  /home/engram/data/piper/episode_001.hdf5
```

只有 `bag_inspect` 和 `validate_episode` 都成功、QC 中存在有效同步帧且
`action_source=executed`，才能进入正式训练数据候选集。

导出 LeRobot Dataset v3：

```bash
./scripts/export_lerobot.sh /home/engram/data/piper/episode_001.hdf5 \
  --output /home/engram/data/lerobot/piper_episode_001 \
  --repo-id local/piper_episode_001 \
  --task "双臂主从遥操作"
```

最后必须重新加载 Dataset，并人工观看三路视频、核对左右 master intent、command、follower state 和
EEF。bag、HDF5、QC、图片、视频和 LeRobot 输出都保留在数据目录，不提交 Git。

## 9. 只使用旧在线 collector

旧入口仍可用于开发：

```bash
ros2 launch piper_aio_ros2 collect.launch.py \
  config:=$PWD/config/topics.yaml
```

它目前不复用 rosbag 转换器的同步合同，因此输出只能作为实验数据；在完成因果 action 选择、同步
容差和保存后 validate 门禁前，不进入正式数据集。
