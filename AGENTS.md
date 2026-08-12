# Repository operating rules

## Scope and protected repositories

- Changes belong only in `/home/engram/project/piper/piper_aio_ros2`.
- Keep `/home/engram/project/piper/piper_ros2`, `piper-aio`, and `piper_sdk` clean. Do not edit,
  commit, reset, or install generated files into those repositories.
- Preserve user changes. Check `git status`, `git diff`, and the current HEAD before editing.

## Hardware and privilege gates

- Without explicit user authorization, do not use `sudo`, write `/etc`, reload udev/systemd, change
  CAN state, enable arms, publish control commands, or move any arm.
- Without explicit user authorization, do not start `piper_single_ctrl`, teleop, `four_arm.launch.py`,
  or any launch path that can create control publishers or enable services.
- Hardware checks require a read-only preflight, a bounded timeout, and a postflight check for residual
  processes and unexpected CAN TX. `piper_read_slave_joint` performs non-zero query TX at startup.
- Never treat `auto_enable: false` as a complete safety system.

## Environment, data, and verification

- Default to Conda environment `piper`, ROS 2 Humble from `/opt/ros/humble`, then source the official
  `piper_ros2` install and this workspace install in that order.
- Do not commit bags, datasets, episodes, HDF5, videos, image output, or colcon `build/install/log`.
- Make the smallest scoped change and run the matching minimum check: `bash -n` for shell, Python
  compile/tests for Python, CAN parser tests for CAN config, and `colcon build/test` when dependencies
  are available.
- Documentation must label verified facts, unverified items, and evidence limits separately. Static
  checks and smoke tests are not hardware or complete-episode validation.
