# 实机闭环 TODO

截至 2026-08-13，本文件按真实依赖顺序记录从当前 v0.1 软件框架走到“三相机、双主臂、
双从臂、可采集真实 LeRobot 数据”的剩余工作。任务完成只以对应验收证据为准；代码存在、
单元测试通过、合成数据通过和真机通过是四个不同层级。

## 当前结论

| 能力 | 当前状态 | 已有证据与边界 |
|---|---|---|
| 四路 CAN 稳定绑定 | 语义修正已部署 | 重启后四路目标 serial、稳定接口名、1 Mbps、UP 检查通过；业务角色仍以逐侧运动回归为准 |
| 四臂 ROS 2 编排 | 映射已修正，待定量回归 | ROS 已恢复 left→`can_slave_l`、right→`can_slave_r`；四路节点和反馈可启动，仍需保存逐侧角色证据 |
| 真机主从遥操作 | 两阶段对齐已观察到真实收敛 | 100 Hz/100% 在 0.4 s 内收敛到 0.0321/0.0365 rad 静态残差；0.05 rad 完成门限尚待 live follow 回归 |
| RealSense ROS wrapper | 已安装，三台已绑定并可录 | 三台 D435 已按 serial→角色启动，正式角色 10 秒短包读回通过；长时性能/重连待验收 |
| bag → HDF5 → LeRobot v3 | 合成数据已验证 | 11-topic file/zstd 合成 bag 可转换；30 帧 HDF5 可导出并回读为 v3.0、三路 640×480 MP4；合并后的测试数见 `docs/PROGRESS.md` |
| 真实完整 episode | **尚未验证** | 还没有同时包含三相机、双主臂、双从臂反馈、双 EEF 和双 command 的真实 bag |
| 硬件 replay | **未实现，刻意禁用** | 当前 replay 只读 shape；`--execute` 明确拒绝，不创建 publisher |

所以当前不能表述为“整条真实 pipeline 已经没问题”。准确说法是：离线 schema、同步、压缩
bag 读取、HDF5 校验和 LeRobot v3 导出在合成输入上已经打通；真实输入、遥操作安全和长时间
稳定性仍需下面的 P0 验收。

## 依赖顺序

```text
四路 CAN + 官方驱动
          ├── 主臂 JointState ──> teleop bridge ──> 从臂 command
          └── 从臂 state / EEF ──────────────────────┐
                                                     ├── 11-topic rosbag
三台 RealSense ──> 固定 serial/role ──> 三路 RGB ───┘
                                                            │
                                                            v
                                      canonical HDF5 -> validate -> LeRobot v3
```

teleop bridge 和三相机 topic 是真实录包的两个前置条件，可以分别开发，但缺任意一个都不能做
完整 episode 验收。

## P0：先修正真实图上的录包门禁

- [x] 修正 `bag_preflight` 的 control-topic 检查。官方从臂节点会发布
  `/follower_left/joint_ctrl` 和 `/follower_right/joint_ctrl` 作为控制反馈；旧版按名称匹配
  `joint_ctrl` 的启发式检查会把它们误报成额外 command publisher。
- [x] 增加回归测试：允许已知官方反馈 topic；仍拒绝未知的 enable、position command 或额外
  joint command publisher。
- [ ] 在隔离 ROS domain 中同时模拟官方反馈 topic 和 11 个白名单 topic，确认 preflight、
  file/zstd 录包、inspect、HDF5 和 validate 全部通过。

其中“11 个白名单 publisher + 两个官方反馈 topic 的 preflight”已通过；本轮没有重复后续
file/zstd → HDF5 链，因为该链已有独立合成证据，尚未重跑二者组合。

验收：真实驱动节点存在时，preflight 只因真正缺流、类型错误、磁盘不足或未授权的 command
publisher 失败，不因官方反馈 topic 误报。

## P0：实现默认不动作的双臂 teleop bridge

- [x] 新增最小 `teleop` 节点、配置和独立 launch；不要把控制默认塞进 `four_arm.launch.py`。
- [x] 输入固定为 `/master_left/joint_states`、`/master_right/joint_states` 和两路 follower feedback；
  输出固定为 `/follower_left/joint_ctrl_cmd`、`/follower_right/joint_ctrl_cmd`。
