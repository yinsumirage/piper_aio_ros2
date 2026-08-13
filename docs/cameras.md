# 三台 Intel RealSense 部署与验收

本流程只管理相机，不启动机械臂、teleop 或控制 publisher。RealSense 属于 ROS 2 Humble
系统环境；不要在 `piper` 或 LeRobot Conda 环境中另装 wrapper/librealsense。

截至 2026-08-13 的只读审计：`realsense2_camera` 4.58.3 与其 ROS `librealsense2` 2.58.3
位于 `/opt/ros/humble`；系统 `rs-enumerate-devices`/runtime/udev rules 为 2.58.1；官方
`rs_launch.py` 已确认使用 `serial_no`、`camera_namespace`、`camera_name`、
`rgb_camera.color_profile` 与 `rgb_camera.color_format`。初审时 `rs-enumerate-devices -s`
返回 `No device detected`；稍后三台 D435 接入，已记录真实 inventory，并分别按 serial 有界启动，
确认三台都能打开 RGB8 640×480@30 及发布 `sensor_msgs/msg/Image`。用户随后根据按 serial
命名的三张真实预览确认并写入物理角色；三台同时长时帧率与重连仍待后续性能验收。

| serial | model | firmware | USB | 审计时 physical port |
|---|---|---|---|---|
| `349622073361` | D435 | 5.17.0.10 | 3.2 | `.../2-8.1.1/.../video12` |
| `335622070696` | D435 | 5.17.0.10 | 3.2 | `.../2-8.1.2/.../video6` |
| `335622072178` | D435 | 5.15.1.55 | 3.2 | `.../2-8.1.3/.../video0` |

用户确认的唯一映射是 front=`335622070696`、left=`349622073361`、right=`335622072178`。
三台当时都经过 Bus 02 的同一条 5 Gbps Hub 链路；这是待做三路同时带宽验收的风险提示，
不是掉帧结论。`/dev/video*` 为 `root:plugdev` 且有当前用户读写 ACL，三台实际打开成功，所以
当前没有需要 sudo/udev 修复的权限缺口。

## 0. 每个终端的环境

```bash
source /opt/ros/humble/setup.bash
source /home/engram/project/piper/piper_ros2/install/setup.bash
source /home/engram/project/piper/piper_aio_ros2-camera/install/setup.bash
cd /home/engram/project/piper/piper_aio_ros2-camera
```

若系统工具、ROS package 或设备权限确有缺口，先保存错误和设备节点权限，不要直接 `sudo apt`
或改 udev。当前软件已齐全；用户不在 `video` 组本身不能证明相机访问会失败。

## A. 插三台并保存真实 inventory

将三台相机直接接到 USB 3.x 端口；暂时不要根据插口顺序命名角色。运行：

```bash
./scripts/realsense_inventory.sh | tee ~/realsense-inventory-$(date +%F).txt
```

命令最多等待 10 秒，列出每台的 serial、model、firmware、USB type 与 physical port；没有设备、
工具缺失或超时时会返回非零。预期正好三行设备，且每个 serial 唯一。若 USB type 显示 2.x，
先换线、端口或拓扑再继续。`Ctrl+C` 可停止，脚本不启动后台进程。

## B. 人工认定 front / left / right

角色含义固定为：`front` 是正面高位相机，`left` 是左腕相机，`right` 是右腕相机。推荐逐台
操作：只保留一台连接，重新 inventory 并记录 serial，摆到目标位置；三台都确认后再一起插回。
也可按 serial 单台预览，但仍必须由人看画面和物理相机标签，不能按 USB 或输出顺序猜：

```bash
ros2 launch realsense2_camera rs_launch.py \
  serial_no:=_填真实serial camera_namespace:='' camera_name:=role_preview \
  enable_depth:=false rgb_camera.color_profile:=640x480x30 \
  rgb_camera.color_format:=RGB8 wait_for_device_timeout:=5.0

# 另一个终端看预览；确认后两个终端都 Ctrl+C
ros2 run rqt_image_view rqt_image_view /role_preview/color/image_raw
```

如果 `rqt_image_view` 不可用，可用 `realsense-viewer` 人工查看；不要为此安装新的 Python 相机包。

## C. 写配置并先做严格设备 status

三台同时在线后，把 A/B 得到的真实编号传给 assignment：

```bash
./scripts/assign_cameras.sh --config config/cameras.yaml \
  --front 填真实front_serial --left 填真实left_serial --right 填真实right_serial
```

脚本要求当前恰好三台设备、三个非空且唯一 serial、配置集合与当前设备集合完全相同，显示
`role -> serial -> topic` 后还要键入 `WRITE` 才原子写入。也可省略三个角色参数进入逐项输入。
随后运行：

```bash
./scripts/camera_status.sh --config config/cameras.yaml --devices-only
```

空值、重复、离线或换了设备均返回非零；`config/cameras.yaml` 是 serial→角色唯一事实源。

## D. 逐台按 serial 启动和验收

先一次只启动一个角色，以下将 `front` 依次改成 `left`、`right`：

```bash
ros2 launch piper_aio_ros2 three_realsense.launch.py \
  config:=$PWD/config/cameras.yaml role:=front
```

另一个终端做 20 秒有界检查：

```bash
./scripts/camera_status.sh --config config/cameras.yaml --role front --sample-seconds 20
```