- [x] 按 `JointState.name` 把官方主臂 9 维消息转换成 follower 需要的 7 维
  `joint1..joint6,gripper`；gripper 必须使用 `abs(joint7 - joint8)` 形成非负开度，不能直接取主臂第 7 个
  `gripper` 占位值。
- [x] 明确生成 follower 驱动使用的 `velocity[6]` 速度百分比和 `effort[6]` 夹爪力参数。
  不能原样转发 9 维 master 消息：官方驱动会把第 7 个 position 当夹爪，并可能退回 100%
  速度。
- [x] 默认 `armed=false`，未显式 arming 时不发布任何 command；bridge 永不自动调用
  `/follower_*/enable_srv`，从臂硬件使能保持独立、显式操作。
- [x] command 发布前同时满足：左右 master 新鲜、左右 follower feedback 新鲜、消息 finite、
  关节名称完整且输入不越界。显式 arm 后冻结 master 目标，第一条 command 保持 follower 当前姿态，
  随后以 100% 对齐冻结目标；双侧反馈连续稳定后才整体进入 live follow。master 漂移或 15 s 超时会
  fault，日志给出两侧剩余误差。
- [x] 加入保守且可配置的关节限位、单步最大变化、夹爪范围、发布频率和输入超时。超时或异常后
  停止发布并锁存 fault，必须人工重新 arming。
- [x] 让录包中的 `executed_action_*` 精确记录 bridge 实际发布的 7 维 command。这里的
  `executed` 仍表示“已发给驱动的 commanded action”，不是电机 ACK；物理跟踪看 follower state。
- [x] 纯函数测试覆盖：乱序 9D 映射、夹爪、左右隔离、首帧无跳变、冻结目标、settle、超时、双侧原子切换、
  command 限位、单步限制、stale 和 unarmed 零发布；再用隔离 ROS domain 做无硬件 topic/rate
  测试。

验收：不连接或不使能从臂也能证明节点默认零 command；合成 master 输入在显式 arming 后只产生
受限的 7D command；stale、越界和解除 arming 均立即停止新 command。

四条物理臂的夹爪存在由用户确认，四处 `gripper_exist` 保持 `true`。2026-08-13 未使能只读窗口
已确认两路真实 master 都按严格顺序发布 9D `joint1..joint6,gripper,joint7,joint8`，占位
`gripper=0`，且 `joint7+joint8=0`；当时原始 `joint7-joint8` 为左 `-0.0003 m`、右 `0.0 m`。
后续真机运动确认左右原始符号可能不同，因此 position canonical 统一取开度幅值；这不等于夹爪
完整行程或单位已经做过物理标定。

## P0：固定三台 RealSense 的物理角色

- [x] 三台相机的 serial、型号、firmware、USB 3.2 和 physical port inventory 已保存；用户根据
  serial-labelled 预览确认 front=`335622070696`、left=`349622073361`、
  right=`335622072178`，不是按输出顺序分配。
- [x] 新增 `config/cameras.yaml` 作为 serial → role 的唯一事实源，并新增只读
  inventory、assignment 与 `scripts/camera_status.sh`；当前空配置会严格失败，待真机填写。
- [x] 新增三相机 launch，按 serial 启动官方 ROS 2 wrapper，目标稳定输出：
  `/camera_f/color/image_raw`、`/camera_l/color/image_raw`、`/camera_r/color/image_raw`。
- [x] launch 参数固定 RGB8、640×480、30 Hz，depth、pointcloud 与 align depth 默认关闭；
  三台真实输出的 type/encoding/shape/timestamp 和短包已验证。
- [x] 正式角色配置下三路目标 topic/status 和 9.864 秒 zstd message-compressed bag 自动读回通过：
  front/left/right 各 297 帧，共 891 帧；这是绑定/录制 pipeline 验收，不是长时 30 Hz 验收。
- [ ] 检查每路 encoding、shape、header stamp、QoS、实际帧率和 USB 带宽；运行至少 5 分钟，
  记录掉帧、设备重连和 timestamp 跳变。

当前 Python status 消费率曾低于 30 Hz，但 C++ recorder 的短包已接近 30 Hz 并成功读回；按用户
决定，稳定角色绑定和正式三路短 bag 已完成，30 Hz 长时/Hub 拓扑作为后续性能优化，不阻塞
第一版录制 pipeline。

验收：重启或重新插拔后角色不交换；三路各自稳定约 30 Hz；record config 无需改 topic 即可通过
相机部分的 preflight。

## P0：分阶段真机遥操作验收

- [ ] 明确测试现场：从臂周围清空、急停可触达、先单侧后双侧、操作者明确口令；每一步都带
  timeout 和结束后的残留进程/CAN 状态检查。
- [x] 从臂软件 gate 未使能、bridge 未 arming：在隔离 ROS domain 整体启动四臂驱动，确认四路
  topic/schema/频率、namespace→CAN、两路 9D master 夹爪映射和 unarmed 零 command；未运动。
- [x] 用户完成初版未使能 arm、左右单侧和双侧运动流程；动作基本符合，但真实运动证明 follower
  已部署 `can_slave_l/r` 标签对应物理左右相反，且 10% 速度跟随过慢。该结果没有保存定量日志。
- [x] 安装已修正的 follower serial→稳定名规则并正常重启；只读确认物理左 serial 映射
  `can_slave_l`、物理右 serial 映射 `can_slave_r`，四路均为 1 Mbps、UP/ERROR-ACTIVE。
- [ ] 回归无 ROS 补偿的语义映射：`/follower_left` 使用 `can_slave_l`，`/follower_right` 使用
  `can_slave_r`；逐侧确认 master left/right 不再串到另一只物理 follower。
- [ ] 回归冻结目标的两阶段对齐：主从不必人工预先对齐，arm 后第一条 command 应等于各侧 follower
  当前反馈，后续 command 等于 arm 瞬间的 master 快照；两侧连续稳定 `0.3 s` 后才进入 live follow。
  硬件 enable 后由官方控制器以 100% 追踪，不执行机械零位回零；必须清空工作区并保持急停可触达。
- [ ] 回归左右夹爪完整张合：确认 master 原始正负号都归一化为非负开度，闭合至完全张开的
  `0.08 m` 配置范围可跟随，不再触发 70 mm 误停；记录实际最大开度后再标定门限。
- [ ] 以默认 100 Hz/100% 重新做左、右、双侧短时运动，记录 command/state 的方向、延迟、跟踪误差、
  停止行为和 `/actions/executed` 语义；若需继续提高速度，按一次一级的小步重新验收。
- [ ] 单独验证真实 stale/fault：fault 后 bridge 停发，但仍需人工 disable follower；验证前不得
  把 Ctrl+C 当作硬件 disable。

验收：默认启动不运动；任何缺流、stale、越界或解除 arming 都不再产生 command；单侧和双侧
方向、单位、夹爪、速度均经人工观察与记录确认。

### 下一次：用 tmux 回归 follower 左右、两阶段对齐与 100 Hz/100% 同步

- [ ] 重新 `colcon build --symlink-install`；不要继续使用已删除的 `/tmp/teleop_first_motion.yaml`。
  从仓库根目录运行 `./scripts/teleop_session.sh start`，确认左侧 30% DRIVER、右上 TELEOP、右下
  CONTROL 出现且未自动 enable/arm。
- [ ] 现场清空、急停可触达；确认没有旧 ROS/control 进程，四路 CAN 正常，且 follower 参数为
  left→`can_slave_l`、right→`can_slave_r`，两路 `auto_enable=false`。
- [ ] follower 不 enable，启动 teleop 并确认 unarmed 零 command；无需人工让四臂绝对对齐。
- [ ] 仅软件 arm，核对响应为 `armed; frozen-target alignment active; hold both masters still`、两路
  第一条 7D command 分别等于当前 follower feedback、后续 command 等于 arm 时冻结的 master 目标、
  `velocity[6]=100`、`effort[6]=1.0`，随后 disarm。
- [ ] 把两条 master 保持在安全且稳定的目标姿态；再依次仅 enable 左、仅 enable 右检查物理角色和
  对齐方向。单侧 enable 时另一侧不会到位，因此不应期待全局对齐完成。
- [ ] 两侧方向均通过后才同时 enable 两侧并 arm；观察每秒剩余误差和
  `dual-arm alignment complete; live follow active` 日志，再从小幅单关节开始确认 100 Hz/100% 同步，并按
  disarm→disable 顺序结束。