将 `--role front` 依次改成 left/right。默认以“可绑定、可录制”为门禁：type、唯一 publisher、
encoding、shape、header timestamp 不满足才失败；帧率和 >100 ms 间断列入 `warnings`，不会阻塞。
需要调优/验收 30 Hz 时显式加 `--require-nominal-rate`。也可补充查看 publisher：

```bash
timeout 5s ros2 topic info -v /camera_f/color/image_raw
timeout 15s ros2 topic hz /camera_f/color/image_raw
```

确认消息类型 `sensor_msgs/msg/Image`、`rgb8`、640×480、约 30 Hz、header stamp 非零且向前；
同时预览画面，人工确认物理角色。每台验收后在 launch 终端 `Ctrl+C`，确认 shell 返回再换下一台。

## E. 三台同时启动并做至少 5 分钟统计

```bash
ros2 launch piper_aio_ros2 three_realsense.launch.py config:=$PWD/config/cameras.yaml
```

另一个终端运行 300 秒统计；可以 `Ctrl+C` 提前清理，但提前结束不算 5 分钟性能验收：

```bash
./scripts/camera_status.sh --config config/cameras.yaml --sample-seconds 300 \
  | tee ~/realsense-status-$(date +%F-%H%M%S).json
```

三路必须为约定 topic、`sensor_msgs/msg/Image`、RGB8、640×480，timestamp 非零且不倒退；
这些是当前录制门禁。30 Hz 性能目标另用 `--require-nominal-rate` 检查：统计帧率在 27–33 Hz，
receive/header frame gap 不应超过 100 ms。同步观察 `dmesg --follow`
（若当前用户有权限）是否出现 USB reset/
disconnect，并用 inventory 的 physical port 判断是否把三台高带宽流都压在同一 root hub。

验收还必须人工做两项：运行时逐路看画面确认 front/left/right 没绑反；停止后逐台拔插、三台
重新插入并重启 launch，再确认相同 serial 仍映射到相同 topic。不要以设备枚举顺序或 `/dev/video*`
名称作为角色证据，也不要写 udev 规则去固定 video 编号。

## F. 现有 record preflight 与短 bag 读回

相机和独立获批的机械臂/teleop publisher 都已启动后，先检查 11 路白名单；缺任何一路都会失败：

```bash
ros2 run piper_aio_ros2 bag_preflight \
  --config config/record_topics.yaml --output-dir /data/piper/camera_check_001
```

先只闭环三相机，录 10 秒静态短包。脚本先做三路 preflight，拒绝覆盖目录，录完自动
`bag_inspect` 回读每路 type/count/rate；低于 30 Hz 会如实显示但不会伪造帧：

```bash
./scripts/record_cameras.sh /data/piper/camera_rgb_check_001 10
```

三路短包通过后，再在相机和独立获批的机械臂/teleop publisher 都已启动时做完整 11-topic 包。
`Ctrl+C` 正常结束；脚本拒绝覆盖已有目录：

```bash
timeout --signal=INT --kill-after=5s 10s \
  ./scripts/record_bag.sh /data/piper/camera_check_001 config/record_topics.yaml

ros2 run piper_aio_ros2 bag_inspect /data/piper/camera_check_001 \
  --config config/record_topics.yaml
```

再按 `docs/data_pipeline.md` 转 HDF5、validate，并人工抽取/观看 `cam_high`、
`cam_left_wrist`、`cam_right_wrist` 同一时刻图像，确认三路颜色、方向和角色。bag、图片、JSON
统计与 HDF5 都留在数据目录，不能提交 Git。只有真实短包读回和人工画面核对完成，才能说三路
没有绑反；配置/测试通过不等于真机通过。

## 停止与故障边界

- 所有 inventory/status 都有有界等待；`Ctrl+C` 会退出并销毁 status 的 ROS node。
- launch 在配置解析、serial 唯一性和当前在线检查通过前不会创建相机节点；不完整配置或无设备
  会立即非零退出，不会进入长期重试。
- 正常停止相机 launch 用一次 `Ctrl+C`。随后用 `ros2 node list | grep camera_` 检查无残留；
  如仍有旧节点，先识别其 PID/所属终端，不要用宽泛 `pkill`。
- 三台分别按 serial 启动的 type、RGB8、640×480@30 profile 已验证，且用户已根据按 serial
  命名的预览确认物理角色。Python status 在三路并发
  300 秒时只消费到约 10.9/13.6/14.9 Hz；但更贴近真实录制路径的 C++ rosbag recorder 在 9.84 秒
  短包中每路都写入 296 帧（共 888 帧），自动回读三路 type/count/header timestamp 成功，
  left/right header rate 约 29.98 Hz，front 因首尾 header 跨度显示约 26.88 Hz。由此不能把 Python
  status 的消费率直接当作相机发布率；30 Hz 长时性能仍待后续优化/验收。默认 status 把 rate/gap
  作为 warning，严格性能门禁需显式 `--require-nominal-rate`。拔插重连后的角色保持仍未验证。
- 写入正式角色配置后，`camera_f/l/r` 的 5 秒 status 均通过 type、唯一 publisher、RGB8、
  640×480 和 timestamp 门禁；front/right 约 29.98 Hz，left 约 28.97 Hz 且出现一次约 100 ms
  warning。随后 9.87 秒正式角色 zstd bag 自动读回成功：front/left/right 分别 297/296/294 帧，
  共 887 帧，三路类型和 header timestamp 正确。该短包证明当前绑定与录制 pipeline 可用，不是
  5 分钟性能、拔插重连或完整 11-topic episode 验收。