- [x] 双侧 arm 完整日志已确认约 100 Hz 发布，右 joint6 在 0.3 s 内从 `0.2013` 收敛到
  `0.0428 rad`，随后两侧停在 `0.0321/0.0365 rad` 的近零位静态残差；夹爪已进入容差。
  `/follower_*/joint_ctrl` 同时保持零值，不能在本机用作 command 消费证据或电机 ACK。
- [x] 基于上述真机收敛证据，将 `alignment_joint_tolerance_rad` 从 `0.02` 标定到 `0.05`；绝对自动
  对齐距离、master 漂移、step、stale 等其他安全门限不变。
- [ ] 重启新版本并再次双侧 arm；预期对齐收敛后稳定 `0.3 s`，约 `0.7 s` 报告
  `dual-arm alignment complete; live follow active`。随后只做小幅单关节和夹爪跟随，再逐步扩大。
- [ ] 保存 command/follower state 的短时 bag 或文本统计，至少记录跟踪方向、峰值误差、主观延迟、
  fault/停止行为；结束后检查无残留进程。

## P0：首个真实 episode 闭环

- [ ] 先录 10 秒静态 bag，再录一个 10–30 秒低速遥操作 bag；每次只使用显式 11-topic 白名单。
- [ ] `bag_inspect` 核对每路类型、count、rate、起止时间和 timestamp 来源。
- [ ] 转换到 HDF5，保存 QC JSON，核对 overlap、丢帧原因、同步 delta、有效帧数和
  `action_source=executed`。
- [ ] `validate_episode` 通过后导出 LeRobot v3；重新加载 Dataset，并逐路观看 MP4，确认左右、
  相机角色、颜色和时间方向正确。
- [ ] 人工抽查同一时刻的 master intent、实际 command、follower qpos 和 EEF，不能只检查 shape。
- [ ] 把 bag、HDF5、QC、LeRobot 输出保留在数据目录，不提交 Git；记录仓库 SHA、配置 SHA、CAN
  映射和相机 serial，保证 episode 可追溯。

验收：至少一个真实 episode 完成 record → inspect → HDF5 → validate → LeRobot reload，并有三路
视频和 command/state 对齐的人审记录。达到此项后才可把“真实数据 pipeline 已打通”写入进展文档。

## P1：稳定性和数据质量

- [ ] 逐步扩展到 5–10 分钟录制，测磁盘增长、CPU、内存、zstd 吞吐、丢帧和相机重连。
- [ ] 用真实统计重新设定 RGB/state/action 同步容差，不凭合成数据固定最终值。
- [ ] 增加 command 与 follower state 的跟踪误差、延迟和异常段 QC；必要时另录官方
  `/follower_*/joint_ctrl` 控制反馈，但不要混淆它和 bridge command。
- [ ] 决定 episode 失败后的清理/隔离策略，并验证磁盘不足、中断录包和部分 topic 消失时不会生成
  被误当成合格数据的输出。
- [ ] 完成多 episode 批量导出、任务标签约定、数据集版本和本地/Hub 发布边界。

## P2：replay 与策略推理

- [ ] 在真实数据合同稳定前继续保持硬件 replay 禁用。
- [ ] 先实现纯离线时间轴检查和可视化，再实现隔离 ROS domain 的 command replay。
- [ ] 若以后增加真机 `--execute`，必须复用 teleop 的 arming、绝对对齐、限位、单步限制、stale、
  显式 enable/disable 和单侧验收门禁；禁止从当前 dry-run 直接跳到双臂执行。

## v1 完成定义

- 三台相机按 serial 稳定绑定并通过 5 分钟采集检查。
- 四路机械臂角色、topic、单位和 gripper 映射全部真机确认。
- teleop 默认不动作、独立显式使能、故障锁存，并完成左、右、双侧分阶段验收。
- 至少一个真实 11-topic episode 完成全链路转换、QC、LeRobot v3 回读和视频人工抽查。
- 文档明确保留“commanded action 不等于电机 ACK”和“硬件 replay 尚未验证”的证据边界。

下一项 teleop 工作是回归 follower 稳定名、冻结目标的两阶段对齐和 100 Hz/100% 同步；不做四臂自动
机械回零。相机 serial 绑定必须等待三台设备实际接入后再填写，不能预造编号。
